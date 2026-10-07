"""One sequential Thought -> Code -> Observation loop for both benchmarks."""

from __future__ import annotations

from agent_smith.logging_config import get_logger

import time

from agent_smith.code_extraction import extract_agent_code
from agent_smith.models import AgentLimits, SolutionOutput, StepMetrics
from agent_smith.providers import ProviderClient
from agent_smith.sandbox import SandboxExecution
from agent_smith.sandbox_session import SandboxSession

logger = get_logger('agent_smith.agent_loop')


MINIMUM_HISTORY_MESSAGES = 6


def _message_tokens(message: dict[str, str]) -> int:
    """Approximate one message as the provider estimates a request."""
    return (len(message["content"].encode("utf-8")) + 3) // 4 + 8


def trim_history(
    messages: list[dict[str, str]], budget_tokens: int,
) -> list[dict[str, str]]:
    """Keep the system prompt, the task, and as many recent exchanges as fit.

    The whole list is resent on every request, so keeping all of it grows
    quadratically: one run spent 296,410 of its 300,000 input tokens. A fixed
    window does not work either: with three pairs the model forgot it had
    already edited a file and re-read the same ranges 22 times. So the size
    is set by the remaining budget divided among the remaining iterations,
    or by the model's max_input_per_request if that is smaller.
    MINIMUM_HISTORY_MESSAGES are always sent even if they do not fit:
    without the latest exchanges the model cannot continue.
    """
    logger.debug("Entrando en trim_history")
    head, rest = messages[:2], messages[2:]
    used = sum(_message_tokens(message) for message in head)
    kept: list[dict[str, str]] = []
    for message in reversed(rest):
        used += _message_tokens(message)
        if used > budget_tokens and len(kept) >= MINIMUM_HISTORY_MESSAGES:
            break
        kept.append(message)
    kept.reverse()
    if len(kept) < len(rest):
        logger.info(
            "Recortando historial a %s mensajes de %s; presupuesto=%s tokens",
            len(head) + len(kept), len(messages), budget_tokens,
        )
    return head + kept


def build_observation(
    execution: SandboxExecution | None,
    extraction_feedback: str,
) -> str:
    """Build the observation returned to the LLM."""
    logger.debug("Entrando en build_observation")

    if execution is None:
        return extraction_feedback

    parts = []

    if extraction_feedback:
        parts.append(extraction_feedback)

    if execution.output:
        parts.append(execution.output)

    if execution.error:
        parts.append("Error: " + execution.error)

    if execution.timed_out:
        parts.append(
            "Timeout. Execution timed out. Output may be partial."
        )

    if execution.final_answer is not None:
        parts.append("Final answer:\n" + execution.final_answer)

    if not parts:
        # A block that printed nothing left the observation empty, and the
        # model repeated the same call without understanding why it saw no
        # result.
        parts.append("The block ran without errors and printed nothing.")

    return "\n".join(parts)


