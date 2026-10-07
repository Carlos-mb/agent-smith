"""Tests for the SWE-bench prompts, limits and container lifecycle."""

import subprocess
import sys
import time
from pathlib import Path

import pytest

from agent_smith.models import SWEBenchTaskInput
from agent_smith.swebench_agent import (
    SWEEnvironment, _build_swebench_limits, build_swebench_system_prompt,
    build_swebench_task_prompt,
)


TEST_IMAGE = "agent-smith-swebench-test:latest"
DOCKERFILE = """FROM python:3.10.12-slim
RUN mkdir -p /testbed && printf 'def add(a, b):\\n    return a + b\\n' > /testbed/main.py
"""


def _docker_available() -> bool:
    try:
        return subprocess.run(
            ["docker", "info"], capture_output=True, timeout=30, check=False
        ).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


needs_docker = pytest.mark.skipif(not _docker_available(), reason="Docker is not available")


@pytest.fixture(scope="module")
def test_image():
    """Build a tiny image that has a /testbed, like a real SWE-bench image."""
    subprocess.run(
        ["docker", "build", "-t", TEST_IMAGE, "-"],
        input=DOCKERFILE, text=True, capture_output=True, timeout=300, check=True,
    )
    yield TEST_IMAGE
    subprocess.run(["docker", "rmi", "-f", TEST_IMAGE], capture_output=True, check=False)


def _task(**overrides) -> SWEBenchTaskInput:
    values = {
        "instance_id": "demo__demo-1", "problem_statement": "Pipeline should implement __len__",
        "docker_image": TEST_IMAGE, "eval_script": "echo running", "repo": "demo/demo",
    }
    values.update(overrides)
    return SWEBenchTaskInput(**values)


def test_limits_follow_the_subject():
    limits = _build_swebench_limits(30)

    assert (limits.max_iterations, limits.max_input_tokens) == (30, 300_000)
    assert (limits.max_output_tokens, limits.max_time_seconds) == (10_000, 900)


def test_limits_cap_the_requested_iterations_and_reject_zero():
    assert _build_swebench_limits(100).max_iterations == 30
    assert _build_swebench_limits(3).max_iterations == 3
    with pytest.raises(ValueError):
        _build_swebench_limits(0)


def test_task_prompt_carries_the_issue_without_execution_details():
    prompt = build_swebench_task_prompt(_task(hints_text="maybe use __len__"))

    assert "demo__demo-1" in prompt and "demo/demo" in prompt
    assert "Pipeline should implement __len__" in prompt
    assert "maybe use __len__" in prompt
    # La imagen y el eval_script son cosa del adaptador, no ordenes para el modelo.
    assert TEST_IMAGE not in prompt and "echo running" not in prompt


def test_task_prompt_omits_absent_hints():
    assert "Hints" not in build_swebench_task_prompt(_task(hints_text=""))


def test_system_prompt_embeds_the_manual_and_the_submission_rule():
    prompt = build_swebench_system_prompt("MANUAL_MARKER")

    assert prompt.endswith("MANUAL_MARKER")
    assert "final_answer(get_patch())" in prompt
    assert "never an MCP tool" in prompt


def test_start_refuses_a_task_without_an_image():
    environment = SWEEnvironment(_task(docker_image=""), deadline=time.monotonic() + 60)

    with pytest.raises(RuntimeError, match="does not name a Docker image"):
        environment.start()


def test_start_refuses_an_expired_deadline():
    environment = SWEEnvironment(_task(), deadline=time.monotonic() - 1)

    with pytest.raises(TimeoutError):
        environment.start()


def test_close_without_start_does_nothing():
    SWEEnvironment(_task(), deadline=time.monotonic() + 60).close()


def _container_exists(name: str) -> bool:
    completed = subprocess.run(
        ["docker", "ps", "-a", "--filter", f"name={name}", "--format", "{{.Names}}"],
        text=True, capture_output=True, check=False,
    )
    return name in completed.stdout.split()


@needs_docker
def test_environment_starts_one_container_and_removes_it(test_image):
    environment = SWEEnvironment(_task(), deadline=time.monotonic() + 300)
    try:
        environment.start()
        container_id = environment.container_id
        assert _container_exists(container_id)

        exported = environment.mcp_environment()
        assert exported["AGENT_SMITH_CONTAINER_ID"] == container_id
        assert exported["AGENT_SMITH_EVAL_SCRIPT"] == "echo running"
    finally:
        environment.close()

    assert not _container_exists(container_id)
    assert environment.started is False


@needs_docker
def test_mcp_environment_requires_a_running_container():
    environment = SWEEnvironment(_task(), deadline=time.monotonic() + 60)

    with pytest.raises(RuntimeError, match="not running"):
        environment.mcp_environment()


@needs_docker
def test_tools_reach_the_started_container(test_image, monkeypatch):
    from agent_smith import swebench_tools

    environment = SWEEnvironment(_task(), deadline=time.monotonic() + 300)
    try:
        environment.start()
        for name, value in environment.mcp_environment().items():
            monkeypatch.setenv(name, value)

        assert "/testbed/main.py" in swebench_tools.list_files("/testbed", "*.py")
        assert "1: def add(a, b):" in swebench_tools.read_file("/testbed/main.py", 1, 1)
        assert "running" in swebench_tools.run_tests()
    finally:
        environment.close()


KILL_SCRIPT = """
import sys, time
sys.path.insert(0, {root!r})
from agent_smith.models import SWEBenchTaskInput
from agent_smith.swebench_agent import SWEEnvironment

task = SWEBenchTaskInput(
    instance_id="demo__demo-1", problem_statement="x",
    docker_image={image!r}, eval_script="echo running",
)
environment = SWEEnvironment(task, deadline=time.monotonic() + 300)
environment.start()
print(environment.container_id, flush=True)
time.sleep(300)
"""


@needs_docker
def test_a_hard_killed_agent_leaves_no_container(test_image, tmp_path):
    # La hoja de evaluacion mata el agente a mitad de tarea y comprueba que no
    # queda contenedor. Ningun finally se ejecuta tras un SIGKILL, asi que el
    # contenedor tiene que apagarse solo al cerrarse la tuberia que lo sostiene.
    script = tmp_path / "agente.py"
    root = str(Path(__file__).resolve().parents[1])
    script.write_text(KILL_SCRIPT.format(root=root, image=test_image))

    agent = subprocess.Popen(
        [sys.executable, str(script)], stdout=subprocess.PIPE, text=True,
    )
    try:
        name = agent.stdout.readline().strip()
        assert name.startswith("agent-smith-")
        assert _container_exists(name)

        agent.kill()
        agent.wait(timeout=30)

        for _ in range(60):
            if not _container_exists(name):
                break
            time.sleep(0.5)
        assert not _container_exists(name), "el contenedor sobrevivio al kill -9"
    finally:
        if agent.poll() is None:
            agent.kill()
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)


def test_system_prompt_forbids_submitting_without_a_change():
    prompt = build_swebench_system_prompt("MANUAL")

    assert "Never call final_answer until get_patch shows your change" in prompt


def test_system_prompt_warns_that_the_sandbox_cannot_import_the_project():
    # Un modelo gasto 4 de 12 iteraciones intentando `import sympy` en el sandbox.
    prompt = build_swebench_system_prompt("MANUAL")

    assert "cannot import the project" in prompt
    assert "run_command" in prompt
