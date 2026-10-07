"""Opt-in application logging.

AGENT_SMITH_LOG_LEVEL chooses the level; unset or empty means silence. Logs
go to stderr, never stdout, which the MCP stdio transport uses.

With DEBUG, the same records are also appended to a log file, so a whole run
can be read afterwards: functions entered, decisions taken, connections,
every message sent to and received from the LLM, the sandbox and MCP. The
file is AGENT_SMITH_LOG_FILE if set, otherwise logs/agent_smith_<time>.log.
Its name is saved in the environment, so the sandbox worker and the MCP
server started afterwards write to the same file.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from typing import Iterable


LOG_LEVEL_ENV = "AGENT_SMITH_LOG_LEVEL"
LOG_FILE_ENV = "AGENT_SMITH_LOG_FILE"
_LEVELS = {name: getattr(logging, name) for name in (
    "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL",
)}
_secrets: set[str] = set()
_configured = False


def register_secrets(values: Iterable[str]) -> None:
    """Hide provider keys even if an error or response echoes them."""
    _secrets.update(value for value in values if value)


class _ApplicationFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # SDK debug logs can contain HTTP headers or raw protocol payloads.
        return (record.name == "agent_smith"
                or record.name.startswith("agent_smith."))


class _SecretFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        for secret in sorted(_secrets, key=len, reverse=True):
            text = text.replace(secret, "[REDACTED]")
        return text


def configure_logging() -> None:
    """Read the environment again at each entry point; no duplicate handlers.

    Empty/unset means silence. Invalid nonempty values enable ERROR and report
    the configuration mistake. This module does not log its own helper calls:
    doing so would recurse while formatting or configuring a log record.
    """
    global _configured
    requested = os.environ.get(LOG_LEVEL_ENV, "").strip().upper()
    level = (_LEVELS.get(requested, logging.ERROR) if requested
             else logging.CRITICAL + 1)
    register_secrets(os.environ.get(name, "") for name in (
        "PROVIDER_API_KEY", "PROVIDER_API_KEY_2", "OPENROUTER_API_KEY",
        "OPENROUTER_API_KEY_2", "GEMINI_API_KEY", "GEMINI_API_KEY_2",
    ))
    handlers = [logging.StreamHandler(sys.stderr)]
    if level == logging.DEBUG:
        if not os.environ.get(LOG_FILE_ENV):
            os.environ[LOG_FILE_ENV] = os.path.abspath(os.path.join(
                "logs", time.strftime("agent_smith_%Y%m%d_%H%M%S.log")))
        path = os.environ[LOG_FILE_ENV]
        os.makedirs(os.path.dirname(path), exist_ok=True)
        handlers.append(logging.FileHandler(path, encoding="utf-8"))
    for handler in handlers:
        handler.setLevel(level)
        handler.addFilter(_ApplicationFilter())
        handler.setFormatter(_SecretFormatter(
            "%(asctime)s %(levelname)s [pid=%(process)d] "
            "%(name)s.%(funcName)s:%(lineno)d | %(message)s",
            datefmt="%H:%M:%S",
        ))
    logging.basicConfig(level=level, handlers=handlers, force=True)
    logging.getLogger("agent_smith").setLevel(level)
    # Application messages describe these operations without exposing SDK
    # internals.
    for name in ("openai", "httpx", "httpcore", "docker", "urllib3", "mcp",
                 "asyncio"):
        logging.getLogger(name).setLevel(logging.CRITICAL + 1)
    logging.raiseExceptions = False
    _configured = True
    if requested and requested not in _LEVELS:
        logging.getLogger("agent_smith.logging_config").error(
            "%s not valid; using ERROR. Values: DEBUG, INFO, WARNING, ERROR, "
            "CRITICAL.",
            LOG_LEVEL_ENV,
        )


def get_logger(name: str) -> logging.Logger:
    """Give every project module a logger under the application namespace."""
    if not _configured:
        configure_logging()
    if not name.startswith("agent_smith.") and name != "agent_smith":
        name = "agent_smith." + name
    return logging.getLogger(name)