def run_agent_loop(
    *,
    task_id: str,
    benchmark: str,
    system_prompt: str,
    task_prompt: str,
    provider: ProviderClient,
    sandbox: SandboxSession,
    limits: AgentLimits,
    started_at: float,
    deadline: float | None = None,
) -> SolutionOutput:
    """Borrow resources; own counters and preserve every completed request."""
    logger.debug("Entrando en run_agent_loop")
    logger.info("Inicio del bucle: benchmark=%s, tarea=%s", benchmark, task_id)
    logger.debug("Prompt del sistema:\n%s", system_prompt)
    logger.debug("Prompt de la tarea:\n%s", task_prompt)
    task_deadline = started_at + limits.max_time_seconds
    deadline = (min(deadline, task_deadline) if deadline is not None
                else task_deadline)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": task_prompt},
    ]
    steps = []
    requests = input_tokens = output_tokens = 0
    solution = ""
    success = False
    error = None
    step = None

    tool_names = ["final_answer"]
    if sandbox.manual:
        for tool in sandbox.manual.tools:
            tool_names.append(tool["name"])
    logger.debug("Nombres que el extractor reconoce como llamadas: %s",
                 tool_names)

    try:
        for number in range(1, limits.max_iterations + 1):
            logger.info(
                "Iteración %s/%s; tokens restantes entrada=%s/salida=%s; "
                "tiempo restante=%.2fs",
                number, limits.max_iterations,
                limits.max_input_tokens - input_tokens,
                limits.max_output_tokens - output_tokens,
                deadline - time.monotonic(),
            )
            if time.monotonic() >= deadline:
                error = "Task execution deadline reached."
                break
            if (input_tokens >= limits.max_input_tokens
                    or output_tokens >= limits.max_output_tokens):
                error = "Task token budget exhausted."
                break
            # Share the remaining input budget among the remaining iterations.
            share = ((limits.max_input_tokens - input_tokens)
                     // (limits.max_iterations - number + 1))

            # Groq's free tier refuses any Qwen request above 7,000 input
            # tokens (HTTP 413), however long we wait: cap each request.
            if (provider.config.max_input_per_request and
                share > provider.config.max_input_per_request):
                logger.info("Iteración %s: presupuesto del historial %s "
                            "limitado al tope por petición del modelo (%s)",
                            number, share,
                            provider.config.max_input_per_request)
                share = provider.config.max_input_per_request

            completion = provider.complete(
                trim_history(messages, share),
                max_input_tokens=limits.max_input_tokens - input_tokens,
                max_output_tokens=limits.max_output_tokens - output_tokens,
                deadline=deadline,
            )
            requests += completion.request_count
            input_tokens += completion.input_tokens
            output_tokens += completion.output_tokens
            logger.debug(
                "Acumulados tras LLM: peticiones=%s, entrada=%s, salida=%s, "
                "usage completo=%s",
                requests, input_tokens, output_tokens,
                completion.usage_complete,
            )
            logger.debug("Respuesta del modelo:\n%s", completion.text)
            if completion.request_count == 0:
                error = completion.error or "No LLM request was made."
                break
            step = StepMetrics(
                step=number, input_tokens=completion.input_tokens,
                output_tokens=completion.output_tokens,
                request_time_ms=completion.request_time_ms,
                api_url=completion.api_url, model_name=completion.model_name,
                llm_output=completion.text, retries=completion.retries,
            )
            steps.append(step)
            error = completion.error
            if (not completion.usage_complete
                    and "known subtotals" not in (error or "")):
                error = ((error or "")
                         + " Token totals are known subtotals only.")
            if (input_tokens > limits.max_input_tokens
                    or output_tokens > limits.max_output_tokens):
                error = "Cumulative token limit exceeded."
            if time.monotonic() >= deadline:
                error = ((error + " " if error else "")
                         + "Task execution deadline reached.")
            if error and not completion.recoverable:
                logger.error("Iteración %s detenida antes de ejecutar "
                             "código: %s", number, error)
                step.sandbox_output = error
                break
            if error:
                # The model said nothing usable, but its usage is measured:
                # return it as an observation instead of ending the task.
                logger.warning("Iteración %s sin respuesta utilizable: %s",
                               number, error)
                step.sandbox_output = error
                messages.append({"role": "user",
                                 "content": "Observation:\n" + error})
                continue
            code, feedback = extract_agent_code(completion.text, tool_names)
            execution = None
            if code:
                logger.info("Iteración %s: ejecutando el bloque Python "
                            "extraído", number)
                logger.debug("Código que se ejecutará:\n%s", code)
                step.sandbox_input = code
                execution = sandbox.execute(code, deadline=deadline)
            else:
                logger.warning("Iteración %s sin código ejecutable: %s",
                               number, feedback)
                feedback += (
                    "\nNothing was executed. Resend all code in one "
                    "complete, concise Python block; do not describe the "
                    "delimiters."
                )
            observation = build_observation(execution, feedback)
            logger.debug("Observación real de la iteración %s:\n%s",
                         number, observation)
            step.sandbox_output = observation
            messages.append({"role": "assistant", "content": completion.text})
            messages.append({"role": "user",
                             "content": "Observation:\n" + observation})
            logger.debug("Observación añadida al historial; mensajes=%s",
                         len(messages))
            if execution is not None and execution.final_answer is not None:
                solution = execution.final_answer
            if time.monotonic() > deadline:
                error = "Task execution deadline reached."
                break
            if execution is not None:
                if execution.worker_failed:
                    error = execution.error or "Sandbox worker failed."
                    break
                if execution.final_answer is not None:
                    if execution.error or execution.timed_out:
                        error = execution.error or "Execution timed out."
                    elif not solution.strip():
                        error = "The final answer is empty."
                    else:
                        success = True
                        logger.info("final_answer recibido; el bucle ha "
                                    "finalizado con una solución")
                    break
        else:
            error = "Iteration limit reached without final_answer."
    except Exception as exc:
        logger.exception("Fallo inesperado del bucle; se conservarán los "
                         "pasos parciales")
        error = f"{type(exc).__name__}: {exc}"
        if step is not None:
            step.sandbox_output += "\nError: " + error
    if error:
        logger.error("Bucle terminado sin éxito: %s", error)
    logger.info(
        "Fin del bucle: success=%s, iteraciones=%s, peticiones=%s, "
        "tokens=%s/%s",
        success, len(steps), requests, input_tokens, output_tokens,
    )
    return SolutionOutput(
        task_id=task_id, benchmark=benchmark, success=success,
        solution=solution, system_prompt=system_prompt,
        iterations=len(steps), total_requests=requests,
        total_input_tokens=input_tokens, total_output_tokens=output_tokens,
        total_time_seconds=time.monotonic() - started_at, steps=steps,
        error=error,
    )
