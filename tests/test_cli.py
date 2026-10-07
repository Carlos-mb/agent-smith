"""Regression test for invalid MBPP input before agent execution."""

from agent_mbpp import main as mbpp_main
import pytest


@pytest.mark.parametrize("log_level", [None, "ERROR"])
def test_mbpp_cli_handles_invalid_task_file(tmp_path, capsys, monkeypatch, log_level):
    """Invalid JSON must report an error without writing a solution file."""
    if log_level is None:
        monkeypatch.delenv("AGENT_SMITH_LOG_LEVEL", raising=False)
    else:
        monkeypatch.setenv("AGENT_SMITH_LOG_LEVEL", log_level)
    task_path = tmp_path / "invalid_task.json"
    output_path = tmp_path / "mbpp_solution.json"

    task_path.write_text("not json", encoding="utf-8")

    exit_code = mbpp_main(
        [
            "--task-file",
            str(task_path),
            "--output",
            str(output_path),
            "--model-name",
            "test-model",
            "--provider-url",
            "https://example.invalid/v1",
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.out == ""
    if log_level is None:
        assert captured.err == ""
    else:
        assert "Error:" in captured.err and "Invalid JSON" in captured.err
    assert not output_path.exists()
