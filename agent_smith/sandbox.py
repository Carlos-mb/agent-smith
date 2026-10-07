"""Everything that runs inside the sandbox worker process.

The agent never executes generated Python itself. SandboxSession
(sandbox_session.py) starts a separate worker process that runs worker_main.
Inside that process this module applies the controls (allowed imports, allowed
directories, safe builtins, memory limit, no network) and runs each block in
one shared namespace, so variables persist between blocks.

The worker and the agent talk through a multiprocessing Pipe, sending plain
Python dicts:

    agent  -> worker   {"type": "execute", "code": ...}
    worker -> agent    {"type": "ready"}                    set up, waiting for code
    worker -> agent    {"type": "output", "text": ...}      what the code prints
    worker -> agent    {"type": "mcp_request", ...}          the code called a tool
    agent  -> worker   {"type": "mcp_result", ...}          the tool's answer
    worker -> agent    {"type": "done", ...}                block finished

These controls do not resist hostile Python introspection.
"""

from __future__ import annotations

from agent_smith.logging_config import (
    LOG_FILE_ENV, LOG_LEVEL_ENV, configure_logging, get_logger,
)

import ast
import builtins
import importlib
import keyword
import os
import signal
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

from agent_smith.io import load_model
from agent_smith.models import SandboxConfig

logger = get_logger('agent_smith.sandbox')


@dataclass
class SandboxExecution:
    """Carry one block's output, final answer, and execution status.

    Output may be partial or truncated. A final answer is kept in full.
    worker_failed distinguishes a lost process from an ordinary Python error.
    """

    output: str = ""
    final_answer: str | None = None
    error: str | None = None
    timed_out: bool = False
    worker_failed: bool = False


class FinalAnswerSignal(Exception):
    """Stop the current block and carry the answer in the exception argument.

    An ordinary Exception, not a BaseException: a whole file piped into the
    sandbox is one block, so a final_answer inside it must stay catchable and
    let the rest of the file run. execute_block catches it before any generic
    handler, so the answer is never mistaken for a failure.
    """


def final_answer(answer: str) -> None:
    """Stop execution and carry the complete final answer."""
    logger.debug("Entrando en final_answer")
    if not isinstance(answer, str):
        logger.warning("final_answer rechazado: la respuesta debe ser texto")
        raise TypeError("Final answer must be a string.")

    logger.info("Solicitud local de finalización: %s caracteres", len(answer))
    raise FinalAnswerSignal(answer)


def load_sandbox_config(path: str | Path | None) -> SandboxConfig:
    """Load sandbox settings from a JSON file, or use the defaults."""
    logger.debug("Entrando en load_sandbox_config")
    return SandboxConfig() if path is None else load_model(path, SandboxConfig)


def _is_import_allowed(module_name, patterns):
    """Check exact module names and patterns ending in .*."""
    logger.debug("Entrando en _is_import_allowed")
    if module_name.startswith("."):
        return False

    for pattern in patterns:
        if module_name == pattern:
            logger.debug("Import permitido por coincidencia exacta: %s",
                         module_name)
            return True

        if pattern.endswith(".*"):
            prefix = pattern[:-1]
            if module_name.startswith(prefix):
                logger.debug("Import permitido por patrón: %s", module_name)
                return True

    logger.debug("Import no autorizado: %s", module_name)
    return False


def _make_safe_import(authorized_imports):
    """Create an importer that checks the configured allowlist."""
    logger.debug("Entrando en _make_safe_import")
    allowed_imports = tuple(authorized_imports)

    def restricted_import(
        name, globals=None, locals=None, fromlist=(), level=0
    ):
        """Reject disallowed modules before delegating to Python's importer."""
        logger.debug("Entrando en _make_safe_import.restricted_import")
        logger.debug("Solicitado import %s; nivel relativo=%s; fromlist=%s",
                     name, level, fromlist)
        if level != 0:
            raise ImportError("Relative imports are not allowed.")

        if not _is_import_allowed(name, allowed_imports):
            raise ImportError(f"Import not allowed: {name}")

        if fromlist:
            if "*" in fromlist:
                raise ImportError("Use explicit names instead of import *.")

            # Load the allowed module without processing fromlist yet.
            module = importlib.import_module(name)
            attributes = vars(module)

            for item in fromlist:
                value = attributes.get(item)

                if isinstance(value, ModuleType):
                    module_name = value.__name__
                elif item not in attributes:
                    module_name = f"{name}.{item}"
                else:
                    continue

                if not _is_import_allowed(module_name, allowed_imports):
                    raise ImportError(f"Import not allowed: {module_name}")

        return builtins.__import__(name, globals, locals, fromlist, level)

    return restricted_import


def _resolve_allowed_path(
        path: str | Path,
        allowed_directories: list[Path],
        ) -> Path:
    """Resolve a path and require membership in an allowed directory."""
    logger.debug("Entrando en _resolve_allowed_path")
    candidate = Path(path).resolve(strict=False)
    logger.debug("Comprobando pertenencia de la ruta resuelta: %s", candidate)

    for directory in allowed_directories:
        root = directory.resolve(strict=False)
        if candidate.is_relative_to(root):
            logger.debug("Ruta autorizada dentro de %s", root)
            return candidate

    logger.warning("Acceso a archivo rechazado: ruta fuera de los "
                   "directorios permitidos")
    raise PermissionError(f"Filesystem access denied by sandbox: {candidate}")


