"""Exercise blocks of known test code without starting a worker process."""

import sys

import pytest

from agent_smith.models import SandboxConfig
from agent_smith.sandbox import _make_safe_builtins, execute_block, final_answer


class FakeConnection:
    """Stand-in for one end of a multiprocessing Pipe: records what is sent."""

    def __init__(self):
        self.sent = []

    def send(self, message):
        self.sent.append(message)


@pytest.fixture
def namespace():
    config = SandboxConfig(authorized_imports=[], allowed_directories=[])
    return {
        "__builtins__": _make_safe_builtins(config),
        "__name__": "__sandbox__",
        "final_answer": final_answer,
    }


def test_blocks_share_variables_and_function_globals(namespace):
    stream = FakeConnection()

    execute_block("x = 1\ndef get_x():\n    return x", namespace, stream)
    execute_block("x += 1\nresult = get_x()", namespace, stream)

    assert namespace["x"] == 2
    assert namespace["result"] == 2
    messages = stream.sent
    assert messages == [
        {
            "type": "done", "final_answer": None, "error": None
        },
        {
            "type": "done", "final_answer": None, "error": None
        },
    ]


def test_stdout_and_stderr_keep_order_and_are_restored(namespace):
    stream = FakeConnection()
    original_streams = (sys.stdout, sys.stderr)
    # Expose sys only to this fixed test code to exercise stderr redirection.
    namespace["sys"] = sys

    execute_block(
        "print('first', end='')\n"
        "print('second', end='', file=sys.stderr)\n"
        "print('third', end='')",
        namespace,
        stream,
    )

    assert (sys.stdout, sys.stderr) == original_streams
    messages = stream.sent
    assert messages[:-1] == [
        {"type": "output", "text": "first"},
        {"type": "output", "text": "second"},
        {"type": "output", "text": "third"},
    ]
    assert messages[-1]["type"] == "done"
    assert messages[-1]["error"] is None


def test_error_keeps_output_and_variables_for_next_block(namespace):
    stream = FakeConnection()
    original_streams = (sys.stdout, sys.stderr)

    execute_block(
        "x = 7\nprint('before', end='')\nraise ValueError('bad value')",
        namespace,
        stream,
    )

    assert (sys.stdout, sys.stderr) == original_streams
    assert namespace["x"] == 7
    messages = stream.sent
    assert messages == [
        {"type": "output", "text": "before"},
        {
            "type": "done", "final_answer": None,
            "error": "ValueError: bad value",
        },
    ]

    next_stream = FakeConnection()
    execute_block("x += 1", namespace, next_stream)
    assert namespace["x"] == 8
    assert next_stream.sent[-1]["error"] is None


def test_syntax_error_is_reported(namespace):
    stream = FakeConnection()
    original_streams = (sys.stdout, sys.stderr)

    execute_block("if :", namespace, stream)

    assert (sys.stdout, sys.stderr) == original_streams
    message = stream.sent[-1]
    assert message["type"] == "done"
    assert message["error"].startswith("SyntaxError:")
    assert message["final_answer"] is None


@pytest.mark.parametrize("answer", ["complete answer", ""])
def test_final_answer_stops_the_block(namespace, answer):
    stream = FakeConnection()
    namespace["answer"] = answer
    original_streams = (sys.stdout, sys.stderr)

    execute_block("final_answer(answer)\nfinished = True", namespace, stream)

    assert (sys.stdout, sys.stderr) == original_streams
    assert "finished" not in namespace
    assert stream.sent[-1] == {
        "type": "done", "final_answer": answer, "error": None,
    }


def test_exit_requests_from_generated_code_are_ordinary_errors(namespace):
    for statement in ("raise KeyboardInterrupt()", "raise SystemExit(3)"):
        stream = FakeConnection()
        execute_block(f"print('before', end='')\n{statement}\nfinished = True", namespace, stream)
        assert "finished" not in namespace
        assert stream.sent[0] == {"type": "output", "text": "before"}
        assert stream.sent[-1]["type"] == "done"
        assert stream.sent[-1]["error"].split(":")[0] in ("KeyboardInterrupt", "SystemExit")


def _printed(code, namespace):
    """Return only what the block wrote as output messages."""
    stream = FakeConnection()
    execute_block(code, namespace, stream)
    return "".join(
        message["text"] for message in stream.sent
        if message["type"] == "output"
    )


def test_a_trailing_expression_is_echoed_like_in_the_repl(namespace):
    # Los modelos llaman a las herramientas sin print; sin este eco la
    # observacion llegaba vacia y repetian la misma llamada en bucle.
    assert _printed("1 + 1", namespace) == "2\n"


def test_a_trailing_expression_runs_after_the_rest_of_the_block(namespace):
    assert _printed("a = 3\nb = 4\na * b", namespace) == "12\n"


def test_an_assignment_alone_echoes_nothing(namespace):
    assert _printed("value = 10", namespace) == ""
    assert namespace["value"] == 10


def test_a_trailing_none_echoes_nothing(namespace):
    assert _printed("def nothing():\n    pass\nnothing()", namespace) == ""


def test_an_explicit_print_is_not_duplicated(namespace):
    assert _printed("print('once')", namespace) == "once\n"


def test_a_multiline_string_result_is_echoed_readably(namespace):
    # Las herramientas devuelven texto con saltos; el modelo debe leerlo tal cual.
    assert _printed("'primera\\nsegunda'", namespace) == "primera\nsegunda\n"
