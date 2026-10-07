"""Known code only: the persistent worker process, its controls and its pipe."""

import time

import pytest

from agent_smith.models import SandboxConfig
from agent_smith.sandbox import FinalAnswerSignal, _build_namespace
from agent_smith.sandbox_session import SandboxSession
from agent_smith.mcp_client import MCPManual


def test_persistent_worker_and_complete_answer():
    def scenario():
        sandbox = SandboxSession(SandboxConfig(allowed_directories=[]))
        try:
            sandbox.start()
            process, directory = sandbox.process, sandbox.work_directory
            first = sandbox.execute("x = 6\ndef value():\n    return x\nprint('first')")
            assert first.output == "first\n"
            failed = sandbox.execute("x += 1\nprint('before')\nraise ValueError('bad')")
            assert failed.error == "ValueError: bad"
            assert failed.output == "before\n"
            assert not failed.worker_failed
            answer = sandbox.execute("final_answer(str(value()) * 130000)")
            assert answer.final_answer == "7" * 130000
            assert sandbox.process is process
        finally:
            sandbox.close()
        assert process.exitcode is not None
        assert not directory.exists()
        sandbox.close()
    scenario()


def test_timeout_preserves_output_and_closes_worker():
    def scenario():
        sandbox = SandboxSession(SandboxConfig(max_execution_time_seconds=1))
        try:
            sandbox.start()
            process = sandbox.process
            result = sandbox.execute("print('before', end='')\nwhile True: pass")
            assert result.timed_out and result.worker_failed
            assert result.output == "before"
            assert process.exitcode is not None
            assert sandbox.process is None
        finally:
            sandbox.close()
    scenario()


@pytest.mark.parametrize("statement, expected", [
    ("import os", "ImportError"),
    ("open('/etc/passwd')", "PermissionError"),
    ("import socket\nsocket.socket()", "PermissionError"),
    ("huge = 'x' * (1024 * 1024 * 1024)", "MemoryError"),
])
def test_worker_controls(statement, expected):
    def scenario():
        sandbox = SandboxSession(SandboxConfig(
            authorized_imports=["socket"], allowed_directories=[], max_memory_mb=128,
        ))
        try:
            sandbox.start()
            result = sandbox.execute(statement)
            assert expected in result.error
        finally:
            sandbox.close()
    scenario()


def test_truncation_does_not_truncate_final_answer():
    def scenario():
        sandbox = SandboxSession(SandboxConfig())
        try:
            sandbox.start()
            result = sandbox.execute("print('x' * 12010, end='')\nfinal_answer('z' * 130000)")
            assert result.output.count("[Output truncated:") == 1
            assert "10 characters omitted" in result.output
            assert result.final_answer == "z" * 130000
        finally:
            sandbox.close()
    scenario()


def test_exit_requests_do_not_stop_the_worker():
    sandbox = SandboxSession(SandboxConfig())
    try:
        sandbox.start()
        process = sandbox.process
        for statement in ("raise KeyboardInterrupt()", "raise SystemExit(7)"):
            result = sandbox.execute(statement)
            assert result.error and not result.worker_failed
        assert sandbox.process is process and process.exitcode is None
    finally:
        sandbox.close()


def test_mcp_wait_excluded_from_block_timeout():
    class Client:
        def call(self, operation, arguments, timeout):
            time.sleep(1.1)
            return {"result": {"answer": 42}}

    def scenario():
        tool = {"name": "slow", "inputSchema": {"properties": {}}}
        sandbox = SandboxSession(
            SandboxConfig(max_execution_time_seconds=1), Client(),
            MCPManual("", [tool], [], [], []),
        )
        try:
            sandbox.start()
            result = sandbox.execute("print(slow())", deadline=time.monotonic() + 5)
            assert result.error is None
            assert "42" in result.output
            result = sandbox.execute("slow()", deadline=time.monotonic() + 0.05)
            assert result.timed_out and result.worker_failed
        finally:
            sandbox.close()
    scenario()


def test_namespace_collision_and_positional_arguments():
    class FakeConnection:
        def __init__(self, replies):
            self.sent, self.replies = [], list(replies)

        def send(self, message):
            self.sent.append(message)

        def recv(self):
            if not self.replies:
                raise EOFError
            return self.replies.pop(0)

    tools = [
        {"name": name, "inputSchema": {"properties": {"code": {}, "tests": {}}}}
        for name in ("run_tests", "final_answer", "print", "class", "has-dash")
    ]
    connection = FakeConnection([{"type": "mcp_result", "result": {"success": True}}])
    namespace = _build_namespace(SandboxConfig(), tools, connection)
    assert "class" not in namespace and "has-dash" not in namespace
    assert "print" not in namespace
    with pytest.raises(FinalAnswerSignal):
        namespace["final_answer"]("local")
    assert namespace["run_tests"]("candidate", tests=[]) == {"success": True}
    assert connection.sent[0]["arguments"] == {
        "name": "run_tests", "arguments": {"code": "candidate", "tests": []}}
    with pytest.raises(TypeError):
        namespace["run_tests"]("one", code="two")
    with pytest.raises(EOFError):
        namespace["run_tests"]("no reply")


def test_missing_mcp_is_an_ordinary_error():
    def scenario():
        sandbox = SandboxSession(SandboxConfig())
        try:
            sandbox.start()
            result = sandbox.execute("mcp_call_tool('absent')")
            assert "No MCP server" in result.error
            assert not result.worker_failed
        finally:
            sandbox.close()
    scenario()
