"""MBPP prompts and resource ownership around the shared agent loop."""

from __future__ import annotations

from agent_smith.logging_config import get_logger

import argparse
import os
from pathlib import Path
import sys
import time
import uuid

from agent_smith.agent_loop import run_agent_loop
from agent_smith.mbpp_tools import cleanup_mbpp_containers
from agent_smith.mcp_client import MCPClient
from agent_smith.models import AgentLimits, MBPPTaskInput, SolutionOutput
from agent_smith.providers import ProviderClient
from agent_smith.sandbox import load_sandbox_config
from agent_smith.sandbox_session import SandboxSession

logger = get_logger('agent_smith.mbpp_agent')


CLEANUP_RESERVE_SECONDS = 5


def build_mbpp_system_prompt(mcp_manual: str) -> str:
    logger.debug("Entrando en build_mbpp_system_prompt")
    # The prompt is kept verbatim: wrapping its lines would change the text
    # the model receives. The noqa at the end covers its long lines.
    return '''Solve the supplied Python task using Thought -> Code -> Observation.
Write a Thought of at most 20 words and one closed ```python block, then <end_code>.
Keep code concise, without explanatory comments. Never discuss the delimiters.
Only Python in that block is executed. Variables persist between blocks.
Use print to inspect results. Never invent observations or search for solutions.
Keep the required function signature and solve the general problem.
Store your solution source in a raw triple-quoted string, preserving backslashes.
Do not also define the function in the worker.
Call run_tests with that code and the
supplied test_imports and test_list. Print its result, then stop and wait for the
real Observation before correcting the code or submitting it.
Example methodology for a separate addition task:
Thought: I will check my candidate against the supplied assertions.
```python
solution = r"""def add(a, b):
    return a + b
"""
print(run_tests(code=solution, test_imports=[], test_list=["assert add(2, 3) == 5"]))
```
<end_code>
After an Observation confirms success, submit in a NEW response:
```python
final_answer(solution)
```
<end_code>
final_answer is a local sandbox function. Pass complete solution code, not prose.
Public tests do not guarantee hidden-test success. Only the host supplies observations.
Available MCP manual:
''' + mcp_manual  # noqa: E501


def build_mbpp_task_prompt(task: MBPPTaskInput) -> str:
    logger.debug("Entrando en build_mbpp_task_prompt")
    return (
        f"Task {task.task_id}\n{task.task_definition}\n"
        f"Required signature: {task.function_definition}\n"
        "These public test variables are already defined in your worker:\n"
        f"test_imports = {task.test_imports!r}\n"
        f"test_list = {task.test_list!r}\n"
    )


def _build_mbpp_limits(max_iterations: int) -> AgentLimits:
    logger.debug("Entrando en _build_mbpp_limits")
    if max_iterations <= 0:
        raise ValueError("max_iterations must be positive.")
    return AgentLimits(
        max_iterations=min(max_iterations, 10), max_input_tokens=6000,
        max_output_tokens=1500, max_time_seconds=120,
    )


