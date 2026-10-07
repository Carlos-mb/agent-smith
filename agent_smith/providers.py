"""The LLM client: one OpenAI-compatible provider, measured usage, key rotation.

Every free provider we use (Mistral, OpenRouter, Google, Groq) speaks the
OpenAI chat-completions API, so the official `openai` SDK talks to all of
them: only the base URL, the model name and the key change. The SDK sends the
request and turns HTTP errors into exceptions; this module decides what each
outcome means for the task's token budget.
"""

from __future__ import annotations

from agent_smith.logging_config import get_logger, register_secrets

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping

import openai
from openai import OpenAI
from pydantic import BaseModel, Field

from agent_smith.io import load_model

logger = get_logger('agent_smith.providers')


class ProviderConfig(BaseModel):
    """Store one chat-completions configuration, without API secrets."""

    api_url: str
    model_name: str
    api_key_environment_variables: list[str] = Field(default_factory=list)
    timeout_seconds: float = Field(default=60.0, gt=0)
    max_retries: int = Field(default=2, ge=0)
    temperature: float = Field(default=0.1, ge=0, le=2)
    stop_sequences: list[str] = Field(default_factory=lambda: ["<end_code>"])
    reasoning_effort: str | None = None
    reasoning_enabled: bool | None = None
    max_output_per_request: int = Field(default=600, gt=0)
    max_input_per_request: int | None = Field(default = None, gt=0)
    output_limit_parameter: Literal[
        "max_tokens", "max_completion_tokens"] = "max_tokens"


class ProvidersConfig(BaseModel):
    """Store the model configurations available for explicit CLI selection."""

    providers: list[ProviderConfig] = Field(default_factory=list)


@dataclass(frozen=True)
class CompletionResponse:
    """Return text, measured usage and any error from one completion call.

    Metrics include every HTTP attempt made by that operation. When usage is
    incomplete, token counts are known subtotals and must not imply zero usage.
    This internal result does not change the public SolutionOutput JSON schema.
    """

    text: str
    input_tokens: int
    output_tokens: int
    request_time_ms: float
    api_url: str
    model_name: str
    retries: int
    request_count: int
    usage_complete: bool = True
    error: str | None = None
    # An unusable model reply is not a provider failure: if its usage is
    # measured, the loop can continue with an observation.
    recoverable: bool = False


def estimate_input_tokens(messages: list[dict[str, str]]) -> int:
    """Approximate preflight estimate, NEVER a measurement for result metrics.

    UTF-8 bytes divided by four, plus framing headroom. Actual usage is checked
    after every reply: this is not the provider's tokenizer.
    """
    logger.debug("Entrando en estimate_input_tokens")
    estimate = 64 + sum((len(m["content"].encode("utf-8")) + 3) // 4 + 32
                        for m in messages)
    logger.debug("Entrada estimada: %s tokens en %s mensajes; no es usage "
                 "medido", estimate, len(messages))
    return estimate


def render_tool_calls(message: dict[str, Any]) -> str:
    """Render a provider's native tool calls as the <tool_use> text dialect.

    Gemini sometimes calls functions through its native channel even though
    we never send schemas: the reply arrives without content and with
    tool_calls. It is translated into the text code_extraction already
    converts, so there is a single place where a call becomes Python.
    """
    logger.debug("Entrando en render_tool_calls")
    blocks = []
    for call in message.get("tool_calls") or []:
        function = call.get("function") or {}
        if not isinstance(function.get("name"), str):
            continue
        arguments = function.get("arguments") or "{}"
        blocks.append(
            f"<tool_use>\n<tool_name>{function['name']}</tool_name>\n"
            f"<arguments>\n{arguments}\n</arguments>\n</tool_use>"
        )
    return "\n".join(blocks)