def _make_safe_open(allowed_directories: list[str]) -> Callable[..., Any]:
    """Create a file opener restricted to allowed directories."""
    logger.debug("Entrando en _make_safe_open")
    allowed_paths = [
        Path(directory).resolve(strict=False)
        for directory in allowed_directories
    ]

    def restricted_open(
        file, mode="r", buffering=-1, encoding=None, errors=None,
        newline=None, closefd=True, opener=None,
    ):
        """Check access before opening the resolved path."""
        logger.debug("Entrando en _make_safe_open.restricted_open")
        if opener is not None:
            raise ValueError("Custom openers are not allowed.")

        if closefd is not True:
            raise ValueError("closefd must be True.")

        path = _resolve_allowed_path(file, allowed_paths)
        logger.debug("Abriendo archivo autorizado %s con modo %s", path, mode)

        return builtins.open(
            path,
            mode=mode,
            buffering=buffering,
            encoding=encoding,
            errors=errors,
            newline=newline,
        )

    return restricted_open


def _make_safe_builtins(config: SandboxConfig) -> dict[str, Any]:
    """Build the allowed builtins and attach restricted import and open."""
    logger.debug("Entrando en _make_safe_builtins")
    names = [
        "print", "len", "range", "enumerate", "zip",
        "iter", "next", "map", "filter",
        "sum", "min", "max", "sorted", "reversed",
        "abs", "round", "pow", "divmod", "all", "any",
        "int", "float", "bool", "str", "bytes",
        "list", "tuple", "dict", "set", "frozenset",
        "chr", "ord", "repr", "dir",
        "object", "isinstance", "issubclass", "type",
        "super", "property", "staticmethod", "classmethod",
        "__build_class__",
        "Exception", "AssertionError", "ValueError", "TypeError",
        "KeyError", "IndexError", "AttributeError", "NameError",
        "RuntimeError", "NotImplementedError", "StopIteration",
        "ZeroDivisionError", "ImportError", "OSError",
        "FileNotFoundError", "PermissionError",
        "MemoryError", "TimeoutError", "KeyboardInterrupt", "SystemExit",
    ]

    safe = {name: getattr(builtins, name) for name in names}
    safe["__import__"] = _make_safe_import(config.authorized_imports)
    safe["open"] = _make_safe_open(config.allowed_directories)

    logger.debug("Builtins preparados: %s nombres; import y open "
                 "controlados", len(safe))
    return safe


def _apply_worker_limits(config: SandboxConfig) -> None:
    """Set memory limits and disable socket entry points in the worker."""
    logger.debug("Entrando en _apply_worker_limits")
    import resource
    import socket

    memory = config.max_memory_mb * 1024 * 1024
    _, hard = resource.getrlimit(resource.RLIMIT_AS)
    if hard != resource.RLIM_INFINITY:
        memory = min(memory, hard)
    resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
    logger.info("Límite de memoria del trabajador aplicado: %s bytes de "
                "espacio virtual", memory)

    def reject_network(*args, **kwargs):
        logger.debug("Entrando en _apply_worker_limits.reject_network")
        logger.warning("Acceso de red del trabajador rechazado")
        raise PermissionError("Network access is disabled in the sandbox.")

    for name in (
        "socket", "create_connection", "create_server", "socketpair", "fromfd",
        "getaddrinfo", "gethostbyname", "gethostbyname_ex", "gethostbyaddr",
        "getnameinfo",
    ):
        if hasattr(socket, name):
            setattr(socket, name, reject_network)
    logger.debug("Vías de red expuestas deshabilitadas en el trabajador")


class WorkerOutput:
    """File-like object for print(): send every write to the agent at once.

    Sending immediately keeps the output that was printed before a timeout:
    the agent already has it when it kills the worker. The agent, not the
    worker, decides how much of it to keep.
    """

    def __init__(self, connection) -> None:
        self.connection = connection

    def write(self, text: str) -> int:
        if text:
            self.connection.send({"type": "output", "text": text})
        return len(text)

    def flush(self) -> None:
        """Nothing to flush: every write is sent immediately."""


def _request_mcp(connection, operation: str,
                 arguments: dict[str, Any]) -> Any:
    """Ask the agent to run one MCP operation and wait for its reply."""
    logger.debug("Entrando en _request_mcp")
    logger.info("Solicitando operación MCP %s al agente", operation)
    connection.send({
        "type": "mcp_request", "operation": operation, "arguments": arguments,
    })
    reply = connection.recv()
    if reply.get("error") is not None:
        logger.warning("La operación MCP devolvió un error; "
                       "se entregará al código")
        raise RuntimeError(reply["error"])
    logger.debug("Resultado MCP recibido; reanudando el bloque Python")
    return reply["result"]


