"""Controlled LLM responses; actual CLI, adapter, container, MCP and worker.

No external API is contacted. The model's replies are fixtures, so this proves
the wiring and that a real patch comes back, not a benchmark result.
"""

import json
import subprocess
from pathlib import Path

import httpx
import openai
import pytest

from agent_swebench import main
from agent_smith.models import SolutionOutput
from agent_smith.providers import ProviderClient, ProviderConfig


ROOT = Path(__file__).resolve().parents[1]
IMAGE = "swebench/sweb.eval.x86_64.sympy_1776_sympy-23534:latest"
TARGET = "/testbed/sympy/core/symbol.py"

REPLIES = [
    f'Thought: locate the file.\n```python\nprint(list_files(directory="/testbed/sympy/core", pattern="symbol.py"))\n```\n<end_code>',
    'Thought: find the class.\n```python\nprint(search_function_or_class_definition_in_code(name="Symbol"))\n```\n<end_code>',
    'Thought: add a marker I can then edit.\n```python\n'
    'print(run_command(command="echo \'# agent-smith-marker\' >> sympy/core/symbol.py", workdir="/testbed"))\n'
    '```\n<end_code>',
    f'Thought: apply the change.\n```python\nprint(edit_file(filepath="{TARGET}", '
    'old_str="# agent-smith-marker", new_str="# agent-smith-fix"))\n```\n<end_code>',
    'Thought: review the diff.\n```python\nprint(get_patch())\n```\n<end_code>',
    'Thought: submit.\n```python\nfinal_answer(get_patch())\n```\n<end_code>',
]


def require_image():
    completed = subprocess.run(
        ["docker", "image", "inspect", IMAGE], capture_output=True, check=False, timeout=60,
    )
    if completed.returncode != 0:
        pytest.skip(f"The SWE-bench image {IMAGE} is not available locally")


def _containers_for_image() -> set:
    completed = subprocess.run(
        ["docker", "ps", "-aq", "--filter", f"ancestor={IMAGE}"],
        text=True, capture_output=True, check=False,
    )
    return set(completed.stdout.split())


def test_cli_explores_edits_and_submits_the_real_patch(tmp_path, monkeypatch):
    require_image()
    monkeypatch.delenv("AGENT_SMITH_LOG_LEVEL", raising=False)
    before = _containers_for_image()
    histories = []

    def handler(request):
        histories.append(json.loads(request.content)["messages"])
        return httpx.Response(200, json={
            "choices": [{"message": {"content": REPLIES[len(histories) - 1]}}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 40},
        })

    monkeypatch.setattr("agent_smith.providers.OpenAI", lambda **kwargs: openai.OpenAI(
        http_client=httpx.Client(transport=httpx.MockTransport(handler)), **kwargs))
    provider = ProviderClient(ProviderConfig(
        api_url="https://example.invalid/v1", model_name="controlled-fixture",
        api_key_environment_variables=["TEST_KEY"],
    ), {"TEST_KEY": "not-a-real-key"})
    monkeypatch.setattr(ProviderClient, "from_environment", lambda *args, **kwargs: provider)

    task = tmp_path / "task.json"
    task.write_text(json.dumps({
        "instance_id": "sympy__sympy-23534", "problem_statement": "symbols with cls=Function",
        "docker_image": IMAGE, "eval_script": "echo skipped", "repo": "sympy/sympy",
    }))
    output = tmp_path / "solution.json"

    assert main([
        "--task-file", str(task), "--output", str(output),
        "--model-name", "controlled-fixture", "--provider-url", "https://example.invalid/v1",
    ]) == 0

    result = SolutionOutput.model_validate_json(output.read_text())
    assert result.success, result.error
    assert result.benchmark == "swebench" and result.task_id == "sympy__sympy-23534"

    # La solucion es el diff integro, sin Markdown ni prosa.
    assert result.solution.startswith("diff --git")
    assert "sympy/core/symbol.py" in result.solution
    assert "+# agent-smith-fix" in result.solution
    assert "agent-smith-marker" not in result.solution

    # Cada herramienta fue observada de verdad por el bucle.
    assert "/testbed/sympy/core/symbol.py" in result.steps[0].sandbox_output
    assert "class Symbol" in result.steps[1].sandbox_output
    assert "exit_code: 0" in result.steps[2].sandbox_output
    assert "Edit applied successfully." in result.steps[3].sandbox_output
    assert result.steps[4].sandbox_output.lstrip().startswith("diff --git")

    assert result.iterations == result.total_requests == len(REPLIES)
    assert result.total_input_tokens == 120 * len(REPLIES)
    assert result.total_time_seconds < 900

    # El contenedor de la tarea no debe sobrevivir al agente.
    assert _containers_for_image() == before


NO_EDIT_REPLIES = [
    'Thought: look around.\n```python\nprint(list_files(directory="/testbed/sympy/core", pattern="symbol.py"))\n```\n<end_code>',
    'Thought: submit.\n```python\nfinal_answer(get_patch())\n```\n<end_code>',
]


def test_submitting_without_editing_is_not_a_success(tmp_path, monkeypatch):
    # Un modelo real entrego el aviso "No changes yet." de get_patch como si
    # fuera el parche, y la tarea se daba por buena. Eso es un exito falso.
    require_image()
    monkeypatch.delenv("AGENT_SMITH_LOG_LEVEL", raising=False)
    histories = []

    def handler(request):
        histories.append(json.loads(request.content)["messages"])
        return httpx.Response(200, json={
            "choices": [{"message": {"content": NO_EDIT_REPLIES[len(histories) - 1]}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 30},
        })

    monkeypatch.setattr("agent_smith.providers.OpenAI", lambda **kwargs: openai.OpenAI(
        http_client=httpx.Client(transport=httpx.MockTransport(handler)), **kwargs))
    provider = ProviderClient(ProviderConfig(
        api_url="https://example.invalid/v1", model_name="controlled-fixture",
        api_key_environment_variables=["TEST_KEY"],
    ), {"TEST_KEY": "not-a-real-key"})
    monkeypatch.setattr(ProviderClient, "from_environment", lambda *args, **kwargs: provider)

    task = tmp_path / "task.json"
    task.write_text(json.dumps({
        "instance_id": "sympy__sympy-23534", "problem_statement": "x",
        "docker_image": IMAGE, "eval_script": "echo skipped", "repo": "sympy/sympy",
    }))
    output = tmp_path / "solution.json"

    assert main([
        "--task-file", str(task), "--output", str(output),
        "--model-name", "controlled-fixture", "--provider-url", "https://example.invalid/v1",
    ]) == 0

    result = SolutionOutput.model_validate_json(output.read_text())
    assert result.success is False
    assert "not a diff" in (result.error or "")
