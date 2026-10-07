"""Start the sandbox worker process, send it code, and kill it when needed.

This is the agent's side of the sandbox. The generated Python never runs in
the agent process, which holds the API keys: it runs in a separate worker
process (sandbox.worker_main). If a block exceeds its time limit, the whole
worker is killed; no Python code inside it can catch that. A new worker can
then be started, but its variables are lost.
"""

from __future__ import annotations

from agent_smith.logging_config import get_logger

import multiprocessing
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING

from agent_smith.models import SandboxConfig
from agent_smith.sandbox import SandboxExecution, worker_main

if TYPE_CHECKING:
    from agent_smith.mcp_client import MCPClient, MCPManual

logger = get_logger('agent_smith.sandbox_session')

MAX_OUTPUT_CHARACTERS = 12_000


def _dispatch_mcp(client, message: dict, timeout: float | None) -> dict:
    """Ask the MCP client for one operation; no client is an ordinary error."""
    logger.debug("Entrando en _dispatch_mcp")
    if client is None:
        logger.warning("El trabajador pidió MCP sin una sesión conectada")
        return {"type": "mcp_result", "error": "No MCP server is connected."}
    reply = client.call(message["operation"], message["arguments"], timeout)
    logger.debug("Operación MCP completada; devolviendo resultado al "
                 "trabajador")
    return {"type": "mcp_result", **reply}


