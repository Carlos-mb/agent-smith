"""MCP connection configuration and manual generation."""

from __future__ import annotations

from agent_smith.logging_config import LOG_FILE_ENV, LOG_LEVEL_ENV, get_logger

import asyncio
import concurrent.futures
from contextlib import AsyncExitStack
from datetime import timedelta
import json
import keyword
import logging
import builtins
import os
import sys
import threading
import time

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import PaginatedRequestParams

logger = get_logger('agent_smith.mcp_client')


@dataclass
class MCPManual:
    """Store discovered MCP metadata and render the model's tool manual.

    All lists contain JSON-compatible dictionaries supplied by the MCP SDK.
    This object owns no connection and never validates or executes tool calls.
    """

    instructions: str
    tools: list[dict[str, Any]]
    resources: list[dict[str, Any]]
    resource_templates: list[dict[str, Any]]
    prompts: list[dict[str, Any]]

    def as_text(self) -> str:
        """Render instructions, tool parameters, resources, and prompt names.

        Tools are sorted by name; parameter order follows each input schema.
        The sandbox supplies the local final_answer function independently.
        """
        logger.debug("Entrando en MCPManual.as_text")
        logger.debug(
            "Generando manual: herramientas=%s, recursos=%s, plantillas=%s, "
            "prompts=%s",
            len(self.tools), len(self.resources),
            len(self.resource_templates), len(self.prompts),
        )

        lines = []

        if self.instructions:
            lines.append("SERVER INSTRUCTIONS")
            lines.append(self.instructions)
            lines.append("")

        lines.append("TOOLS")

        for tool in sorted(self.tools, key=lambda item: item.get("name", "")):
            name = tool.get("name", "")
            description = tool.get("description", "")
            schema = tool.get("inputSchema", {})
            properties = schema.get("properties", {})
            required = schema.get("required", [])

            lines.append("")
            lines.append("Tool: " + name)

            if description:
                lines.append("Description: " + description)

            lines.append("Parameters:")

            for parameter_name, parameter in properties.items():
                parameter_type = parameter.get("type", "unknown")

                line = "- " + parameter_name + ": " + str(parameter_type)

                if parameter_name in required:
                    line += " (required)"
                else:
                    line += " (optional)"

                if "default" in parameter:
                    line += ", default=" + repr(parameter["default"])

                lines.append(line)
            if (not name.isidentifier() or keyword.iskeyword(name)
                    or hasattr(builtins, name) or name in {
                        "final_answer", "mcp_call_tool", "read_resource",
                        "get_prompt", "__name__",
                    }):
                lines.append(
                    "Call with mcp_call_tool(name, arguments)."
                )

        lines.append("")
        lines.append("RESOURCES")
        lines.append("Use read_resource(uri).")

        for resource in sorted(
            self.resources,
            key=lambda item: item.get("name", ""),
        ):
            lines.append(
                "- "
                + resource.get("name", "")
                + ": "
                + str(resource.get("uri", ""))
            )

        lines.append("")
        lines.append("RESOURCE TEMPLATES")

        for template in sorted(
            self.resource_templates,
            key=lambda item: item.get("name", ""),
        ):
            lines.append(
                "- "
                + template.get("name", "")
                + ": "
                + str(template.get("uriTemplate", ""))
            )

        lines.append("")
        lines.append("PROMPTS")
        lines.append("Use get_prompt(name, arguments).")

        for prompt in sorted(
            self.prompts,
            key=lambda item: item.get("name", ""),
        ):
            lines.append("- " + prompt.get("name", ""))

        lines.append("")
        lines.append(
            "final_answer is provided by the sandbox "
            "and is never replaced by an MCP tool."
        )
        manual = "\n".join(lines)
        logger.debug("Manual MCP generado: %s caracteres", len(manual))
        return manual



