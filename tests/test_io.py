"""Tests for JSON input and output helpers."""

import json

import pytest
from pydantic import ValidationError

from agent_smith.io import load_model, write_model
from agent_smith.models import MBPPTaskInput


def test_load_model_validates_the_file(tmp_path):
    path = tmp_path / "task.json"
    path.write_text(json.dumps({"task_id": 1, "task_definition": "d",
                                "function_definition": "def f():"}), encoding="utf-8")
    assert load_model(path, MBPPTaskInput).task_id == 1


def test_missing_file_is_an_os_error(tmp_path):
    with pytest.raises(OSError):
        load_model(tmp_path / "missing.json", MBPPTaskInput)


@pytest.mark.parametrize("content", ["not json", '{"task_id": "x"}'])
def test_bad_json_or_fields_are_a_value_error(tmp_path, content):
    path = tmp_path / "task.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError):
        load_model(path, MBPPTaskInput)


def test_write_model_creates_the_folder(tmp_path):
    path = tmp_path / "out" / "task.json"
    task = MBPPTaskInput(task_id=1, task_definition="d", function_definition="def f():")
    write_model(path, task)
    assert load_model(path, MBPPTaskInput) == task
