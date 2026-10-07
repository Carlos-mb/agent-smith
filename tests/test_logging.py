"""Logging is opt-in, readable across processes, and separate from JSON data."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


def environment(level):
    result = dict(os.environ)
    result.pop("AGENT_SMITH_LOG_LEVEL", None)
    if level is not None:
        result["AGENT_SMITH_LOG_LEVEL"] = level
    return result


@pytest.mark.parametrize("level, expected", [
    (None, []), ("", []), ("DEBUG", ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]),
    ("info", ["INFO", "WARNING", "ERROR", "CRITICAL"]),
    ("WARNING", ["WARNING", "ERROR", "CRITICAL"]),
    ("ERROR", ["ERROR", "CRITICAL"]), ("CRITICAL", ["CRITICAL"]),
])
def test_levels_stderr_only_and_no_duplicate_or_sdk_logs(level, expected):
    code = '''
import logging
from agent_smith.logging_config import configure_logging, get_logger
configure_logging()
configure_logging()
logger = get_logger("logging_test")
for name in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
    logger.log(getattr(logging, name), "event_" + name)
logging.getLogger("httpcore").critical("SDK Authorization header should stay private")
'''
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=environment(level),
                            text=True, capture_output=True, timeout=10)
    assert result.returncode == 0 and result.stdout == ""
    for name in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        assert result.stderr.count("event_" + name) == (1 if name in expected else 0)
    assert "SDK Authorization" not in result.stderr
    if not expected:
        assert result.stderr == ""


def test_invalid_level_reports_error_without_echoing_its_value():
    result = subprocess.run([sys.executable, "-c", "import agent_smith.providers"],
                            cwd=ROOT, env=environment("mistyped-private-value"),
                            text=True, capture_output=True, timeout=10)
    assert result.returncode == 0 and result.stdout == ""
    assert "not valid; using ERROR" in result.stderr
    assert "mistyped-private-value" not in result.stderr


def test_custom_provider_keys_are_redacted_in_messages_and_tracebacks():
    code = '''
from agent_smith.providers import ProviderClient, ProviderConfig
from agent_smith.logging_config import get_logger
ProviderClient(ProviderConfig(api_url="https://example.invalid", model_name="fixture",
    api_key_environment_variables=["CUSTOM_KEY"]), {"CUSTOM_KEY": "private-test-credential"})
logger = get_logger("test")
logger.info("Echo: %s", "private-test-credential")
try:
    raise RuntimeError("server echoed private-test-credential")
except RuntimeError:
    logger.exception("Operation failed")
'''
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=environment("DEBUG"),
                            text=True, capture_output=True, timeout=10)
    assert result.returncode == 0 and result.stdout == ""
    assert "private-test-credential" not in result.stderr
    assert "[REDACTED]" in result.stderr and "RuntimeError" in result.stderr


@pytest.mark.parametrize("level", [None, "INFO", "DEBUG"])
@pytest.mark.parametrize("reply_kind", ["json", "non_json_error"])
def test_ai_exchange_logs_full_history_and_body_only_in_debug(level, reply_kind):
    code = '''
import json
import sys
import time
import httpx
from agent_smith.providers import ProviderClient, ProviderConfig

messages = [
    {"role": "system", "content": "SYSTEM_MARKER\\nComplete instructions."},
    {"role": "user", "content": "TASK_MARKER"},
    {"role": "assistant", "content": "PREVIOUS_REPLY_MARKER"},
    {"role": "user", "content": "OBSERVATION_MARKER\\nCorrect the previous failure."},
]
def handler(request):
    assert json.loads(request.content)["messages"] == messages
    assert request.headers["Authorization"] == "Bearer private-test-credential"
    if sys.argv[1] == "json":
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "REPLY_MARKER private-test-credential"}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20},
        })
    return httpx.Response(503, text="ERROR_BODY_MARKER private-test-credential")

import openai
import agent_smith.providers
agent_smith.providers.OpenAI = lambda **kwargs: openai.OpenAI(
    http_client=httpx.Client(transport=httpx.MockTransport(handler)), **kwargs)
client = ProviderClient(ProviderConfig(api_url="https://example.invalid/v1", model_name="fixture",
    api_key_environment_variables=["CUSTOM_KEY"], max_retries=0),
    {"CUSTOM_KEY": "private-test-credential"})
result = client.complete(messages, max_input_tokens=6000, max_output_tokens=500,
                                    deadline=time.monotonic() + 5)
assert result.request_count == 1
assert (result.error is None) == (sys.argv[1] == "json")
'''
    result = subprocess.run([sys.executable, "-c", code, reply_kind], cwd=ROOT,
                            env=environment(level), text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert "private-test-credential" not in result.stderr
    assert "Bearer" not in result.stderr
    for marker in ("SYSTEM_MARKER", "TASK_MARKER", "PREVIOUS_REPLY_MARKER", "OBSERVATION_MARKER",
                   "REPLY_MARKER" if reply_kind == "json" else "ERROR_BODY_MARKER"):
        assert (marker in result.stderr) == (level == "DEBUG")
    if level == "DEBUG":
        assert result.stderr.count("IA ENVIADO [mensaje") == 4
        assert "IA RECIBIDO [HTTP" in result.stderr and "[REDACTED]" in result.stderr
    elif level is None:
        assert result.stderr == ""


WORKER_SCRIPT = """
from agent_smith.models import SandboxConfig
from agent_smith.sandbox_session import SandboxSession
sandbox = SandboxSession(SandboxConfig())
sandbox.start()
try:
    result = sandbox.execute("print('hello'); final_answer('done')")
    assert result.output == "hello\\n" and result.final_answer == "done"
