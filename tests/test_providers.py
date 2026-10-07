"""Fake HTTP responses verify actual request construction and accounting."""
import json
import time
from pathlib import Path

import httpx
import openai
import pytest

from agent_smith.providers import ProviderClient, ProviderConfig


def config(**kwargs):
    return ProviderConfig(api_url="https://example.invalid/v1", model_name="test-model",
                          api_key_environment_variables=["KEY_ONE", "KEY_TWO"], **kwargs)


def answer(text="```python\nprint(1)\n```", incoming=100, outgoing=20):
    return {"choices": [{"message": {"content": text}}],
            "usage": {"prompt_tokens": incoming, "completion_tokens": outgoing}}


def mock_http(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr("agent_smith.providers.OpenAI", lambda **kwargs: openai.OpenAI(
        http_client=httpx.Client(transport=transport), **kwargs))


def complete(client, **kwargs):
    parameters = dict(max_input_tokens=6000, max_output_tokens=1500, deadline=time.monotonic() + 10)
    parameters.update(kwargs)
    return client.complete([{"role": "user", "content": "hello"}], **parameters)


def test_configuration_selection_and_key_deduplication(tmp_path):
    path = tmp_path / "models.json"
    path.write_text(json.dumps({"providers": [config().model_dump()]}))
    client = ProviderClient.from_environment(
        "https://example.invalid/v1/", "test-model", path, {"KEY_ONE": "same", "KEY_TWO": "same"})
    assert client.api_keys == ["same"]
    with pytest.raises(ValueError, match="exactly one"):
        ProviderClient.from_environment("https://example.invalid/v1", "different", path, {})
    with pytest.raises(RuntimeError, match="Missing API key"):
        ProviderClient(config(), {})


def test_default_models_configuration_serves_both_exams():
    """The adapters fall back to this path when the .env omits the variable."""
    path = Path(__file__).resolve().parents[1] / "configs" / "models_template.json"
    assert path.is_file(), "the adapters default to configs/models_template.json"

    swebench = ProviderClient.from_environment(
        "https://api.groq.com/openai/v1", "qwen/qwen3.8-27b", path,
        {"GROQ_API_KEY": "a", "GROQ_API_KEY_2": "b", "GROQ_API_KEY_3": "c"})
    assert swebench.api_keys == ["a", "b", "c"]
    assert swebench.config.stop_sequences == ["<end_code>", "Observation:"]

    backup = ProviderClient.from_environment(
        "https://api.mistral.ai/v1", "codestral-2508", path, {"MISTRAL_API_KEY": "k"})
    assert backup.api_keys == ["k"]
    assert backup.config.stop_sequences == ["<end_code>", "Observation:"]

    assert swebench.config.max_input_per_request == 6000
    assert backup.config.max_input_per_request is None

    mbpp = ProviderClient.from_environment(
        "https://openrouter.ai/api/v1", "inclusionai/ling-3.0-flash-vl:free", path,
        {"OPENROUTER_API_KEY": "k"})
    assert mbpp.api_keys == ["k"]


def test_the_per_request_input_cap_is_optional_and_positive():
    assert config().max_input_per_request is None
    assert config(max_input_per_request=6000).max_input_per_request == 6000
    with pytest.raises(ValueError):
        config(max_input_per_request=0)


def test_payload_and_measured_usage(monkeypatch):
    sent = []
    def handler(request):
        sent.append(request)
        body = answer()
        body["usage"]["completion_tokens_details"] = {"reasoning_tokens": 10}
        return httpx.Response(200, json=body)
    mock_http(monkeypatch, handler)
    result = complete(ProviderClient(config(), {"KEY_ONE": "fake-one"}), max_output_tokens=123)
    payload = json.loads(sent[0].content)
    assert payload["max_tokens"] == 123 and payload["stream"] is False
    assert payload["stop"] == ["<end_code>"]
    assert payload["temperature"] == 0.1
    assert str(sent[0].url) == "https://example.invalid/v1/chat/completions"
    assert sent[0].headers["Authorization"] == "Bearer fake-one"
    assert result.input_tokens == 100 and result.output_tokens == 20
    assert result.request_count == 1 and result.retries == 0
    assert result.usage_complete and result.error is None


def test_bounded_rotation_accounts_for_all_known_attempts(monkeypatch):
    keys = []
    def handler(request):
        keys.append(request.headers["Authorization"])
        if len(keys) == 1:
            return httpx.Response(429, json={"usage": {"prompt_tokens": 0, "completion_tokens": 0}})
        return httpx.Response(200, json=answer())
    mock_http(monkeypatch, handler)
    client = ProviderClient(config(max_retries=1), {"KEY_ONE": "one", "KEY_TWO": "two"})
    result = complete(client)
    assert keys == ["Bearer one", "Bearer two"]
    assert result.request_count == 2 and result.retries == 1
    assert result.input_tokens == 100 and result.output_tokens == 20
    assert result.error is None


@pytest.mark.parametrize("reported", ["actual/free-model", None, "", 123])
def test_router_preserves_reported_model_without_changing_request_target(monkeypatch, reported):
    def handler(request):
        assert json.loads(request.content)["model"] == "openrouter/free"
        body = answer()
        body["model"] = reported
        return httpx.Response(200, json=body)
    mock_http(monkeypatch, handler)
    settings = config()
    settings.model_name = "openrouter/free"
    client = ProviderClient(settings, {"KEY_ONE": "fake-one"})
    result = complete(client)
    assert result.model_name == (reported if reported == "actual/free-model" else "openrouter/free")
    assert client.config.model_name == "openrouter/free"
    assert result.input_tokens == 100 and result.output_tokens == 20


def test_real_rate_limit_without_usage_rotates_to_the_next_key(monkeypatch):
    # OpenRouter responde al límite diario sin bloque usage. Un 429 no genera
    # nada, así que el subtotal sigue siendo exacto y se puede probar otra clave.
    keys = []
    def handler(request):
        keys.append(request.headers["Authorization"])
        if len(keys) == 1:
            return httpx.Response(429, json={"error": {"message": "free-models-per-day"}})
        return httpx.Response(200, json=answer())
    mock_http(monkeypatch, handler)
    client = ProviderClient(config(max_retries=1), {"KEY_ONE": "one", "KEY_TWO": "two"})
    result = complete(client)
    assert keys == ["Bearer one", "Bearer two"]
    assert result.usage_complete and result.error is None
    assert result.input_tokens == 100 and result.output_tokens == 20
    assert result.request_count == 2 and result.retries == 1


def test_every_key_rate_limited_fails_without_inventing_usage(monkeypatch):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(429, json={"error": {"message": "free-models-per-day"}})
    mock_http(monkeypatch, handler)
    client = ProviderClient(config(max_retries=1), {"KEY_ONE": "one", "KEY_TWO": "two"})
    result = complete(client)
    assert len(calls) == 2
    assert "HTTP 429" in result.error
    assert result.input_tokens == 0 and result.output_tokens == 0


def test_a_200_without_usage_does_not_retry_unknown_spend(monkeypatch):
    # Aqui si pudo generar y no sabemos cuanto: es el unico caso que sigue
    # siendo consumo desconocido, y no se vuelve a pedir.
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "texto"}}]})
    mock_http(monkeypatch, handler)
    result = complete(ProviderClient(config(), {"KEY_ONE": "one", "KEY_TWO": "two"}))

    assert len(calls) == 1
    assert not result.usage_complete and "subtotals" in result.error


