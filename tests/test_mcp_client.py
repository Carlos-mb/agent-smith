"""Tests for MCP client configuration and streamable HTTP discovery."""

from contextlib import suppress
from pathlib import Path
import socket
import subprocess
import sys
import time

from agent_smith.mcp_client import MCPClient
from agent_smith.models import SandboxConfig
from agent_smith.sandbox_session import SandboxSession


def test_mcp_client_discovers_and_uses_streamable_http_server() -> None:
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]

    root = Path(__file__).resolve().parents[1]
    server = subprocess.Popen(
        [sys.executable, "tests/_http_mcp_server.py", str(port)],
        cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    url = f"http://127.0.0.1:{port}/mcp"

    try:
        deadline = time.monotonic() + 10
        client = None
        while client is None:
            candidate = MCPClient(server_url=url)
            try:
                manual = candidate.start(deadline=deadline)
            except Exception:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)
            else:
                client = candidate
        try:
            assert [tool["name"] for tool in manual.tools] == ["identify"]
            assert [resource["uri"] for resource in manual.resources] == ["test://status"]
            assert [template["uriTemplate"] for template in manual.resource_templates] == [
                "test://items/{name}",
            ]
            assert [prompt["name"] for prompt in manual.prompts] == ["discuss"]
            assert "HTTP integration instructions." in manual.as_text()

            assert client.call("call_tool", {"name": "identify", "arguments": {"value": "MCP"}}) == {
                "result": "identified: MCP"}
            assert client.call("read_resource", {"uri": "test://status"}) == {"result": "ready"}
            assert client.call("read_resource", {"uri": "test://items/example"}) == {
                "result": "item: example"}
            prompt = client.call("get_prompt", {"name": "discuss", "arguments": {"topic": "HTTP"}})
            assert prompt["result"]["messages"][0]["content"]["text"] == "Discuss HTTP"

            def in_worker():
                sandbox = SandboxSession(
                    SandboxConfig(allowed_directories=[]), client, manual,
                )
                try:
                    sandbox.start()
                    return sandbox.execute(
                        "print(identify('worker'))\n"
                        "print(read_resource('test://status'))\n"
                        "print(get_prompt('discuss', {'topic': 'worker'}))"
                    )
                finally:
                    sandbox.close()

            execution = in_worker()
            assert execution.error is None
            assert "identified: worker" in execution.output
            assert "ready" in execution.output
            assert "Discuss worker" in execution.output
        finally:
            client.close()
    finally:
        with suppress(ProcessLookupError):
            server.terminate()
        try:
            stdout, stderr = server.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            stdout, stderr = server.communicate(timeout=5)
        assert server.returncode is not None, stderr
        assert stdout == ""
