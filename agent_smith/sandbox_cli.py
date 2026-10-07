"""Interactive command-line interface required by ``uv run sandbox``."""

from __future__ import annotations

from agent_smith.logging_config import configure_logging, get_logger

import argparse
import ast
import codeop
import os
import shlex
import sys
from pathlib import Path
from typing import Sequence

from agent_smith.mcp_client import MCPClient
from agent_smith.sandbox import load_sandbox_config
from agent_smith.sandbox_session import SandboxSession

logger = get_logger('agent_smith.sandbox_cli')


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse sandbox command-line arguments."""
    logger.debug("Entrando en parse_arguments")

    parser = argparse.ArgumentParser(
        description="Run the interactive sandbox."
    )

    parser.add_argument(
        "config",
        nargs="?",
        type=Path,
        help="Path to the sandbox configuration JSON file.",
    )

    mcp_group = parser.add_mutually_exclusive_group()

    mcp_group.add_argument(
        "--mcp-stdio",
        help="Command used to start an MCP server with stdio.",
    )

    mcp_group.add_argument(
        "--mcp-server",
        help="URL of an MCP server.",
    )

    return parser.parse_args(argv)


# The MCP server starts with a minimal environment, so it must be given
# explicitly what it needs to find the testbed and talk to Docker.
SERVER_ENVIRONMENT_NAMES = (
    "PATH", "HOME", "TESTBED_PATH", "AGENT_SMITH_CONTAINER_ID",
    "AGENT_SMITH_EVAL_SCRIPT", "AGENT_SMITH_DEADLINE",
    "AGENT_SMITH_MBPP_SESSION",
    "DOCKER_HOST", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH",
)


def _build_mcp_client(args: argparse.Namespace) -> MCPClient | None:
    """Build an MCP client from CLI arguments without connecting."""
    logger.debug("Entrando en _build_mcp_client")

    if args.mcp_stdio is not None:
        command = shlex.split(args.mcp_stdio)
        environment = {
            name: os.environ[name]
            for name in SERVER_ENVIRONMENT_NAMES if name in os.environ
        }
        return MCPClient(stdio_command=command, environment=environment)

    if args.mcp_server is not None:
        return MCPClient(server_url=args.mcp_server)

    return None


def _run_entry(session: SandboxSession, code: str) -> None:
    """Execute one complete entry and print what the sandbox reports."""
    logger.debug("Entrando en _run_entry")
    execution = session.execute(code)
    if execution.output:
        print(execution.output, end="")
    if execution.error:
        print("Error: " + execution.error)
    if execution.final_answer is not None:
        print("Final answer: " + execution.final_answer)
    if execution.worker_failed:
        print("Worker restarted; variables were lost.")
        session.close()
        session.start()


def run_script(session: SandboxSession, text: str | None = None) -> int:
    """Execute a piped script one top-level statement at a time.

    Line-by-line reading cannot handle a pasted file: a blank line inside a
    block would close it early, and a final_answer would abort everything that
    follows it. Splitting on top-level statements keeps both working.
    """
    logger.debug("Entrando en run_script")
    if text is None:
        text = sys.stdin.read()
    try:
        parsed = ast.parse(text)
    except SyntaxError as exc:
        print(f"SyntaxError: {exc}")
        return 1
    lines = text.splitlines()
    for node in parsed.body:
        first = min([node.lineno]
                    + [d.lineno for d in getattr(node, "decorator_list", [])])
        statement = "\n".join(lines[first - 1:node.end_lineno])
        if statement.strip() == "exit":
            return 0
        _run_entry(session, statement)
    return 0


def run_repl(session: SandboxSession) -> int:
    """Read and execute persistent Python entries until exit or EOF."""
    logger.debug("Entrando en run_repl")
    lines: list[str] = []
    while True:
        try:
            line = input("... " if lines else ">>> ")
        except EOFError:
            print()
            # With redirected input the last block arrives without a blank
            # line.
            if lines:
                _run_entry(session, "\n".join(lines))
            return 0

        if not lines and line == "exit":
            return 0
        if not lines and not line:
            continue

        lines.append(line)
        code = "\n".join(lines)
        try:
            # "single" waits for a blank line to close a block, like the
            # Python REPL. With "exec" the block closed before else/except.
            compiled = codeop.compile_command(code, symbol="single")
        except (OverflowError, SyntaxError, ValueError) as exc:
            print(f"{type(exc).__name__}: {exc}")
            lines.clear()
            continue
        if compiled is None:
            continue

        lines.clear()
        _run_entry(session, code)


def _run_sandbox(args: argparse.Namespace) -> int:
    """Own the MCP client and the worker, and close both at the end."""
    logger.debug("Entrando en _run_sandbox")
    config = load_sandbox_config(args.config)
    client = _build_mcp_client(args)
    session = None
    manual = None
    try:
        if client is not None:
            manual = client.start()
        session = SandboxSession(config, mcp=client, manual=manual)
        session.start()
        if manual is not None:
            print(manual.as_text())
        if sys.stdin.isatty():
            return run_repl(session)
        return run_script(session)
    finally:
        cleanup_errors = []
        if session is not None:
            try:
                session.close()
            except Exception as exc:
                cleanup_errors.append(f"sandbox: {exc}")
        if client is not None:
            try:
                client.close()
            except Exception as exc:
                cleanup_errors.append(f"MCP: {exc}")
        if cleanup_errors:
            logger.error("Cleanup failed: %s", "; ".join(cleanup_errors))
            if sys.exc_info()[0] is None:
                raise RuntimeError("Sandbox cleanup failed: "
                                   + "; ".join(cleanup_errors))


def main(argv: Sequence[str] | None = None) -> int:
    """Parse CLI arguments and run the sandbox with graceful errors."""
    configure_logging()
    logger.debug("Entrando en main")
    args = parse_arguments(argv)
    try:
        return _run_sandbox(args)
    except Exception as exc:
        logger.error("Error: %s", exc)
        return 1