@pytest.mark.parametrize("status", [401, 403, 400])
def test_non_retryable_status_is_preserved(monkeypatch, status):
    mock_http(monkeypatch, lambda request: httpx.Response(status, json={}))
    result = complete(ProviderClient(config(), {"KEY_ONE": "one"}))
    assert result.request_count == 1 and f"HTTP {status}" in result.error


def test_partial_usage_is_not_replaced_by_estimates(monkeypatch):
    body = answer()
    del body["usage"]["completion_tokens"]
    mock_http(monkeypatch, lambda request: httpx.Response(200, json=body))
    result = complete(ProviderClient(config(), {"KEY_ONE": "one"}))
    assert result.input_tokens == 100 and result.output_tokens == 0
    assert not result.usage_complete and "subtotals" in result.error


def test_transport_error_does_not_leak_credentials_or_retry(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("secret: fake-one")
    mock_http(monkeypatch, handler)
    result = complete(ProviderClient(config(), {"KEY_ONE": "fake-one"}))
    assert result.request_count == 1 and not result.usage_complete
    assert "fake-one" not in result.error


def test_a_request_timeout_ends_with_an_explicit_message(monkeypatch):
    def handler(request):
        raise httpx.ReadTimeout("slow provider")
    mock_http(monkeypatch, handler)
    result = complete(ProviderClient(config(), {"KEY_ONE": "fake-one"}))
    assert result.request_count == 1 and not result.usage_complete
    assert result.error == "LLM request failed (APITimeoutError); token usage is unknown."


def test_provider_error_keeps_its_diagnosis_without_leaking_keys(monkeypatch):
    mock_http(monkeypatch, lambda request: httpx.Response(503, json={
        "error": {"message": "Model overloaded for fake-one; alternative fake-two."},
    }))
    result = complete(ProviderClient(config(max_retries=0), {"KEY_ONE": "fake-one", "KEY_TWO": "fake-two"}))
    assert "HTTP 503" in result.error and "Model overloaded" in result.error
    assert "fake-one" not in result.error and "fake-two" not in result.error
    # Un rechazo no genera: su consumo es cero conocido, no un subtotal incierto.
    assert "known subtotals" not in result.error
    assert result.request_count == 1 and result.usage_complete


def test_limits_stop_before_sending(monkeypatch):
    def handler(request):
        pytest.fail("Must not send after a limit.")
    mock_http(monkeypatch, handler)
    client = ProviderClient(config(), {"KEY_ONE": "one"})
    for kwargs in ({"max_input_tokens": 1}, {"max_output_tokens": 0}, {"deadline": 0}):
        result = complete(client, **kwargs)
        assert result.request_count == 0 and result.error


def test_real_over_budget_usage_is_kept(monkeypatch):
    mock_http(monkeypatch, lambda request: httpx.Response(200, json=answer(incoming=7000)))
    result = complete(ProviderClient(config(), {"KEY_ONE": "one"}))
    assert result.input_tokens == 7000 and "exceeded" in result.error


def test_long_history_does_not_count_each_byte_as_a_token(monkeypatch):
    mock_http(monkeypatch, lambda request: httpx.Response(200, json=answer(incoming=1600)))
    client = ProviderClient(config(), {"KEY_ONE": "fake-one"})
    result = client.complete(
        [{"role": "user", "content": "some Python code and observations\n" * 180}],
        max_input_tokens=4500, max_output_tokens=500, deadline=time.monotonic() + 10,
    )
    assert result.request_count == 1 and result.error is None
    assert result.input_tokens == 1600


def test_an_empty_200_is_retried_and_the_retry_counts(monkeypatch):
    # Gemini devuelve de vez en cuando un 200 sin content. Antes eso terminaba
    # la tarea; ahora se reintenta y sus tokens se suman igual.
    calls = []
    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, json={
                "choices": [{"message": {"content": None}}],
                "usage": {"prompt_tokens": 40, "completion_tokens": 5},
            })
        return httpx.Response(200, json=answer())
    mock_http(monkeypatch, handler)
    result = complete(ProviderClient(config(max_retries=1), {"KEY_ONE": "one"}))

    assert len(calls) == 2
    assert result.error is None and result.text
    assert result.input_tokens == 140 and result.output_tokens == 25
    assert result.request_count == 2 and result.retries == 1


