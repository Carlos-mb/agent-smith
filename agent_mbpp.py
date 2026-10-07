"""Command-line entry point for the MBPP agent."""

import argparse
import time
from pathlib import Path
from typing import Sequence

from agent_smith.io import load_model, write_model
from agent_smith.logging_config import configure_logging, get_logger
from agent_smith.mbpp_agent import run_mbpp_agent
from agent_smith.models import MBPPTaskInput

logger = get_logger('agent_mbpp')


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse MBPP command-line arguments."""
    logger.debug("Entrando en parse_arguments")
    parser = argparse.ArgumentParser(
        description="Solve one MBPP task and write a solution JSON file."
    )
    parser.add_argument(
        "--task-file",
        required=True,
        type=Path,
        help="Path to the MBPP task JSON file.",
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
        default=10,
        help="Maximum number of agent iterations. Default: 10.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Write the real result, including failed tasks with partial metrics."""
    started_at = time.monotonic()
    configure_logging()
    logger.debug("Entrando en main")
    args = parse_arguments(argv)
    logger.info("Starting MBPP: reading task %s", args.task_file)
    try:
        task = load_model(args.task_file, MBPPTaskInput)
        logger.info("Tarea MBPP %s validada; iniciando el agente",
                    task.task_id)
        result = run_mbpp_agent(task, args, started_at=started_at)
        write_model(args.output, result)
        logger.info("Resultado guardado en %s; success=%s",
                    args.output, result.success)
        return 0
    except (OSError, ValueError) as exc:
        logger.error("Error: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