def _make_tool_wrapper(tool: dict[str, Any], connection) -> Callable[..., Any]:
    """Build the local Python function that calls one discovered MCP tool."""
    logger.debug("Entrando en _make_tool_wrapper")
    name = tool["name"]
    parameters = list(tool.get("inputSchema", {}).get("properties", {}))

    def tool_wrapper(*args, **kwargs):
        logger.debug("Llamada a herramienta descubierta: %s", name)
        if len(args) > len(parameters):
            raise TypeError(f"Too many positional arguments for {name}.")
        arguments = dict(zip(parameters, args))
        if arguments.keys() & kwargs.keys():
            raise TypeError(f"Duplicate arguments for {name}.")
        arguments.update(kwargs)
        return _request_mcp(connection, "call_tool", {
            "name": name, "arguments": arguments,
        })

    return tool_wrapper


def _build_namespace(config: SandboxConfig, tools: list[dict[str, Any]],
                     connection) -> dict[str, Any]:
    """Prepare persistent user globals with safe builtins and MCP wrappers."""
    logger.debug("Entrando en _build_namespace")
    safe = _make_safe_builtins(config)

    def mcp_call_tool(name, arguments=None):
        return _request_mcp(connection, "call_tool", {
            "name": name,
            "arguments": arguments if arguments is not None else {},
        })

    def read_resource(uri):
        return _request_mcp(connection, "read_resource", {"uri": uri})

    def get_prompt(name, arguments=None):
        return _request_mcp(connection, "get_prompt", {
            "name": name,
            "arguments": arguments if arguments is not None else {},
        })

    namespace = {
        "__builtins__": safe, "__name__": "__sandbox__",
        "final_answer": final_answer, "mcp_call_tool": mcp_call_tool,
        "read_resource": read_resource, "get_prompt": get_prompt,
    }
    for tool in tools:
        name = tool["name"]
        if (name.isidentifier() and not keyword.iskeyword(name)
                and name not in safe and name not in namespace):
            namespace[name] = _make_tool_wrapper(tool, connection)
            logger.debug("Función local MCP registrada: %s", name)
        else:
            logger.debug("Herramienta %s disponible mediante mcp_call_tool; "
                         "nombre reservado o no válido", name)
    logger.debug("Namespace persistente preparado; entradas=%s",
                 len(namespace))
    return namespace


def execute_block(code: str, namespace: dict[str, Any], connection) -> None:
    """Execute code in the shared namespace and send its result."""
    logger.debug("Entrando en execute_block")
    logger.info("Ejecutando bloque Python en el namespace persistente: "
                "%s caracteres", len(code))
    logger.debug("Código recibido del agente:\n%s", code)
    output = WorkerOutput(connection)
    answer = None
    error = None

    try:
        with redirect_stdout(output), redirect_stderr(output):
            parsed = ast.parse(code)
            # As in the Python REPL: if the block ends with an expression,
            # print its value. The models call tools without print, and
            # without this the observation came back empty and they looped.
            trailing = None
            if parsed.body and isinstance(parsed.body[-1], ast.Expr):
                trailing = parsed.body.pop().value
            exec(compile(parsed, "<sandbox>", "exec"), namespace, namespace)
            if trailing is not None:
                value = eval(
                    compile(ast.Expression(trailing), "<sandbox>", "eval"),
                    namespace, namespace,
                )
                if value is not None:
                    print(value)

    except FinalAnswerSignal as exc:
        answer = exc.args[0]
        logger.info("final_answer capturado: %s caracteres", len(answer))

    except BaseException as exc:
        # Any error, including a SystemExit or KeyboardInterrupt raised by the
        # generated code, is just an observation: the worker keeps running.
        error = f"{type(exc).__name__}: {exc}"
        logger.warning("Bloque Python fallido: %s; se enviará una "
                       "observación", error)

    connection.send({"type": "done", "final_answer": answer, "error": error})
    logger.info("Bloque terminado: error=%s, respuesta final=%s",
                error is not None, answer is not None)


def worker_main(connection, config_data: dict[str, Any],
                tools: list[dict[str, Any]], work_directory: str) -> None:
    """Body of the worker process: set up once, then run blocks until EOF.

    If the setup fails, the exception ends the process with its traceback on
    stderr, and the agent sees the worker exit before saying it is ready.
    """
    # The agent handles Ctrl+C and then kills this process.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    # The inherited environment holds the API keys: the generated code must
    # not see them. Only the logging settings survive.
    kept = {name: os.environ[name] for name in (LOG_LEVEL_ENV, LOG_FILE_ENV)
            if name in os.environ}
    os.environ.clear()
    os.environ.update(kept)
    os.chdir(work_directory)
    configure_logging()
    logger.debug("Entrando en worker_main")
    logger.info("Trabajador iniciado; pid=%s, directorio=%s",
                os.getpid(), work_directory)
    config = SandboxConfig.model_validate(config_data)
    _apply_worker_limits(config)
    namespace = _build_namespace(config, tools, connection)
    connection.send({"type": "ready"})
    logger.info("Trabajador listo para recibir bloques consecutivos")
    while True:
        try:
            message = connection.recv()
        except EOFError:
            logger.info("El agente cerró la conexión; fin del trabajador")
            return
        execute_block(message["code"], namespace, connection)
