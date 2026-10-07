import pytest


@pytest.fixture(autouse=True)
def debug_log_file(tmp_path, monkeypatch):
    """Send DEBUG log files to the test's temporary directory, not to logs/."""
    path = tmp_path / "debug.log"
    monkeypatch.setenv("AGENT_SMITH_LOG_FILE", str(path))
    return path