finally:
    sandbox.close()
"""


@pytest.mark.parametrize("level", [None, "DEBUG"])
def test_worker_logs_go_to_stderr_never_to_stdout(level):
    result = subprocess.run([sys.executable, "-c", WORKER_SCRIPT], cwd=ROOT,
                            env=environment(level), text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    if level:
        assert "worker_main" in result.stderr and "final_answer capturado" in result.stderr
    else:
        assert result.stderr == ""


def test_debug_writes_one_file_shared_by_the_agent_and_the_worker(debug_log_file):
    result = subprocess.run([sys.executable, "-c", WORKER_SCRIPT], cwd=ROOT,
                            env=environment("DEBUG"), text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    text = debug_log_file.read_text()
    assert "SandboxSession.start" in text and "worker_main" in text
    assert "Código recibido del agente" in text and "Salida del bloque" in text
    process_ids = {line.split("[pid=")[1].split("]")[0] for line in text.splitlines() if "[pid=" in line}
    assert len(process_ids) == 2


def test_no_log_file_below_debug(debug_log_file):
    result = subprocess.run([sys.executable, "-c", WORKER_SCRIPT], cwd=ROOT,
                            env=environment("INFO"), text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert not debug_log_file.exists()


def test_startup_failure_is_reported_with_its_cause_on_stderr():
    code = """
from agent_smith.models import SandboxConfig
from agent_smith.sandbox_session import SandboxSession
try:
    SandboxSession(SandboxConfig.model_construct(max_memory_mb=0)).start()
except RuntimeError as exc:
    print(exc)
"""
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                            env=environment(None), text=True, capture_output=True, timeout=30)
    assert result.returncode == 0
    assert "Sandbox startup failed" in result.stdout and "exited before it was ready" in result.stdout
    assert "greater than 0" in result.stderr


def test_argument_errors_use_argparse_and_its_exit_code():
    result = subprocess.run([sys.executable, "-m", "agent_mbpp"], cwd=ROOT,
                            env=environment(None), text=True, capture_output=True, timeout=10)
    assert result.returncode == 2 and result.stdout == ""
    assert "the following arguments are required" in result.stderr