class SandboxSession:
    """Own one worker process; borrow the MCP client that the caller owns."""

    def __init__(
        self,
        config: SandboxConfig,
        mcp: MCPClient | None = None,
        manual: MCPManual | None = None,
    ) -> None:
        logger.debug("Entrando en SandboxSession.__init__")
        self.config = config.model_copy(deep=True)
        self.mcp = mcp
        self.manual = manual
        self.process = None
        self.connection = None
        self.work_directory = None
        self._temporary = None

    def start(self, timeout: float = 10) -> None:
        """Start the worker in a temporary directory and wait until ready."""
        logger.debug("Entrando en SandboxSession.start")
        logger.info("Arrancando trabajador Python persistente")
        try:
            self._temporary = tempfile.TemporaryDirectory(
                prefix="agent-smith-")
            self.work_directory = Path(self._temporary.name)
            # "spawn" starts a fresh Python interpreter: the worker does not
            # inherit the agent's memory (provider client, MCP thread).
            context = multiprocessing.get_context("spawn")
            self.connection, worker_connection = context.Pipe()
            self.process = context.Process(
                target=worker_main, daemon=True,
                args=(worker_connection, self.config.model_dump(),
                      self.manual.tools if self.manual else [],
                      str(self.work_directory)),
            )
            self.process.start()
            # Only the worker keeps its end open: if it dies, we read EOF.
            worker_connection.close()
            if not self.connection.poll(timeout):
                raise TimeoutError("Worker did not become ready.")
            try:
                self.connection.recv()
            except EOFError:
                raise RuntimeError("the worker exited before it was ready; "
                                   "its error is on stderr") from None
            logger.info("Trabajador listo; pid=%s", self.process.pid)
        except BaseException as exc:
            logger.error("Fallo al iniciar el trabajador: %s", exc)
            self.close()
            if isinstance(exc, Exception):
                raise RuntimeError(f"Sandbox startup failed: {exc}") from exc
            raise

    def execute(
        self, code: str, *, deadline: float | None = None,
    ) -> SandboxExecution:
        """Execute one block, serving its MCP requests, within its time."""
        logger.debug("Entrando en SandboxSession.execute")
        logger.debug("Enviando bloque al trabajador: %s caracteres", len(code))
        result = SandboxExecution()
        output = ""
        omitted = 0
        started = time.monotonic()
        mcp_wait = 0.0

        def remaining():
            # The block limit does not count time spent waiting for MCP tools;
            # the task deadline counts everything.
            now = time.monotonic()
            block = (self.config.max_execution_time_seconds
                     - (now - started - mcp_wait))
            return (min(block, deadline - now) if deadline is not None
                    else block)

        try:
            self.connection.send({"type": "execute", "code": code})
            while True:
                if not self.connection.poll(max(0, remaining())):
                    raise TimeoutError("Execution deadline exceeded.")
                message = self.connection.recv()
                kind = message["type"]
                logger.debug("Mensaje del trabajador: tipo=%s", kind)
                if kind == "output":
                    # Keep the first MAX_OUTPUT_CHARACTERS: every observation
                    # is resent to the model on all following requests.
                    kept = message["text"][:MAX_OUTPUT_CHARACTERS - len(output)]
                    output += kept
                    omitted += len(message["text"]) - len(kept)
                elif kind == "mcp_request":
                    logger.debug("Pausando el reloj del bloque durante la "
                                 "espera MCP; el plazo de tarea continúa")
                    mcp_started = time.monotonic()
                    timeout = (None if deadline is None
                               else max(0, deadline - mcp_started))
                    reply = _dispatch_mcp(self.mcp, message, timeout)
                    self.connection.send(reply)
                    mcp_wait += time.monotonic() - mcp_started
                    logger.debug("MCP terminó; espera MCP acumulada=%.3fs; "
                                 "reanudando reloj del bloque", mcp_wait)
                else:  # "done"
                    result.final_answer = message["final_answer"]
                    result.error = message["error"]
                    if remaining() < 0:
                        raise TimeoutError("Execution deadline exceeded.")
                    break
        except Exception as exc:
            # TimeoutError, or EOFError because the worker died (for example
            # killed by the memory limit): it is closed and its state lost.
            logger.error("Fallo fatal de ejecución; se conservará la salida "
                         "parcial: %s", exc)
            result.timed_out = isinstance(exc, TimeoutError)
            result.worker_failed = True
            result.error = f"{type(exc).__name__}: {exc}"
            if result.timed_out:
                result.error = "Execution timed out; worker state was lost."
            try:
                self.close()
            except Exception as cleanup:
                result.error += f" Cleanup failed: {cleanup}"
        except BaseException:
            logger.warning("Ejecución interrumpida; cerrando el trabajador")
            self.close()
            raise
        result.output = output
        if omitted:
            result.output += (f"\n[Output truncated: {omitted} characters "
                              "omitted.]")
        logger.info(
            "Bloque recibido: error=%s, timeout=%s, trabajador perdido=%s, "
            "final=%s, salida=%s caracteres",
            result.error is not None, result.timed_out, result.worker_failed,
            result.final_answer is not None, len(result.output),
        )
        logger.debug("Salida del bloque:\n%s", result.output)
        return result

    def close(self) -> None:
        """Stop our worker (asking first, then killing) and remove its files."""
        logger.debug("Entrando en SandboxSession.close")
        logger.info("Cerrando trabajador y directorio temporal")
        errors = []
        try:
            if self.connection is not None:
                # EOF: an idle worker leaves its loop and exits by itself.
                self.connection.close()
            if self.process is not None:
                self.process.join(0.5)
                if self.process.is_alive():
                    logger.warning("El trabajador sigue activo; se mata")
                    self.process.kill()
                    self.process.join(1)
                if self.process.is_alive():
                    raise RuntimeError("Worker did not exit after kill.")
                logger.debug("Trabajador recogido; código de salida=%s",
                             self.process.exitcode)
        except Exception as exc:
            logger.error("Fallo al cerrar el trabajador: %s", exc)
            errors.append(str(exc))
        finally:
            self.process = self.connection = None
            if self._temporary is not None:
                try:
                    self._temporary.cleanup()
                    logger.debug("Directorio temporal del trabajador "
                                 "eliminado")
                except Exception as exc:
                    logger.error("No se pudo eliminar el directorio "
                                 "temporal: %s", exc)
                    errors.append(str(exc))
            self._temporary = self.work_directory = None
        if errors:
            raise RuntimeError("Sandbox cleanup failed: " + "; ".join(errors))
        logger.debug("Sandbox cerrado correctamente")
