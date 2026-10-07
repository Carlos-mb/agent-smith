"""Integration tests for the MBPP MCP server using the async SDK directly."""

import asyncio
import os
import sys
from datetime import timedelta
from pathlib import Path

import anyio
import pytest
from anyio.abc import Process
from exceptiongroup import ExceptionGroup
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import Tool


MCP_TIMEOUT = timedelta(seconds=30)


def docker_environment() -> dict[str, str]:
    """Return only the extra environment variables Docker may need."""
    names = (
        "DOCKER_HOST",
        "DOCKER_TLS_VERIFY",
        "DOCKER_CERT_PATH",
    )
    return {
        name: os.environ[name]
        for name in names
        if name in os.environ
    }


def server_parameters() -> StdioServerParameters:
    """Run our MBPP server with the same Python interpreter as pytest."""
    project_root = Path(__file__).resolve().parents[1]
    return StdioServerParameters(
        command=sys.executable,
        args=[str(project_root / "mcp_tools_mbpp.py")],
        env=docker_environment(),
        cwd=str(project_root),
    )


@pytest.fixture
def server_processes(monkeypatch: pytest.MonkeyPatch) -> list[Process]:
    """Record real processes started by the SDK; do not fake the server."""
    processes = []
    original_open_process = anyio.open_process

    async def record_process(*args, **kwargs) -> Process:
        process = await original_open_process(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(anyio, "open_process", record_process)
    return processes


def assert_server_stopped(processes: list[Process]) -> None:
    """Check that exactly one server was started and has terminated."""
    assert len(processes) == 1, "Expected exactly one MCP server process."
    process = processes[0]
    assert process.returncode is not None, (
        f"MCP server PID {process.pid} is still running."
    )


async def list_mbpp_tools(processes: list[Process]) -> list[Tool]:
    """Discover tools and check shutdown before leaving the coroutine."""
    async with stdio_client(server_parameters()) as (read_stream, write_stream):
        async with ClientSession(
            read_stream,
            write_stream,
            read_timeout_seconds=MCP_TIMEOUT,
        ) as session:
            await session.initialize()
            response = await session.list_tools()

    assert_server_stopped(processes)
    return list(response.tools)


async def call_run_tests(session: ClientSession, code: str) -> dict:
    """Call run_tests using a session that is already open."""
    response = await session.call_tool(
        "run_tests",
        arguments={
            "code": code,
            "test_imports": [],
            "test_list": ["assert add(2, 3) == 5"],
            "timeout_seconds": 10,
        },
    )

    assert response.isError is False, response
    assert response.content, response
    data = response.structuredContent
    assert isinstance(data, dict), response
    return data


async def run_two_calls(
    processes: list[Process],
    controlled_error: ValueError | None = None,
) -> None:
    """Use one session twice, then leave normally or raise a known error."""
    try:
        async with stdio_client(server_parameters()) as (read_stream, write_stream):
            async with ClientSession(
                read_stream,
                write_stream,
                read_timeout_seconds=MCP_TIMEOUT,
            ) as session:
                await session.initialize()

                failed = await call_run_tests(
                    session,
                    "def add(a, b):\n    return 0\n",
                )
                assert failed["success"] is False, failed
                assert failed["message"] == "Public tests failed.", failed
                assert isinstance(failed["exit_code"], int), failed
                assert failed["exit_code"] != 0, failed
                assert "AssertionError" in failed["output"], failed

                passed = await call_run_tests(
                    session,
                    "def add(a, b):\n    return a + b\n",
                )
                assert passed["success"] is True, passed
                assert passed["message"] == "All public tests passed.", passed
                assert passed["exit_code"] == 0, passed

                # Both calls are finished, but the session is still open.
                if controlled_error is not None:
                    raise controlled_error
    finally:
        # Check after both contexts exit, before asyncio.run does any cleanup.
        assert_server_stopped(processes)


def test_mcp_server_exposes_run_tests(server_processes: list[Process]) -> None:
    """The real server must advertise run_tests and its input parameters."""
    tools = asyncio.run(list_mbpp_tools(server_processes))
    run_tests_tool = next(
        (tool for tool in tools if tool.name == "run_tests"),
        None,
    )
    assert run_tests_tool is not None

    properties = run_tests_tool.inputSchema["properties"]
    assert "code" in properties
    assert "test_imports" in properties
    assert "test_list" in properties
    assert "timeout_seconds" in properties


def test_mcp_two_calls_and_normal_close(server_processes: list[Process]) -> None:
    """A failed candidate must not prevent a second call in the same session."""
    asyncio.run(run_two_calls(server_processes))


def test_mcp_two_calls_and_error_close(server_processes: list[Process]) -> None:
    """A client error must propagate after the server has terminated."""
    expected_error = ValueError("Controlled error after two MCP calls.")

    with pytest.raises((ValueError, ExceptionGroup)) as caught:
        asyncio.run(run_two_calls(server_processes, expected_error))

    # AnyIO can wrap the original error in nested exception groups.
    error = caught.value
    while isinstance(error, ExceptionGroup):
        assert len(error.exceptions) == 1, caught.value
        error = error.exceptions[0]

    # Do not accept a different error or a group containing extra failures.
    assert error is expected_error
