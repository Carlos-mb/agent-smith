"""Tests for the SWE-bench tools against a temporary host testbed."""

import subprocess

import pytest

from agent_smith import swebench_tools


UTILS = '''"""Helpers."""


def calculate_sum(numbers):
    return sum(numbers)


def average(numbers):
    return calculate_sum(numbers) / len(numbers)
'''

MODELS = '''class User:
    def __init__(self, name):
        self.name = name
'''


@pytest.fixture
def testbed(tmp_path, monkeypatch):
    """Build a small git checkout and point the tools at it."""
    root = tmp_path / "testbed"
    (root / "package").mkdir(parents=True)
    (root / "utils.py").write_text(UTILS)
    (root / "models.py").write_text(MODELS)
    (root / "notes.txt").write_text("not python\n")
    (root / "package" / "deep.py").write_text("from utils import calculate_sum\n")
    for command in (
        ["git", "init", "-q"],
        ["git", "add", "-A"],
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"],
    ):
        subprocess.run(command, cwd=root, check=True, capture_output=True)
    monkeypatch.delenv("AGENT_SMITH_CONTAINER_ID", raising=False)
    monkeypatch.setenv("TESTBED_PATH", str(root))
    return root


def test_read_file_numbers_the_requested_range(testbed):
    result = swebench_tools.read_file("/testbed/utils.py", 4, 5)

    assert result.splitlines() == ["4: def calculate_sum(numbers):", "5:     return sum(numbers)"]


def test_read_file_stops_at_the_end_of_the_file(testbed):
    result = swebench_tools.read_file("/testbed/models.py", 1, 500)

    assert result.startswith("1: class User:")
    assert len(result.splitlines()) == len(MODELS.splitlines())


def test_list_files_walks_subdirectories_and_shows_testbed_paths(testbed):
    result = swebench_tools.list_files("/testbed", "*.py")

    assert set(result.split()) == {
        "/testbed/models.py", "/testbed/utils.py", "/testbed/package/deep.py",
    }
    assert "notes.txt" not in result


def test_search_code_reports_path_and_line_number(testbed):
    result = swebench_tools.search_code("calculate_sum")

    assert "/testbed/utils.py:4:" in result
    assert "/testbed/package/deep.py:1:" in result


def test_search_definition_finds_functions_and_classes(testbed):
    function = swebench_tools.search_function_or_class_definition_in_code("calculate_sum")
    klass = swebench_tools.search_function_or_class_definition_in_code("User")

    assert "/testbed/utils.py" in function and "def calculate_sum" in function
    # La llamada desde average no es una definicion y no debe aparecer.
    assert "return calculate_sum" not in function
    assert "/testbed/models.py" in klass and "class User" in klass


def test_find_references_is_textual_and_includes_the_definition(testbed):
    result = swebench_tools.find_references("calculate_sum", "/testbed/utils.py", 4)

    assert "/testbed/utils.py:4:" in result
    assert "/testbed/utils.py:9:" in result
    assert "/testbed/package/deep.py:1:" in result


def test_edit_file_applies_a_unique_match(testbed):
    result = swebench_tools.edit_file("/testbed/utils.py", "return sum(numbers)", "return 0")

    assert "Edit applied successfully." in result
    assert "return 0" in (testbed / "utils.py").read_text()


def test_edit_file_refuses_an_ambiguous_match(testbed):
    result = swebench_tools.edit_file("/testbed/utils.py", "numbers", "values")

    assert "expected exactly one match" in result
    assert (testbed / "utils.py").read_text() == UTILS


def test_edit_file_refuses_a_result_that_would_not_compile(testbed):
    result = swebench_tools.edit_file("/testbed/utils.py", "def calculate_sum", "def calculate sum")

    assert "would not compile" in result
    assert (testbed / "utils.py").read_text() == UTILS


def test_edit_file_refuses_an_edit_that_changes_nothing(testbed):
    # This used to answer "Edit applied successfully." to an edit that changed
    # nothing. In scikit-learn-13439 the model sent the same no-op edit 13
    # times, believed each confirmation and spent the whole task on it.
    result = swebench_tools.edit_file(
        "/testbed/utils.py", "return sum(numbers)", "return sum(numbers)")

    assert "identical" in result
    assert "Edit applied successfully." not in result
    assert (testbed / "utils.py").read_text() == UTILS


def test_get_patch_reports_no_changes_then_shows_the_diff(testbed):
    assert swebench_tools.get_patch() == "No changes yet."

    swebench_tools.edit_file("/testbed/utils.py", "return sum(numbers)", "return 0")
    patch = swebench_tools.get_patch()

    assert patch.startswith("diff --git")
    assert "-    return sum(numbers)" in patch
    assert "+    return 0" in patch


def test_run_command_returns_exit_code_and_output(testbed):
    result = swebench_tools.run_command("echo marker_value", "/testbed")

    assert "exit_code: 0" in result
    assert "marker_value" in result


def test_run_command_keeps_a_failure_visible(testbed):
    result = swebench_tools.run_command("exit 3", "/testbed")

    assert "exit_code: 3" in result


def test_run_tests_uses_the_supplied_eval_script(testbed, monkeypatch):
    monkeypatch.setenv("AGENT_SMITH_EVAL_SCRIPT", "echo running_eval_script")

    result = swebench_tools.run_tests()

    assert "running_eval_script" in result
    assert "exit_code: 0" in result


EVAL_SCRIPT = """#!/bin/bash
set -uxo pipefail
for i in $(seq 400); do echo "old mode 100644 noise"; done
: '>>>>> Start Test Output'
echo 'Ran 59 tests in 0.111s' >&2
echo 'OK' >&2
: '>>>>> End Test Output'
for i in $(seq 400); do echo "DeprecationWarning noise" >&2; done
"""


def test_run_tests_returns_only_the_test_output_section(testbed, monkeypatch):
    # Como el eval_script real: ruido antes y despues, y el resumen de unittest
    # (Django) en stderr. Antes el recorte dejaba el ruido y perdia el resumen.
    monkeypatch.setenv("AGENT_SMITH_EVAL_SCRIPT", EVAL_SCRIPT)

    result = swebench_tools.run_tests()

    assert "Ran 59 tests in 0.111s" in result
    assert "OK" in result
    assert "noise" not in result


def test_paths_outside_the_testbed_are_refused(testbed):
    with pytest.raises(ValueError):
        swebench_tools.read_file("/etc/passwd", 1, 5)

    with pytest.raises(ValueError):
        swebench_tools.read_file("/testbed/../../etc/passwd", 1, 5)


def test_an_ambiguous_edit_says_where_the_matches_are(testbed):
    # Sin las lineas, el modelo reintenta a ciegas: ocho iteraciones perdidas
    # en una tarea real contra un docstring que aparecia dos veces.
    result = swebench_tools.edit_file("/testbed/utils.py", "numbers", "values")

    assert "found 5" in result
    assert "It matches starting at lines:" in result
    assert "Extend old_str" in result
    assert (testbed / "utils.py").read_text() == UTILS