def test_an_empty_200_that_never_recovers_is_reported(monkeypatch):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": ""}}],
            "usage": {"prompt_tokens": 40, "completion_tokens": 5},
        })
    mock_http(monkeypatch, handler)
    result = complete(ProviderClient(config(max_retries=1), {"KEY_ONE": "one"}))

    assert len(calls) == 2
    assert "did not contain text content" in (result.error or "")


def test_native_tool_calls_are_translated_when_there_is_no_text(monkeypatch):
    # Gemini llama funciones por su canal nativo aunque nunca le mandamos
    # esquemas: llega sin content y con tool_calls. Antes moria la tarea.
    def handler(request):
        return httpx.Response(200, json={
            "choices": [{"message": {"role": "assistant", "tool_calls": [
                {"function": {"name": "search_code", "arguments": '{"pattern": "cotm"}'}},
            ]}}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 10},
        })
    mock_http(monkeypatch, handler)
    result = complete(ProviderClient(config(), {"KEY_ONE": "one"}))

    assert result.error is None
    assert "<tool_name>search_code</tool_name>" in result.text
    assert '{"pattern": "cotm"}' in result.text


def test_a_response_with_neither_text_nor_tool_calls_is_still_reported(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={
            "choices": [{"message": {"role": "assistant"}}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 10},
        })
    mock_http(monkeypatch, handler)
    result = complete(ProviderClient(config(max_retries=0), {"KEY_ONE": "one"}))

    assert "did not contain text content" in (result.error or "")


