"""Exercise the common loop with known code and scripted completion metadata."""

import time
from types import SimpleNamespace

from agent_smith.agent_loop import run_agent_loop, trim_history, MINIMUM_HISTORY_MESSAGES
from agent_smith.models import AgentLimits, SandboxConfig
from agent_smith.providers import CompletionResponse
from agent_smith.sandbox import SandboxExecution
from agent_smith.sandbox_session import SandboxSession


class ScriptedProvider:

    def __init__(self, replies, max_input_per_request=None):
        self.config = SimpleNamespace(max_input_per_request=max_input_per_request)
        self.replies = iter(replies)
        self.histories = []

    def complete(self, messages, **kwargs):
        self.histories.append(list(messages))
        text = next(self.replies)
        return CompletionResponse(text, 100, 50, 1, "https://example.invalid/v1", "fixture", 0, 1)


def run(replies, cap=None, **limits):
    provider = ScriptedProvider(replies, cap)
    def scenario():
        sandbox = SandboxSession(SandboxConfig(allowed_directories=[]))
        try:
            sandbox.start()
            result = run_agent_loop(
                task_id="fixture", benchmark="mbpp", system_prompt="system", task_prompt="task",
                provider=provider, sandbox=sandbox,
                limits=AgentLimits(max_iterations=limits.get("iterations", 3),
                                   max_input_tokens=limits.get("input", 6000),
                                   max_output_tokens=limits.get("output", 1500), max_time_seconds=10),
                started_at=time.monotonic(),
            )
            return result
        finally:
            sandbox.close()
    return scenario(), provider


def test_extraction_feedback_and_final_step_boundary():
    result, provider = run(["No code.", "```python\nx = 4\nprint(x)\n```",
                            "```python\nfinal_answer(str(x))\n```"], output=150, input=300)
    assert result.success and result.solution == "4"
    assert result.iterations == 3 and result.total_requests == 3
    assert result.total_input_tokens == 300 and result.total_output_tokens == 150
    assert result.steps[0].sandbox_input == ""
    assert "No valid Python code" in provider.histories[1][-1]["content"]
    assert provider.histories[2][-1]["content"] == "Observation:\n4\n"


def test_runtime_error_becomes_observation_for_next_iteration():
    result, provider = run(["```python\nx = 4\nraise ValueError('fix me')\n```",
                            "```python\nfinal_answer(str(x + 1))\n```"])
    assert result.success and result.solution == "5"
    assert "ValueError: fix me" in provider.histories[1][-1]["content"]


def test_worker_timeout_preserves_step_and_stops_task():
    # SystemExit propagation is covered by supervisor tests; a lost worker gives a partial result.
    result, provider = run(["```python\nprint('before')\nwhile True: pass\n```"], iterations=1)
    assert not result.success and len(provider.histories) == 1
    assert result.total_input_tokens == 100
    assert "before" in result.steps[0].sandbox_output
    assert result.error


def test_budget_exhaustion_keeps_existing_steps():
    result, provider = run(["```python\nprint('one')\n```"], output=50)
    assert not result.success and result.iterations == 1
    assert result.total_output_tokens == 50
    assert "budget" in result.error


def _history(pairs, content="x" * 400):
    messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "tarea"}]
    for number in range(pairs):
        messages.append({"role": "assistant", "content": f"respuesta {number} {content}"})
        messages.append({"role": "user", "content": f"observacion {number} {content}"})
    return messages


def test_a_generous_budget_keeps_the_whole_history():
    messages = _history(10)
    assert trim_history(messages, 1_000_000) == messages


def test_a_tight_budget_keeps_the_task_and_the_most_recent_exchanges():
    trimmed = trim_history(_history(20), 2_000)

    assert trimmed[0]["content"] == "s"
    assert trimmed[1]["content"] == "tarea"
    assert trimmed[-1]["content"].startswith("observacion 19")
    assert len(trimmed) < 2 + 20 * 2


