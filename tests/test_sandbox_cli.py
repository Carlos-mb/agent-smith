"""Tests for sandbox CLI parsing and the persistent interactive loop."""

from pathlib import Path
import subprocess
import sys

import pytest

import agent_smith.sandbox_cli as sandbox_cli
from agent_smith.mcp_client import MCPManual
from agent_smith.models import SandboxConfig
from agent_smith.sandbox_session import SandboxSession
from agent_smith.sandbox_cli import _build_mcp_client, parse_arguments, run_repl

def test_parse_arguments_with_no_options():
    args = parse_arguments([])

    assert args.config is None
    assert args.mcp_stdio is None
    assert args.mcp_server is None


def test_parse_arguments_with_config_file():
    args = parse_arguments(["configs/sandbox_template.json"])

    assert args.config == Path("configs/sandbox_template.json")
    assert isinstance(args.config, Path)


def test_parse_arguments_with_mcp_stdio():
    args = parse_arguments(
        ["--mcp-stdio", "python mcp_tools_mbpp.py"]
    )

    assert args.mcp_stdio == "python mcp_tools_mbpp.py"
    assert args.mcp_server is None


def test_parse_arguments_with_mcp_server():
    args = parse_arguments(
        ["--mcp-server", "http://127.0.0.1:8000/mcp"]
    )

    assert args.mcp_server == "http://127.0.0.1:8000/mcp"
    assert args.mcp_stdio is None


def test_parse_arguments_rejects_both_mcp_transports():
    with pytest.raises(SystemExit) as error:
        parse_arguments(
            [
                "--mcp-stdio",
                "python mcp_tools_mbpp.py",
                "--mcp-server",
                "http://127.0.0.1:8000/mcp",
            ]
        )

    assert error.value.code == 2

def test_build_mcp_client_returns_none_without_transport():
    args = parse_arguments([])

    client = _build_mcp_client(args)

    assert client is None


def test_build_mcp_client_with_stdio():
    args = parse_arguments(
        ["--mcp-stdio", "python mcp_tools_mbpp.py"]
    )

    client = _build_mcp_client(args)

    assert client is not None
    assert client.stdio_command == [
        "python",
        "mcp_tools_mbpp.py",
    ]
    assert client.server_url is None


def test_build_mcp_client_with_http():
    args = parse_arguments(
        ["--mcp-server", "http://127.0.0.1:8000/mcp"]
    )

    client = _build_mcp_client(args)

    assert client is not None
    assert client.server_url == "http://127.0.0.1:8000/mcp"
    assert client.stdio_command is None


def test_build_mcp_client_uses_shlex_for_stdio_command():
    args = parse_arguments(
        [
            "--mcp-stdio",
            'python server.py --message "hello world"',
        ]
    )

    client = _build_mcp_client(args)

    assert client is not None
    assert client.stdio_command == [
        "python",
        "server.py",
        "--message",
        "hello world",
    ]


def test_repl_executes_complete_blocks_and_keeps_its_namespace(monkeypatch, capsys):
    entries = iter([
        "value = 40",
        "def add(left, right):",
        "    return left + right",
        "",
        "print(add(value, 2))",
        "final_answer('done')",
        "print(value)",
        "exit",
    ])
    monkeypatch.setattr("builtins.input", lambda prompt: next(entries))

    def scenario():
        session = SandboxSession(SandboxConfig(allowed_directories=[]))
        try:
            session.start()
            assert run_repl(session) == 0
        finally:
            session.close()

    scenario()
    output = capsys.readouterr().out
    assert "42\n" in output
    assert "Final answer: done\n" in output
    assert output.endswith("40\n")


