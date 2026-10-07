"""Tests for the MBPP test execution helper."""

import logging
import subprocess
import time

import pytest

from agent_smith.mbpp_tools import (
    DEFAULT_DOCKER_IMAGE,
    MAX_OUTPUT_CHARACTERS,
    build_test_program,
    run_mbpp_tests,
)


def docker_image_is_ready() -> bool:
    """Return True when Docker and the required Python image are available."""
    try:
        return subprocess.run(["docker", "image", "inspect", DEFAULT_DOCKER_IMAGE],
                              capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


needs_docker = pytest.mark.skipif(not docker_image_is_ready(), reason="Docker image is not available")


def test_build_test_program() -> None:
    """The helper must place imports before the solution and assertions."""
    program = build_test_program(
        code="def add(a, b):\n    return a + b",
        test_imports=["import math"],
        test_list=["assert add(2, 3) == 5"],
    )

    assert program.index("def add") > program.index("import math")
    assert program.index("import math") < program.index("assert add")


@needs_docker
def test_run_mbpp_tests_success() -> None:
    result = run_mbpp_tests("def add(a, b):\n    return a + b", [], ["assert add(2, 3) == 5"])
    assert result["success"] is True
    assert result["exit_code"] == 0


@needs_docker
def test_run_mbpp_tests_failure() -> None:
    result = run_mbpp_tests("def add(a, b):\n    return 0", [], ["assert add(2, 3) == 5"])
    assert result["success"] is False
    assert result["message"] == "Public tests failed."
    assert "AssertionError" in result["output"]


@needs_docker
def test_run_mbpp_tests_syntax_error() -> None:
    """Invalid Python must return the syntax error without crashing the server."""
    result = run_mbpp_tests("def add(a, b)\n    return a + b", [], ["assert add(2, 3) == 5"])
    assert result["success"] is False
    assert "SyntaxError" in result["output"]


@needs_docker
def test_timeout_keeps_partial_output_and_removes_the_container(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_SMITH_MBPP_SESSION", "timeout-test")
    result = run_mbpp_tests("print('before timeout')\nwhile True: pass", [], [], timeout_seconds=3)
    assert result["success"] is False and result["exit_code"] is None
    assert result["message"] == "Public tests could not complete."
    assert "timed out after 3 seconds" in result["output"]
    assert "before timeout" in result["output"]
    left = subprocess.run(["docker", "ps", "-aq", "--filter", "label=agent-smith.mbpp.session=timeout-test"],
                          capture_output=True, text=True).stdout
    assert left == ""


@needs_docker
def test_debug_keeps_full_docker_output_before_truncation(caplog) -> None:
    code = f"print('DOCKER_BEGIN')\nprint('x' * {MAX_OUTPUT_CHARACTERS})\nprint('DOCKER_END')"
    with caplog.at_level(logging.DEBUG, logger="agent_smith.mbpp_tools"):
        result = run_mbpp_tests(code, [], [])
    assert "DOCKER_END" in caplog.text
    assert "DOCKER_END" not in result["output"]
    assert "Output truncated" in result["output"]


def test_docker_own_failure_is_not_a_test_failure(monkeypatch) -> None:
    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 125, "No such image: python:3.10.12-slim")
    monkeypatch.setattr("agent_smith.mbpp_tools.subprocess.run", fake_run)
    result = run_mbpp_tests("pass", [], [])
    assert result["success"] is False and result["exit_code"] is None
    assert result["message"] == "Public tests could not start."
    assert "docker pull" in result["output"]


def test_task_deadline_stops_before_running_docker(monkeypatch) -> None:
    def fail(*args, **kwargs):
        pytest.fail("Docker must not run after the deadline.")
    monkeypatch.setattr("agent_smith.mbpp_tools.subprocess.run", fail)
    monkeypatch.setenv("AGENT_SMITH_DEADLINE", "0")
    result = run_mbpp_tests("pass", [], [])
    assert not result["success"]
    assert "deadline" in result["output"].lower()


def test_task_deadline_limits_the_timeout(monkeypatch) -> None:
    seen = []
    def fake_run(command, **kwargs):
        seen.append(kwargs["timeout"])
        return subprocess.CompletedProcess(command, 0, "")
    monkeypatch.setattr("agent_smith.mbpp_tools.subprocess.run", fake_run)
    monkeypatch.setenv("AGENT_SMITH_DEADLINE", str(time.monotonic() + 4))
    assert run_mbpp_tests("pass", [], [], timeout_seconds=30)["success"]
    assert 0 < seen[0] <= 2