def test_the_last_exchanges_survive_even_an_impossible_budget():
    trimmed = trim_history(_history(20), 0)

    assert len(trimmed) == 2 + MINIMUM_HISTORY_MESSAGES
    assert trimmed[-1]["content"].startswith("observacion 19")


def test_a_bigger_budget_keeps_more_history_than_a_smaller_one():
    messages = _history(20)
    assert len(trim_history(messages, 20_000)) > len(trim_history(messages, 3_000))


def test_trimming_does_not_alter_the_original_list():
    messages = _history(10)
    trim_history(messages, 1_000)
    assert len(messages) == 22


def test_an_unusable_response_becomes_an_observation_instead_of_ending_the_task():
    # Gemini devuelve a veces una llamada de funcion malformada: sin texto pero
    # con consumo medido. Antes eso terminaba la tarea en la iteracion 2.
    from types import SimpleNamespace

    respuestas = [
        SimpleNamespace(
            text="", input_tokens=10, output_tokens=1, request_time_ms=1.0,
            api_url="u", model_name="m", retries=0, request_count=1,
            usage_complete=True, error="Provider response did not contain text content.",
            recoverable=True,
        ),
        SimpleNamespace(
            text="```python\nfinal_answer('listo')\n```", input_tokens=10, output_tokens=1,
            request_time_ms=1.0, api_url="u", model_name="m", retries=0, request_count=1,
            usage_complete=True, error=None, recoverable=False,
        ),
    ]

    class Proveedor:
        config = SimpleNamespace(max_input_per_request=None)
        def complete(self, messages, **kwargs):
            return respuestas.pop(0)

    class Caja:
        manual = None

        def execute(self, code, deadline=None):
            from agent_smith.sandbox import SandboxExecution
            return SandboxExecution(final_answer="listo")

    from agent_smith.models import AgentLimits
    resultado = run_agent_loop(
        task_id="t", benchmark="swebench", system_prompt="s", task_prompt="p",
        provider=Proveedor(), sandbox=Caja(),
        limits=AgentLimits(max_iterations=5, max_input_tokens=1000,
                           max_output_tokens=1000, max_time_seconds=60),
        started_at=time.monotonic(),
    )

    assert resultado.success is True
    assert resultado.iterations == 2
    assert "did not contain text content" in resultado.steps[0].sandbox_output


def test_the_loop_runs_the_block_that_calls_a_tool_after_an_example():
    # Change 1: the names come from MCP discovery (sandbox.manual), plus the
    # sandbox's own final_answer.
    class Caja:
        manual = SimpleNamespace(tools=[{"name": "get_patch"}])

        def __init__(self):
            self.codigos = []

        def execute(self, code, deadline=None):
            self.codigos.append(code)
            return SandboxExecution(output="ok")

    caja = Caja()
    respuestas = [
        "```python\ndef ejemplo():\n    pass\n```\n```python\nprint(get_patch())\n```",
        "```python\nx = 1\n```\n```python\nfinal_answer('listo')\n```",
    ]
    run_agent_loop(
        task_id="t", benchmark="swebench", system_prompt="s", task_prompt="p",
        provider=ScriptedProvider(respuestas), sandbox=caja,
        limits=AgentLimits(max_iterations=2, max_input_tokens=1000,
                           max_output_tokens=1000, max_time_seconds=60),
        started_at=time.monotonic(),
    )

    assert caja.codigos == ["print(get_patch())", "final_answer('listo')"]


FIVE_REPLIES = ["```python\nprint(1)\n```"] * 4 + ["```python\nfinal_answer('ok')\n```"]


def test_without_a_per_request_cap_the_whole_history_is_sent():
    result, provider = run(FIVE_REPLIES, iterations=5)
    assert result.success
    assert len(provider.histories[4]) == 2 + 4 * 2


def test_a_per_request_cap_trims_the_history_sent_to_the_model():
    # Change 2: Groq answers 413 to any Qwen request above 7,000 input tokens.
    result, provider = run(FIVE_REPLIES, cap=1, iterations=5)
    assert result.success
    assert len(provider.histories[4]) == 2 + MINIMUM_HISTORY_MESSAGES
