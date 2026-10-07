"""Contract tests for sandbox configuration loading, which is still pending."""

import pytest

from agent_smith.models import SandboxConfig
from agent_smith.sandbox import load_sandbox_config


def test_load_sandbox_config_uses_defaults_when_path_is_none():
    config = load_sandbox_config(None)

    assert config == SandboxConfig()


def test_load_sandbox_config_preserves_empty_allowed_directories(tmp_path):
    config_path = tmp_path / "sandbox.json"
    config_path.write_text(
        '{"allowed_directories": []}',
        encoding="utf-8",
    )

    config = load_sandbox_config(config_path)

    assert config.allowed_directories == []

def test_load_sandbox_config_loads_custom_values(tmp_path):
    config_path = tmp_path / "sandbox.json"
    config_path.write_text(
        """
        {
            "authorized_imports": ["math"],
            "allowed_directories": ["/tmp/test"],
            "max_execution_time_seconds": 10,
            "max_memory_mb": 128
        }
        """,
        encoding="utf-8",
    )

    config = load_sandbox_config(config_path)

    assert config.authorized_imports == ["math"]
    assert config.allowed_directories == ["/tmp/test"]
    assert config.max_execution_time_seconds == 10
    assert config.max_memory_mb == 128


def test_load_sandbox_config_rejects_zero_execution_time(tmp_path):
    config_path = tmp_path / "sandbox.json"
    config_path.write_text(
        '{"max_execution_time_seconds": 0}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="max_execution_time_seconds"):
        load_sandbox_config(config_path)


def test_load_sandbox_config_rejects_negative_memory(tmp_path):
    config_path = tmp_path / "sandbox.json"
    config_path.write_text(
        '{"max_memory_mb": -1}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="max_memory_mb"):
        load_sandbox_config(config_path)


def test_load_sandbox_config_handles_missing_file(tmp_path):
    config_path = tmp_path / "does_not_exist.json"

    with pytest.raises(OSError):
        load_sandbox_config(config_path)


def test_load_sandbox_config_handles_invalid_json(tmp_path):
    config_path = tmp_path / "sandbox.json"
    config_path.write_text(
        "not json",
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        load_sandbox_config(config_path)


def test_load_sandbox_config_handles_invalid_type(tmp_path):
    config_path = tmp_path / "sandbox.json"
    config_path.write_text(
        '{"max_memory_mb": "not-a-number"}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        load_sandbox_config(config_path)
