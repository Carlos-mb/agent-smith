"""Observation tests and two contract checks for the pending final_answer function."""

import pytest

from agent_smith.agent_loop import build_observation
from agent_smith.sandbox import (
    FinalAnswerSignal,
    SandboxExecution,
    final_answer,
)


def test_final_answer_raises_signal_with_answer():
    with pytest.raises(FinalAnswerSignal) as error:
        final_answer("resultado")

    assert str(error.value) == "resultado"


def test_final_answer_rejects_non_string():
    with pytest.raises(TypeError):
        final_answer(123)


def test_observation_without_execution_returns_extraction_feedback():
    observation = build_observation(
        execution=None,
        extraction_feedback="No valid code block was found.",
    )

    assert observation == "No valid code block was found."


def test_observation_contains_normal_output():
    execution = SandboxExecution(
        output="resultado: 5",
        final_answer=None,
        error=None,
        timed_out=False,
    )

    observation = build_observation(
        execution=execution,
        extraction_feedback="Code extracted successfully.",
    )

    assert "Code extracted successfully." in observation
    assert "resultado: 5" in observation


def test_observation_contains_execution_error():
    execution = SandboxExecution(
        output="",
        final_answer=None,
        error="NameError: name 'x' is not defined",
        timed_out=False,
    )

    observation = build_observation(
        execution=execution,
        extraction_feedback="Code extracted successfully.",
    )

    assert "NameError: name 'x' is not defined" in observation


def test_observation_reports_timeout_and_keeps_partial_output():
    execution = SandboxExecution(
        output="partial output",
        final_answer=None,
        error=None,
        timed_out=True,
    )

    observation = build_observation(
        execution=execution,
        extraction_feedback="Code extracted successfully.",
    )

    assert "partial output" in observation
    assert "timeout" in observation.lower()


def test_observation_keeps_existing_truncation_warning():
    execution = SandboxExecution(
        output=(
            "some output\n"
            "[output truncated: 42 characters omitted]"
        ),
        final_answer=None,
        error=None,
        timed_out=False,
    )

    observation = build_observation(
        execution=execution,
        extraction_feedback="Code extracted successfully.",
    )

    assert "some output" in observation
    assert "[output truncated: 42 characters omitted]" in observation

def test_timeout_does_not_claim_variables_were_lost():
    execution = SandboxExecution(
        output="partial output",
        final_answer=None,
        error=None,
        timed_out=True,
    )

    observation = build_observation(
        execution=execution,
        extraction_feedback="",
    )

    assert "partial output" in observation
    assert "timeout" in observation.lower()
    assert "variables were lost" not in observation.lower()


def test_truncation_warning_is_not_duplicated():
    execution = SandboxExecution(
        output="[output truncated: 42 characters omitted]",
        final_answer=None,
        error=None,
        timed_out=False,
    )

    observation = build_observation(
        execution=execution,
        extraction_feedback="",
    )

    assert observation.count("truncated") == 1
