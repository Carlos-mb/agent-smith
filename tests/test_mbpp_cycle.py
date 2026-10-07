"""Controlled LLM responses; actual CLI, worker, MCP and Docker execution.

No external API is contacted and no generated/unknown code is executed.
These tests do not claim a benchmark pass or measured live-provider tokens.
"""

import json
import time
from pathlib import Path

import subprocess
import httpx
import openai
import pytest

from agent_mbpp import main
from agent_smith.mcp_client import MCPClient
from agent_smith.models import SolutionOutput
from agent_smith.providers import ProviderClient, ProviderConfig
from agent_smith.mbpp_tools import DEFAULT_DOCKER_IMAGE


ROOT = Path(__file__).resolve().parents[1]


def require_docker():
    try:
        ready = subprocess.run(["docker", "image", "inspect", DEFAULT_DOCKER_IMAGE],
                               capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        ready = False
    if not ready:
        pytest.skip("Docker/image unavailable")


def session_containers(session_id):
    return subprocess.run(["docker", "ps", "-aq", "--filter", f"label=agent-smith.mbpp.session={session_id}"],
                          capture_output=True, text=True).stdout.split()


def test_mcp_discovers_run_tests_and_closes():
    client = MCPClient(stdio_command=[str(ROOT / ".venv/bin/python"), str(ROOT / "mcp_tools_mbpp.py")])
    try:
        manual = client.start(deadline=time.monotonic() + 15)
        assert any(tool["name"] == "run_tests" for tool in manual.tools)
        assert "test_imports" in manual.as_text()
    finally:
        client.close()
    assert client._loop is None
    client.close()


@pytest.mark.parametrize("log_level", [None, "DEBUG"])
def test_cli_wrong_candidate_then_correction_and_final_answer(tmp_path, monkeypatch, capfd, log_level):
    require_docker()
    from agent_smith import logging_config
    monkeypatch.setattr(logging_config, "_secrets", set())
    if log_level is None:
        monkeypatch.delenv("AGENT_SMITH_LOG_LEVEL", raising=False)
    else:
        monkeypatch.setenv("AGENT_SMITH_LOG_LEVEL", log_level)
    capfd.readouterr()
    histories = []
    replies = [
        "```python\nsolution = 'def add(a, b):\\n    return 0'\n"
        "print(run_tests(code=solution, test_imports=test_imports, test_list=test_list))\n```",
        "```python\nsolution = 'def add(a, b):\\n    return a + b'\n"
        "print(run_tests(code=solution, test_imports=test_imports, test_list=test_list))\n```",
        "```python\nfinal_answer(solution)\n```",
    ]
    def handler(request):
        payload = json.loads(request.content)
        histories.append(payload["messages"])
        index = len(histories) - 1
        if index == 1:
            assert "AssertionError" in histories[-1][-1]["content"]
        if index == 2:
            assert "All public tests passed" in histories[-1][-1]["content"]
        return httpx.Response(200, json={
            "choices": [{"message": {"content": replies[index]}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        })
    monkeypatch.setattr("agent_smith.providers.OpenAI", lambda **kwargs: openai.OpenAI(
        http_client=httpx.Client(transport=httpx.MockTransport(handler)), **kwargs))
    provider = ProviderClient(ProviderConfig(
        api_url="https://example.invalid/v1", model_name="controlled-fixture",
        api_key_environment_variables=["TEST_KEY"],
    ), {"TEST_KEY": "not-a-real-key"})
    monkeypatch.setattr(ProviderClient, "from_environment", lambda *args, **kwargs: provider)
    task = tmp_path / "task.json"
    result_path = tmp_path / "solution.json"
    task.write_text(json.dumps({
        "task_id": 1, "task_definition": "Add two numbers.",
        "function_definition": "def add(a, b):", "test_imports": [],
        "test_list": ["assert add(2, 3) == 5"],
    }))
    assert main(["--task-file", str(task), "--output", str(result_path),
                 "--model-name", "controlled-fixture", "--provider-url", "https://example.invalid/v1"]) == 0
    result = SolutionOutput.model_validate_json(result_path.read_text())
    assert result.success, result.error
    assert result.solution == "def add(a, b):\n    return a + b"
    assert len(histories) == result.iterations == result.total_requests == 3
    assert result.total_input_tokens == 300 and result.total_output_tokens == 150
    assert "AssertionError" in result.steps[0].sandbox_output
    assert "All public tests passed" in result.steps[1].sandbox_output
    assert result.total_time_seconds < 120
    captured = capfd.readouterr()
    assert captured.out == ""
    if log_level is None:
        assert captured.err == ""
    else:
        for expected in (
            "agent_smith.agent_mbpp.main", "ProviderClient.complete",
            "agent_smith.sandbox.worker_main", "execute_block", "mcp_tools_mbpp",
            "Tests públicos fallidos", "Tests públicos correctos",
            "Observación real", "final_answer recibido",
            "IA RECIBIDO [HTTP 200", "MCP ENVIADO [call_tool]", "MCP RECIBIDO [call_tool]",
            "MCP RECIBIDO [initialize]", "MCP RECIBIDO [listado tools]",
            "DOCKER ENTRADA", "DOCKER SALIDA", "stdout/stderr combinados",
        ):
            assert expected in captured.err
        for history in histories:
            for number, message in enumerate(history, start=1):
                assert (
                    f"IA ENVIADO [mensaje {number}, rol={message['role']}]:\n{message['content']}"
                    in captured.err
                )
        assert captured.err.count("IA ENVIADO [mensaje 1, rol=system]") == 3
        assert captured.err.count("MCP ENVIADO [call_tool]") == 2
        assert captured.err.count("MCP RECIBIDO [call_tool]") == 2
        assert '"name": "run_tests"' in captured.err
        for expression in ("0", "a + b"):
            assert (
                "programa completo:\ndef add(a, b):\n    return " + expression
                + "\n\nassert add(2, 3) == 5\n"
            ) in captured.err
        assert "not-a-real-key" not in captured.err
        assert "Processing request of type" not in captured.err
        # Retain the real controlled trace for inspection without calling an API.
        (tmp_path / "debug.log").write_text(captured.err)


def test_ctrl_c_during_docker_tool_cleans_owned_container(monkeypatch):
    """Press Ctrl+C only after Docker confirms its known infinite loop started."""
    import argparse
    import os
    import signal
    import threading
    from agent_smith.mbpp_agent import run_mbpp_agent
    from agent_smith.models import MBPPTaskInput
    from agent_smith.providers import CompletionResponse

    require_docker()
    session_ids = []
    original_init = MCPClient.__init__
    def capture_session(self, **kwargs):
        session_ids.append(kwargs["environment"]["AGENT_SMITH_MBPP_SESSION"])
        original_init(self, **kwargs)
    monkeypatch.setattr(MCPClient, "__init__", capture_session)
    class Provider:
        config = ProviderConfig(api_url="https://example.invalid/v1", model_name="fixture")
        def complete(self, messages, **kwargs):
            return CompletionResponse(
                "```python\nprint(run_tests(code='while True: pass', test_imports=[], test_list=[], timeout_seconds=30))\n```",
                100, 50, 1, self.config.api_url, "fixture", 0, 1,
            )
    monkeypatch.setattr(ProviderClient, "from_environment", lambda *args, **kwargs: Provider())
    pressed = []

    def press_ctrl_c_when_container_runs():
        for _ in range(200):
            if session_ids and session_containers(session_ids[0]):
                pressed.append(True)
                os.kill(os.getpid(), signal.SIGINT)
                return
            time.sleep(0.05)

    watcher = threading.Thread(target=press_ctrl_c_when_container_runs, daemon=True)
    watcher.start()
    try:
        with pytest.raises(KeyboardInterrupt):
            run_mbpp_agent(
                MBPPTaskInput(task_id=1, task_definition="fixture", function_definition="def add(a, b):"),
                argparse.Namespace(max_iterations=2, provider_url="https://example.invalid/v1", model_name="fixture"),
                started_at=time.monotonic(),
            )
        assert pressed, "Docker test did not start."
        assert not session_containers(session_ids[0])
    finally:
        watcher.join(timeout=15)
