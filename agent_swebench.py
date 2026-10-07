"""Command-line entry point for the SWE-bench agent."""

import argparse
import sys
import time
from pathlib import Path
from typing import Sequence

from agent_smith.io import load_model, write_model
from agent_smith.logging_config import configure_logging, get_logger
from agent_smith.models import SWEBenchTaskInput
from agent_smith.swebench_agent import run_swebench_agent

logger = get_logger('agent_swebench')


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse SWE-bench command-line arguments."""
    logger.debug("Entrando en parse_arguments")
    parser = argparse.ArgumentParser(
        description="Solve one SWE-bench task and write a solution JSON file."
    )
    parser.add_argument(
        "--task-file",
        required=True,
        type=Path,
        help="Path to the SWE-bench task JSON file.",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Path where the solution JSON file will be written.",
    )
    parser.add_argument(
        "--model-name",
        required=True,
        help="Name of the LLM model to use.",
    )
    parser.add_argument(
        "--provider-url",
        required=True,
        help="Base URL of the LLM provider API.",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=30,
        help="Maximum number of agent iterations. Default: 30.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Write the real result, including failed tasks with partial metrics."""
    started_at = time.monotonic()
    configure_logging()
    logger.debug("Entrando en main")
    args = parse_arguments(argv)
    logger.info("Iniciando SWE-bench: leyendo la tarea %s", args.task_file)
    try:
        task = load_model(args.task_file, SWEBenchTaskInput)
        logger.info("Tarea SWE-bench %s validada; iniciando el agente",
                    task.instance_id)
        result = run_swebench_agent(task, args, started_at=started_at)
        write_model(args.output, result)
        logger.info("Resultado guardado en %s; success=%s",
                    args.output, result.success)
        return 0
    except (OSError, ValueError) as exc:
        logger.error("Error: %s", exc)
        return 1
    except KeyboardInterrupt:
        # Ctrl+C: the finally blocks have already closed the worker, MCP and
        # the container; without this the user saw a traceback that looked
        # like a failure.
        print("Interrupted: no solution file was written.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