def run_mbpp_agent(
    task: MBPPTaskInput, args: argparse.Namespace, *, started_at: float,
) -> SolutionOutput:
    logger.debug("Entrando en run_mbpp_agent")
    logger.info("Preparando recursos de MBPP %s", task.task_id)
    result = SolutionOutput(
        task_id=str(task.task_id), benchmark="mbpp", success=False,
        solution="", iterations=0, total_requests=0, total_input_tokens=0,
        total_output_tokens=0, total_time_seconds=0,
    )
    client = sandbox = None
    session_id = uuid.uuid4().hex
    server_started = False
    try:
        limits = _build_mbpp_limits(args.max_iterations)
        deadline = (started_at + limits.max_time_seconds
                    - CLEANUP_RESERVE_SECONDS)
        logger.debug(
            "Límites: iteraciones=%s, tokens entrada=%s/salida=%s, "
            "total=%ss; reserva limpieza=%ss",
            limits.max_iterations, limits.max_input_tokens,
            limits.max_output_tokens, limits.max_time_seconds,
            CLEANUP_RESERVE_SECONDS,
        )
        if time.monotonic() >= deadline:
            raise TimeoutError("Task expired before setup.")

        # http client from environment vars. The default keeps the agent
        # working when its .env forgets AGENT_SMITH_MODELS_CONFIG: without
        # it every task ended with "Missing API key". "or" also covers the
        # variable being defined but empty.
        provider = ProviderClient.from_environment(
            args.provider_url, args.model_name,
            os.environ.get("AGENT_SMITH_MODELS_CONFIG")
            or "configs/models_template.json",
        )
        config = load_sandbox_config(
            os.environ.get("AGENT_SMITH_SANDBOX_CONFIG"))
        root = Path(__file__).resolve().parents[1]
        environment = {name: os.environ[name] for name in (
            "PATH", "DOCKER_HOST", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH",
        ) if name in os.environ}
        environment["AGENT_SMITH_DEADLINE"] = str(deadline)
        environment["AGENT_SMITH_MBPP_SESSION"] = session_id

        client = MCPClient(
            stdio_command=[sys.executable, str(root / "mcp_tools_mbpp.py")],
            environment=environment,
        )

        # MCP client also starts MCP server

        manual = client.start(deadline=deadline)
        logger.info("MCP listo: %s herramientas descubiertas",
                    len(manual.tools))
        server_started = True
        if not any(t["name"] == "run_tests" for t in manual.tools):
            raise RuntimeError("The MCP server did not advertise run_tests.")
        result.system_prompt = build_mbpp_system_prompt(manual.as_text())
        sandbox = SandboxSession(config, client, manual)
        sandbox.start()
        logger.debug("Inicializando test_imports y test_list en el "
                     "trabajador persistente")
        prepared = sandbox.execute(
            f"test_imports = {task.test_imports!r}\n"
            f"test_list = {task.test_list!r}",
            deadline=deadline,
        )
        if prepared.error or prepared.timed_out or prepared.worker_failed:
            raise RuntimeError(prepared.error
                               or "Could not prepare the public tests.")
        logger.info("Trabajador preparado; comenzando "
                    "Thought → Code → Observation")
        result = run_agent_loop(
            task_id=str(task.task_id), benchmark="mbpp",
            system_prompt=result.system_prompt,
            task_prompt=build_mbpp_task_prompt(task),
            provider=provider, sandbox=sandbox, limits=limits,
            started_at=started_at, deadline=deadline,
        )
    except Exception as exc:
        logger.exception("Fallo del adaptador MBPP; iniciando cierre de "
                         "recursos")
        result.success = False
        result.error = f"{type(exc).__name__}: {exc}"
    finally:
        logger.info("Limpieza MBPP: cerrando trabajador, MCP y contenedores "
                    "propios")
        cleanup_errors = []
        for resource in (sandbox, client):
            if resource is not None:
                try:
                    logger.debug("Cerrando %s", type(resource).__name__)
                    resource.close()
                except Exception as exc:
                    logger.error("No se pudo cerrar %s: %s",
                                 type(resource).__name__, exc)
                    cleanup_errors.append(f"{type(resource).__name__}: {exc}")
        if server_started:
            try:
                # A killed MCP server can no longer remove its own containers.
                # The task label limits this fallback to our own resources.
                cleanup_mbpp_containers(session_id)
            except Exception as exc:
                logger.error("Fallo en la limpieza Docker de respaldo: %s",
                             exc)
                cleanup_errors.append(f"Docker cleanup: {exc}")
        result.total_time_seconds = time.monotonic() - started_at
        if result.total_time_seconds > 120:
            cleanup_errors.append("Total task time exceeded 120 seconds.")
        if cleanup_errors:
            result.success = False
            result.error = "\n".join(
                filter(None, [result.error, *cleanup_errors]))
        logger.info("Fin MBPP: success=%s, tiempo total=%.3fs",
                    result.success, result.total_time_seconds)
        if result.error:
            logger.error("Motivo del fallo MBPP: %s", result.error)
    return result
