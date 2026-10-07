"""Tests for the local final-answer signal."""

import pytest

from agent_smith.sandbox import FinalAnswerSignal, final_answer


@pytest.mark.parametrize(
    "answer",
    ["The answer\nwith another line", "", "x" * 20_000],
    ids=["text", "empty", "long"],
)
def test_final_answer_raises_signal_with_complete_text(answer, capsys):
    with pytest.raises(FinalAnswerSignal) as caught:
        final_answer(answer)

    assert caught.value.args == (answer,)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


@pytest.mark.parametrize("answer", [None, 42, {"answer": "hello"}])
def test_final_answer_rejects_non_strings(answer):
    with pytest.raises(TypeError):
        final_answer(answer)
