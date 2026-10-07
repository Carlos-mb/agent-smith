"""Run a candidate MBPP solution against its public tests inside Docker.

Each call runs one short-lived container with the `docker` command, the same
way the SWE-bench tools do: no network, limited memory and CPU, removed when it
ends (--rm). A label with the task's session id lets the agent remove anything
left behind if the MCP server dies while a container is still running.
"""

from agent_smith.logging_config import get_logger

import os
import subprocess
import time
import uuid
from typing import Any

logger = get_logger('agent_smith.mbpp_tools')


DEFAULT_DOCKER_IMAGE = "python:3.11-slim"
DEFAULT_TIMEOUT_SECONDS = 10
MAX_OUTPUT_CHARACTERS = 12_000
SESSION_LABEL = "agent-smith.mbpp.session"


def build_test_program(
    code: str,
    test_imports: list[str],
    test_list: list[str],
) -> str:
    """Combine a candidate solution with the public MBPP tests."""
    logger.debug("Entrando en build_test_program")
    logger.debug("Preparando programa de tests: imports=%s, aserciones=%s, "
                 "código=%s caracteres",
                 len(test_imports), len(test_list), len(code))

    sections = []
    sections.extend(item.strip() for item in test_imports if item.strip())
    sections.append(code.strip())
    sections.extend(item.strip() for item in test_list if item.strip())
    return "\n\n".join(section for section in sections if section) + "\n"


def truncate_output(output: str) -> str:
    """Limit tool output so one failed test does not fill the prompt."""
    logger.debug("Entrando en truncate_output")
    if len(output) <= MAX_OUTPUT_CHARACTERS:
        return output

    removed = len(output) - MAX_OUTPUT_CHARACTERS
    logger.warning("Salida Docker truncada: se omiten %s caracteres", removed)
    return (
        output[:MAX_OUTPUT_CHARACTERS]
        + f"\n\n[Output truncated: {removed} characters were removed.]"
    )


def _result(success: bool, message: str, output: str,
            exit_code: int | None) -> dict[str, Any]:
    """Build the dictionary returned to the model."""
    return {"success": success, "message": message, "output": output,
            "exit_code": exit_code}


def run_mbpp_tests(
    code: str,
    test_imports: list[str],
    test_list: list[str],
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Run the candidate and its tests in one container and report the result."""
    logger.debug("Entrando en run_mbpp_tests")
    logger.info("Tests MBPP solicitados: %s aserciones, timeout=%ss",
                len(test_list), timeout_seconds)
    if not code.strip():
        logger.warning("No se ejecutarán tests: candidato vacío")
        return _result(False, "Public tests were not executed.",
                       "The candidate solution is empty.", None)

    # The task deadline (set by the agent) wins over the requested timeout,
    # keeping two seconds to remove the container.
    timeout = float(timeout_seconds)
    if os.environ.get("AGENT_SMITH_DEADLINE"):
        left = float(os.environ["AGENT_SMITH_DEADLINE"]) - time.monotonic() - 2
        timeout = min(timeout, left)
    if timeout <= 0:
        logger.warning("No se ejecutarán tests: sin tiempo o timeout no "
                       "positivo")
        return _result(False, "Public tests were not executed.",
                       "No time left: the task deadline was reached or "
                       "timeout_seconds is not positive.", None)

    program = build_test_program(code, test_imports, test_list)
    name = "agent-smith-mbpp-" + uuid.uuid4().hex
    session = os.environ.get("AGENT_SMITH_MBPP_SESSION", "standalone")
    command = [
        "docker", "run", "--rm", "--name", name,
        "--label", f"{SESSION_LABEL}={session}",
        "--network", "none", "--memory", "128m",
        "--pull", "never", DEFAULT_DOCKER_IMAGE,
        "python", "-u", "-c", program,
    ]
    logger.info("Ejecutando contenedor %s con imagen %s; timeout=%.1fs",
                name, DEFAULT_DOCKER_IMAGE, timeout)
    logger.debug("DOCKER ENTRADA [%s]: python -u -c; programa completo:\n%s",
                 name, program)
    try:
        completed = subprocess.run(
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        # Stopping the docker command does not stop its container.
        partial = exc.output or b""
        if isinstance(partial, bytes):
            partial = partial.decode("utf-8", errors="replace")
        logger.warning("Tests fuera de tiempo; eliminando el contenedor")
        logger.debug("DOCKER SALIDA PARCIAL [%s, stdout/stderr "
                     "combinados]:\n%s", name, partial or "[sin salida]")
        subprocess.run(["docker", "rm", "-f", name], capture_output=True,
                       timeout=10, check=False)
        return _result(False, "Public tests could not complete.",
                       f"Execution timed out after {timeout:.0f} seconds.\n"
                       "Output is partial:\n"
                       + truncate_output(partial.strip()), None)

    output = completed.stdout
    logger.debug("DOCKER SALIDA [%s, exit_code=%s, stdout/stderr "
                 "combinados]:\n%s", name, completed.returncode,
                 output or "[sin salida]")
    if completed.returncode == 0:
        logger.info("Tests públicos correctos")
        return _result(True, "All public tests passed.",
                       truncate_output(output.strip()), 0)
    if completed.returncode == 125:
        # 125 is Docker's own failure (no image, no daemon), not the tests'.
        logger.error("Docker no pudo arrancar el contenedor: %s", output)
        return _result(False, "Public tests could not start.",
                       f"Docker error: {output.strip()}\n"
                       f"Is the image ready? docker pull {DEFAULT_DOCKER_IMAGE}",
                       None)
    logger.warning("Tests públicos fallidos: exit_code=%s",
                   completed.returncode)
    return _result(False, "Public tests failed.",
                   truncate_output(output.strip())
                   or "The test process failed without output.",
                   completed.returncode)


def cleanup_mbpp_containers(session_id: str) -> None:
    """Remove this task's containers after MCP closes, even after Ctrl+C."""
    logger.debug("Entrando en cleanup_mbpp_containers")
    listing = subprocess.run(
        ["docker", "ps", "-aq", "--filter",
         f"label={SESSION_LABEL}={session_id}"],
        capture_output=True, text=True, timeout=10, check=False,
    )
    for container in listing.stdout.split():
        logger.info("Eliminando contenedor restante de la tarea: %s",
                    container)
        subprocess.run(["docker", "rm", "-f", container],
                       capture_output=True, timeout=10, check=False)
    logger.debug("Comprobación de limpieza Docker completada")
