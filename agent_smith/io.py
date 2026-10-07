"""Read and write the JSON files of the project as Pydantic models."""

from agent_smith.logging_config import get_logger

from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

logger = get_logger('agent_smith.io')


ModelType = TypeVar("ModelType", bound=BaseModel)


def load_model(path: str | Path, model_class: type[ModelType]) -> ModelType:
    """Read a JSON file and validate it with a Pydantic model.

    A missing or unreadable file raises OSError; invalid JSON or fields that
    do not match the model raise pydantic's ValidationError, a ValueError.
    """
    logger.debug("Entrando en load_model")
    logger.debug("Leyendo %s desde %s", model_class.__name__, path)
    return model_class.model_validate_json(
        Path(path).read_text(encoding="utf-8"))


def write_model(path: str | Path, model: BaseModel) -> None:
    """Write a Pydantic model as indented JSON, creating the folder if needed."""
    logger.debug("Entrando en write_model")
    file_path = Path(path)
    logger.debug("Escribiendo %s en %s", type(model).__name__, file_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(model.model_dump_json(indent=2) + "\n",
                         encoding="utf-8")