def test_a_503_is_retried_and_counts_as_zero_not_unknown(monkeypatch):
    # Un 503 tampoco llega a generar. Antes la guarda de consumo desconocido
    # cancelaba el reintento y seis ejecuciones seguidas murieron por esto.
    calls = []
    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(503, json={"error": {"message": "overloaded"}})
        return httpx.Response(200, json=answer())
    mock_http(monkeypatch, handler)
    result = complete(ProviderClient(config(max_retries=1), {"KEY_ONE": "one"}))

    assert len(calls) == 2
    assert result.error is None and result.usage_complete
    assert result.input_tokens == 100 and result.output_tokens == 20


def test_a_persistent_503_reports_the_status_without_fake_subtotals(monkeypatch):
    mock_http(monkeypatch, lambda request: httpx.Response(503, json={}))
    result = complete(ProviderClient(config(max_retries=1), {"KEY_ONE": "one"}))

    assert "HTTP 503" in (result.error or "")
    assert "subtotals" not in (result.error or "")
    assert result.input_tokens == 0 and result.output_tokens == 0


def test_a_429_waits_what_the_provider_asks_when_there_is_no_other_key(monkeypatch):
    calls, waits = [], []
    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, headers={"retry-after": "20"}, json={})
        return httpx.Response(200, json=answer())
    mock_http(monkeypatch, handler)
    monkeypatch.setattr("agent_smith.providers.time.sleep", waits.append)
    result = complete(ProviderClient(config(max_retries=1), {"KEY_ONE": "one"}),
                      deadline=time.monotonic() + 100)
    assert len(waits) == 1 and 19 < waits[0] <= 20
    assert result.error is None and result.request_count == 2


def test_a_429_switches_to_a_free_key_without_waiting(monkeypatch):
    keys, waits = [], []
    def handler(request):
        keys.append(request.headers["Authorization"])
        if len(keys) == 1:
            return httpx.Response(429, headers={"retry-after": "20"}, json={})
        return httpx.Response(200, json=answer())
    mock_http(monkeypatch, handler)
    monkeypatch.setattr("agent_smith.providers.time.sleep", waits.append)
    client = ProviderClient(config(max_retries=1), {"KEY_ONE": "one", "KEY_TWO": "two"})
    result = complete(client, deadline=time.monotonic() + 100)
    assert keys == ["Bearer one", "Bearer two"] and waits == []
    assert result.error is None


def test_a_key_is_not_reused_before_the_time_it_asked_for(monkeypatch):
    keys, waits = [], []
    def handler(request):
        keys.append(request.headers["Authorization"])
        if len(keys) <= 2:
            seconds = "10" if len(keys) == 1 else "30"
            return httpx.Response(429, headers={"retry-after": seconds}, json={})
        return httpx.Response(200, json=answer())
    mock_http(monkeypatch, handler)
    monkeypatch.setattr("agent_smith.providers.time.sleep", waits.append)
    client = ProviderClient(config(max_retries=2), {"KEY_ONE": "one", "KEY_TWO": "two"})
    result = complete(client, deadline=time.monotonic() + 100)
    # Both keys are limited: the one free soonest (one, 10 s) is used after waiting.
    assert keys == ["Bearer one", "Bearer two", "Bearer one"]
    assert len(waits) == 1 and 9 < waits[0] <= 10
    assert result.error is None


def test_no_waiting_many_minutes_for_a_daily_limit(monkeypatch):
    calls, waits = [], []
    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={"retry-after": "507"}, json={
            "error": {"message": "Rate limit reached on tokens per day (TPD)"}})
    mock_http(monkeypatch, handler)
    monkeypatch.setattr("agent_smith.providers.time.sleep", waits.append)
    result = complete(ProviderClient(config(max_retries=5), {"KEY_ONE": "one"}),
                      deadline=time.monotonic() + 900)
    assert len(calls) == 1 and waits == []
    assert "HTTP 429" in result.error and "No key is available again" in result.error