class MCPClient:
    """Keep one MCP session open and call it from ordinary synchronous code.

    The MCP SDK only offers async functions. Instead of making the whole agent
    async, this class runs an asyncio event loop in a background thread:

    - one coroutine (_own_session) opens the session, waits until close() is
      called and then closes it, because the SDK must open and close its
      contexts in the same asyncio task;
    - every request (call) is sent to that loop and the caller just waits.
    """

    def __init__(
        self,
        *,
        stdio_command: Sequence[str] | None = None,
        server_url: str | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        """Store which server to use: a stdio command or an HTTP URL."""
        logger.debug("Entrando en MCPClient.__init__")
        self.stdio_command = list(stdio_command) if stdio_command else None
        self.server_url = server_url
        self.environment = dict(environment or {})
        self._loop = None
        self._thread = None
        self._owner = None
        self._session = None
        self._stop = None
        self._closed = threading.Event()
        logger.debug("Configuración MCP preparada: transporte=%s",
                     "stdio" if self.stdio_command else "HTTP")

    def start(self, *, deadline: float | None = None) -> MCPManual:
        """Start the background loop, open the session and discover it."""
        logger.debug("Entrando en MCPClient.start")
        logger.info("Abriendo MCP y solicitando capacidades al servidor")
        timeout = 30.0 if deadline is None else deadline - time.monotonic()
        if timeout <= 0:
            raise TimeoutError("Task expired before MCP startup.")

        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever,
                                        daemon=True)
        self._thread.start()
        self._stop = asyncio.Event()
        self._closed.clear()
        ready = concurrent.futures.Future()
        self._owner = asyncio.run_coroutine_threadsafe(
            self._own_session(ready, timeout), self._loop)
        try:
            return ready.result(timeout=timeout)
        except BaseException as exc:
            logger.error("Fallo al iniciar MCP; cerrando: %s", exc)
            self._owner.cancel()
            self.close()
            if isinstance(exc, concurrent.futures.TimeoutError):
                raise TimeoutError("MCP startup timed out.") from None
            raise

    async def _own_session(self, ready: concurrent.futures.Future,
                           timeout: float) -> None:
        """Open the session, publish the manual, wait for close(), close."""
        logger.debug("Entrando en MCPClient._own_session")
        try:
            async with AsyncExitStack() as stack:
                if self.stdio_command is not None:
                    environment = dict(self.environment)
                    # The server logs like we do, into the same file.
                    for name in (LOG_LEVEL_ENV, LOG_FILE_ENV):
                        environment.setdefault(name,
                                               os.environ.get(name, ""))
                    parameters = StdioServerParameters(
                        command=self.stdio_command[0],
                        args=self.stdio_command[1:], env=environment,
                    )
                    read, write = await stack.enter_async_context(
                        stdio_client(parameters, errlog=sys.stderr))
                else:
                    read, write, _ = await stack.enter_async_context(
                        streamable_http_client(self.server_url))
                session = await stack.enter_async_context(ClientSession(
                    read, write,
                    read_timeout_seconds=timedelta(seconds=timeout),
                ))
                manual = await asyncio.wait_for(_discover(session), timeout)
                self._session = session
                ready.set_result(manual)
                logger.info("MCP conectado y descubrimiento completado")
                await self._stop.wait()
                logger.info("Cerrando sesión y transporte MCP")
        except Exception as exc:
            if not ready.done():
                ready.set_exception(exc)
            else:
                logger.error("La sesión MCP terminó con un error: %s", exc)
        finally:
            self._session = None
            self._closed.set()

    def call(self, operation: str, arguments: dict[str, Any],
             timeout: float | None = None) -> dict[str, Any]:
        """Run one MCP operation and return {"result": ...} or {"error": ...}.

        Tool errors come back as data so the generated code can see them;
        a lost connection raises, because the task cannot continue.
        """
        logger.debug("Entrando en MCPClient.call")
        from mcp.shared.exceptions import McpError

        if self._session is None:
            raise RuntimeError("MCP client is not started.")
        methods = {
            "call_tool": self._session.call_tool,
            "read_resource": self._session.read_resource,
            "get_prompt": self._session.get_prompt,
        }
        if operation not in methods:
            raise ValueError(f"Unknown MCP operation: {operation}")
        logger.info("Ejecutando MCP %s; herramienta/prompt=%s",
                    operation, arguments.get("name", "—"))
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("MCP ENVIADO [%s]:\n%s", operation,
                         json.dumps(arguments, ensure_ascii=False, indent=2))
        future = asyncio.run_coroutine_threadsafe(
            methods[operation](**arguments), self._loop)
        try:
            response = future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            future.cancel()
            raise TimeoutError("MCP request timed out.") from None
        except McpError as exc:
            logger.warning("El SDK MCP devolvió un error: código=%s",
                           exc.error.code)
            if exc.error.code not in (-32601, -32602):
                raise
            return {"error": str(exc)}
        data = response.model_dump(mode="json", by_alias=True)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("MCP RECIBIDO [%s]:\n%s", operation,
                         json.dumps(data, ensure_ascii=False, indent=2))
        if data.get("isError"):
            logger.warning("La herramienta MCP informó un error; se devolverá "
                           "como observación")
            return {"error": json.dumps(data, ensure_ascii=False)}
        # Generated code expects text: a server that returns a dict delivers it
        # here already serialised as JSON.
        content = data.get("content", data.get("contents"))
        if content and len(content) == 1 and "text" in content[0]:
            return {"result": content[0]["text"]}
        return {"result": data}

    def close(self) -> None:
        """Ask the owner coroutine to close the session, then stop the loop."""
        logger.debug("Entrando en MCPClient.close")
        if self._loop is None:
            return
        try:
            self._loop.call_soon_threadsafe(self._stop.set)
            if not self._closed.wait(10):
                logger.warning("MCP no se cerró a tiempo; cancelando")
                self._owner.cancel()
                self._closed.wait(5)
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(5)
            if not self._thread.is_alive():
                self._loop.close()
            self._loop = self._thread = self._owner = self._stop = None
            self._session = None
        logger.debug("Contextos MCP cerrados")


async def _discover(session: ClientSession) -> MCPManual:
    """Initialize the session and list its tools, resources and prompts."""
    logger.debug("Entrando en _discover")
    logger.debug("MCP ENVIADO [initialize]: inicialización mediante el SDK")
    initialized = await session.initialize()
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("MCP RECIBIDO [initialize]:\n%s",
                     initialized.model_dump_json(indent=2, by_alias=True))
    capabilities = initialized.capabilities
    tools, resources, templates, prompts = [], [], [], []
    for capability, method, field, destination in (
        (capabilities.tools, session.list_tools, "tools", tools),
        (capabilities.resources, session.list_resources, "resources",
         resources),
        (capabilities.resources, session.list_resource_templates,
         "resourceTemplates", templates),
        (capabilities.prompts, session.list_prompts, "prompts", prompts),
    ):
        if capability is None:
            logger.debug("El servidor no anuncia la capacidad de %s", field)
            continue
        cursor = None
        while True:
            logger.debug("MCP ENVIADO [listado %s]: cursor=%r", field, cursor)
            page = await method(params=PaginatedRequestParams(cursor=cursor))
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("MCP RECIBIDO [listado %s]:\n%s", field,
                             page.model_dump_json(indent=2, by_alias=True))
            destination.extend(
                item.model_dump(mode="json", by_alias=True)
                for item in getattr(page, field)
            )
            cursor = page.nextCursor
            if not cursor:
                break
        logger.debug("Descubrimiento %s completado: %s elementos",
                     field, len(destination))
    return MCPManual(initialized.instructions or "", tools, resources,
                     templates, prompts)