class ProviderClient:
    """Keep one provider configuration and its keys; measure every request."""

    def __init__(self, config: ProviderConfig,
                 environment: Mapping[str, str] | None = None):
        logger.debug("Entrando en ProviderClient.__init__")
        self.config = config.model_copy(deep=True)
        environment = os.environ if environment is None else environment
        # Several variables may hold the same key: keep each key once.
        self.api_keys = list(dict.fromkeys(
            environment[name] for name in config.api_key_environment_variables
            if environment.get(name)
        ))
        if not self.api_keys:
            logger.error("No hay claves configuradas para el proveedor")
            raise RuntimeError(
                "Missing API key; set one of: "
                + ", ".join(config.api_key_environment_variables))
        self.key_index = 0
        # When each key may be used again (time.monotonic()); 0 means now.
        self.available_at = [0.0] * len(self.api_keys)
        register_secrets(self.api_keys)
        logger.info("Proveedor preparado: modelo=%s, claves disponibles=%s",
                    config.model_name, len(self.api_keys))

    @classmethod
    def from_environment(
        cls, api_url: str, model_name: str, config_path: str | Path,
        environment: Mapping[str, str] | None = None,
    ) -> "ProviderClient":
        """Pick the one configuration in config_path matching URL and model."""
        logger.debug("Entrando en ProviderClient.from_environment")
        logger.debug("Buscando configuración explícita en %s", config_path)
        configurations = load_model(config_path, ProvidersConfig)
        matches = [c for c in configurations.providers
                   if c.api_url.rstrip("/") == api_url.rstrip("/")
                   and c.model_name == model_name]
        if len(matches) != 1:
            logger.error("La selección URL/modelo tiene %s coincidencias; "
                         "se esperaba una", len(matches))
            raise ValueError("Expected exactly one configuration "
                             "matching CLI URL and model.")
        return cls(matches[0], environment)

    def complete(
        self, messages: list[dict[str, str]], *, max_input_tokens: int,
        max_output_tokens: int, deadline: float,
    ) -> CompletionResponse:
        """Ask for one reply, retrying within the task's time and tokens."""
        logger.debug("Entrando en ProviderClient.complete")
        input_tokens = output_tokens = requests = 0
        elapsed_ms = 0.0
        text = ""
        model_name = self.config.model_name
        error = None
        usage_complete = True
        for attempt in range(1 + self.config.max_retries):
            # Only a 200 generates anything; a rejection costs a known zero.
            generated = False
            # Wait until the chosen key may be used again. More than a minute
            # means a daily limit on every key: waiting would only burn the
            # task's time.
            wait = self.available_at[self.key_index] - time.monotonic()
            if wait > 60:
                error = ((error or "") + " No key is available again for "
                         f"{wait:.0f}s.").strip()
                break
            if wait > 0:
                if time.monotonic() + wait >= deadline:
                    error = "Retry would exceed the task deadline."
                    break
                logger.warning("Esperando %.2fs a que la clave con índice %s "
                               "vuelva a estar disponible", wait,
                               self.key_index)
                time.sleep(wait)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                error = "Task deadline reached before LLM request."
                break
            if (estimate_input_tokens(messages)
                    > max_input_tokens - input_tokens):
                error = "Remaining input budget is below the prompt estimate."
                break
            allowance = min(max_output_tokens - output_tokens,
                            self.config.max_output_per_request)
            if allowance <= 0:
                error = "Output token budget exhausted."
                break
            logger.info(
                "Petición LLM %s/%s: modelo=%s, clave índice=%s, "
                "salida máxima=%s, tiempo restante=%.2fs",
                attempt + 1, 1 + self.config.max_retries,
                self.config.model_name, self.key_index, allowance, remaining,
            )
            for number, message in enumerate(messages, start=1):
                logger.debug("IA ENVIADO [mensaje %s, rol=%s]:\n%s",
                             number, message["role"], message["content"])
            requests += 1
            started = time.monotonic()
            try:
                response = self._send(messages, allowance,
                                      min(remaining,
                                          self.config.timeout_seconds))
            except openai.APIStatusError as exc:
                # 4xx/5xx: the provider rejected the request before generating.
                elapsed_ms += (time.monotonic() - started) * 1000
                logger.debug("IA RECIBIDO [HTTP %s, cuerpo completo]:\n%s",
                             exc.status_code, exc.response.text)
                error = f"Provider returned HTTP {exc.status_code}."
                if isinstance(exc.body, dict) and isinstance(
                        exc.body.get("message"), str):
                    error += " " + self._hide_keys(exc.body["message"])
                if exc.status_code not in (429, 500, 502, 503, 504):
                    break
                # The provider says how long to wait in retry-after (seconds).
                try:
                    wait = float(exc.response.headers["retry-after"])
                except (KeyError, ValueError):
                    wait = 0.5
                self.available_at[self.key_index] = time.monotonic() + wait
                if exc.status_code == 429:
                    # This key is rate limited: use the key that is available
                    # soonest, which may be another account.
                    self.key_index = min(range(len(self.api_keys)),
                                         key=self.available_at.__getitem__)
                    logger.warning("HTTP 429: la clave pide esperar %.1fs; "
                                   "se usará la clave con índice %s",
                                   wait, self.key_index)
            except openai.APIError as exc:
                # Timeout, lost connection or unreadable reply: the provider
                # may have generated, and we cannot know how much.
                elapsed_ms += (time.monotonic() - started) * 1000
                usage_complete = False
                error = (f"LLM request failed ({type(exc).__name__}); "
                         "token usage is unknown.")
                break
            else:
                duration = (time.monotonic() - started) * 1000
                elapsed_ms += duration
                body = response.model_dump()
                logger.debug("IA RECIBIDO [HTTP 200, cuerpo completo]:\n%s",
                             response.model_dump_json(indent=2))
                logger.info("Respuesta HTTP 200 recibida en %.1f ms", duration)
                generated = True
                reply = self._read_reply(body)
                model_name = reply["model_name"]
                input_tokens += reply["input_tokens"]
                output_tokens += reply["output_tokens"]
                usage_complete = usage_complete and reply["usage_complete"]
                text = reply["text"]
                error = reply["error"]
                if not usage_complete:
                    logger.error("Falta usage: se conserva el subtotal y no "
                                 "se reintenta con consumo desconocido")
                    error = ((error or "Invalid provider usage.")
                             + " Token totals are known subtotals only.")
                    break
                if (input_tokens > max_input_tokens
                        or output_tokens > max_output_tokens):
                    error = ("Provider usage exceeded the remaining token "
                             "budget.")
                    break
                # A 200 without text is a transient failure seen in Gemini:
                # its usage is measured, so retrying hides no consumption.
                if text.strip():
                    break
                self.available_at[self.key_index] = time.monotonic() + 0.5
        if error:
            logger.error("Petición LLM detenida: %s", error)
        logger.debug(
            "Fin de complete: peticiones=%s, entrada=%s, salida=%s, "
            "usage completo=%s",
            requests, input_tokens, output_tokens, usage_complete,
        )
        recoverable = (bool(error) and usage_complete and generated
                       and not text.strip())
        return CompletionResponse(
            text, input_tokens, output_tokens, elapsed_ms, self.config.api_url,
            model_name, max(0, requests - 1), requests, usage_complete, error,
            recoverable,
        )

    def _send(self, messages: list[dict[str, str]], max_output_tokens: int,
              timeout_seconds: float):
        """Send one chat-completions request with the SDK, without retries."""
        logger.debug("Entrando en ProviderClient._send")
        # The SDK's own retries are disabled: complete() counts every attempt.
        client = OpenAI(base_url=self.config.api_url,
                        api_key=self.api_keys[self.key_index],
                        max_retries=0)
        arguments: dict[str, Any] = {
            "model": self.config.model_name, "messages": messages,
            self.config.output_limit_parameter: max_output_tokens,
            "stream": False, "temperature": self.config.temperature,
            "timeout": timeout_seconds,
        }
        extra_body: dict[str, Any] = {}
        if self.config.stop_sequences:
            arguments["stop"] = list(self.config.stop_sequences)
            if "openrouter.ai" in self.config.api_url:
                # Require stop to be honoured only when we use it: several
                # free models do not support it, and asking for it would
                # exclude them from routing.
                extra_body["provider"] = {"require_parameters": True}
        if self.config.reasoning_effort is not None:
            arguments["reasoning_effort"] = self.config.reasoning_effort
        if self.config.reasoning_enabled is not None:
            extra_body["reasoning"] = {"enabled": self.config.reasoning_enabled}
        if extra_body:
            arguments["extra_body"] = extra_body
        logger.debug(
            "Parámetros LLM: temperatura=%s, límite=%s, stop=%s, "
            "razonamiento enabled=%s/effort=%s, timeout=%.2fs",
            self.config.temperature, max_output_tokens,
            self.config.stop_sequences, self.config.reasoning_enabled,
            self.config.reasoning_effort, timeout_seconds,
        )
        return client.chat.completions.create(**arguments)

    def _read_reply(self, body: dict[str, Any]) -> dict[str, Any]:
        """Take text, usage and model from a 200 reply, trusting no field.

        Free providers send incomplete replies: no usage block, no content,
        or tool calls instead of text. Missing token counts are reported, never
        replaced by estimates.
        """
        logger.debug("Entrando en ProviderClient._read_reply")
        usage = body.get("usage") or {}
        counts = [usage.get("prompt_tokens"), usage.get("completion_tokens")]
        usage_complete = all(type(value) is int and value >= 0
                             for value in counts)
        counts = [value if type(value) is int and value >= 0 else 0
                  for value in counts]
        choices = body.get("choices") or [{}]
        message = choices[0].get("message") or {}
        text = message.get("content")
        error = None
        if not isinstance(text, str) or not text.strip():
            text = render_tool_calls(message)
            if text:
                logger.info("Respuesta sin texto pero con tool_calls "
                            "nativos; se traducen")
            else:
                error = "Provider response did not contain text content."
        if not usage_complete:
            error = (error or "") + " Token usage is incomplete."
        # Routers can choose a different model on each request. Preserve what
        # the API actually reports; the configured ID remains the target.
        model_name = body.get("model")
        if not isinstance(model_name, str) or not model_name.strip():
            model_name = self.config.model_name
        logger.debug("Usage: entrada=%s, salida=%s, completo=%s; texto=%s "
                     "caracteres; modelo informado=%s", counts[0], counts[1],
                     usage_complete, len(text), model_name)
        if error:
            logger.warning("Respuesta LLM no utilizable: %s", error)
        return {"text": text, "input_tokens": counts[0],
                "output_tokens": counts[1], "usage_complete": usage_complete,
                "error": error, "model_name": model_name}

    def _hide_keys(self, message: str) -> str:
        """Remove our API keys from a provider message before storing it."""
        for key in self.api_keys:
            message = message.replace(key, "[redacted]")
        return message