def test_repl_reports_syntax_errors_and_returns_to_the_prompt(monkeypatch, capsys):
    entries = iter(["if :", "print('still running')", "exit"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(entries))

    def scenario():
        session = SandboxSession(SandboxConfig(allowed_directories=[]))
        try:
            session.start()
            assert run_repl(session) == 0
        finally:
            session.close()

    scenario()
    output = capsys.readouterr().out
    assert "SyntaxError:" in output
    assert output.endswith("still running\n")


def test_repl_exits_on_eof_without_executing_code(monkeypatch):
    def end_of_input(prompt):
        raise EOFError

    monkeypatch.setattr("builtins.input", end_of_input)

    assert run_repl(None) == 0


def test_repl_runs_the_last_block_when_input_ends_without_a_blank_line(monkeypatch, capsys):
    # Un guion enviado con `cat fichero | sandbox` puede acabar sin linea en
    # blanco: el ultimo bloque llegaba asi y antes se quedaba sin ejecutar.
    entries = iter(["if True:", "    print('ultimo bloque')"])

    def next_entry(prompt):
        try:
            return next(entries)
        except StopIteration:
            raise EOFError

    monkeypatch.setattr("builtins.input", next_entry)

    def scenario():
        session = SandboxSession(SandboxConfig(allowed_directories=[]))
        try:
            session.start()
            assert run_repl(session) == 0
        finally:
            session.close()

    scenario()
    assert "ultimo bloque\n" in capsys.readouterr().out


def test_repl_keeps_a_block_open_until_its_else_branch(monkeypatch, capsys):
    # Con symbol="exec" el bloque se cerraba tras el `if` y el `else` llegaba suelto.
    entries = iter([
        "for item in [1]:", "    if item:", "        print('rama if')",
        "    else:", "        print('rama else')", "", "exit",
    ])
    monkeypatch.setattr("builtins.input", lambda prompt: next(entries))

    def scenario():
        session = SandboxSession(SandboxConfig(allowed_directories=[]))
        try:
            session.start()
            assert run_repl(session) == 0
        finally:
            session.close()

    scenario()
    output = capsys.readouterr().out
    assert "rama if\n" in output
    assert "IndentationError" not in output


def test_repl_restarts_only_after_a_lost_worker(monkeypatch, capsys):
    entries = iter(["while True: pass", "", "value = 3", "print(value)", "exit"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(entries))

    def scenario():
        session = SandboxSession(SandboxConfig(
            allowed_directories=[], max_execution_time_seconds=1,
        ))
        try:
            session.start()
            assert run_repl(session) == 0
        finally:
            session.close()

    scenario()
    output = capsys.readouterr().out
    assert "Execution timed out; worker state was lost." in output
    assert "Worker restarted; variables were lost." in output
    assert output.endswith("3\n")


def _script(text):
    session = SandboxSession(SandboxConfig(allowed_directories=[]))
    try:
        session.start()
        assert sandbox_cli.run_script(session, text) == 0
    finally:
        session.close()


def test_script_keeps_blank_lines_inside_a_block(capsys):
    # Un fichero por tuberia se ejecuta por sentencias: una linea en blanco
    # dentro del bloque no lo cierra, al contrario que en el REPL interactivo.
    _script(
        "if True:\n"
        "    print('antes')\n"
        "\n"
        "    print('despues')\n"
        "else:\n"
        "    print('nunca')\n"
    )

    output = capsys.readouterr().out
    assert "antes\n" in output and "despues\n" in output
    assert "nunca" not in output
    assert "IndentationError" not in output


def test_script_continues_after_a_final_answer(capsys):
    _script(
        "valor = 7\n"
        "try:\n"
        "    final_answer('entregado')\n"
        "except Exception as error:\n"
        "    print('capturado:', error)\n"
        "print('sigo vivo', valor)\n"
    )

    output = capsys.readouterr().out
    assert "capturado: entregado\n" in output
    assert "sigo vivo 7\n" in output


def test_script_reports_a_syntax_error_without_executing_anything(capsys):
    def scenario():
        session = SandboxSession(SandboxConfig(allowed_directories=[]))
        try:
            session.start()
            assert sandbox_cli.run_script(session, "print('hola')\nif :\n") == 1
        finally:
            session.close()

    scenario()
    output = capsys.readouterr().out
    assert "SyntaxError:" in output
    assert "hola" not in output


def test_sandbox_entrypoint_opens_repl_and_closes_after_exit():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from agent_smith.sandbox_cli import main; raise SystemExit(main())",
        ],
        cwd=root,
        input="value = 4\nprint(value)\nexit\n",
        text=True,
        capture_output=True,
        timeout=15,
    )

    assert result.returncode == 0
    assert "4\n" in result.stdout
    assert result.stderr == ""


def test_sandbox_owner_closes_resources_after_keyboard_interrupt(monkeypatch):
    events = []

    class Client:
        def start(self):
            events.append("mcp start")
            return MCPManual("", [], [], [], [])

        def close(self):
            events.append("mcp close")

    class Session:
        def __init__(self, config, mcp, manual):
            events.append("sandbox create")

        def start(self):
            events.append("sandbox start")

        def close(self):
            events.append("sandbox close")

    def interrupt(session):
        events.append("repl")
        raise KeyboardInterrupt

    monkeypatch.setattr(sandbox_cli, "load_sandbox_config", lambda path: SandboxConfig())
    monkeypatch.setattr(sandbox_cli, "_build_mcp_client", lambda args: Client())
    monkeypatch.setattr(sandbox_cli, "SandboxSession", Session)
    monkeypatch.setattr(sandbox_cli, "run_repl", interrupt)
    monkeypatch.setattr(sandbox_cli, "run_script", interrupt)

    with pytest.raises(KeyboardInterrupt):
        sandbox_cli._run_sandbox(parse_arguments([
            "--mcp-server", "http://127.0.0.1:8000/mcp",
        ]))

    assert events == [
        "mcp start", "sandbox create", "sandbox start", "repl",
        "sandbox close", "mcp close",
    ]
