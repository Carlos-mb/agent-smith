"""Tests for file access through the sandbox opener, using temporary files."""

import builtins

import pytest

from agent_smith.sandbox import _make_safe_open, _resolve_allowed_path


def test_read_allowed_file(tmp_path):
    path = tmp_path / "data.txt"
    path.write_text("hello", encoding="utf-8")
    safe_open = _make_safe_open([str(tmp_path)])

    with safe_open(str(path), encoding="utf-8") as file:
        assert file.read() == "hello"


def test_write_allowed_file(tmp_path):
    path = tmp_path / "new.txt"
    safe_open = _make_safe_open([str(tmp_path)])

    with safe_open(path, "w", encoding="utf-8") as file:
        file.write("hello")

    assert path.read_text(encoding="utf-8") == "hello"


def test_relative_path_with_parent_inside_allowed_directory(tmp_path, monkeypatch):
    (tmp_path / "subdir").mkdir()
    path = tmp_path / "data.txt"
    path.write_text("hello", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    safe_open = _make_safe_open(["."])

    resolved = _resolve_allowed_path("subdir/../data.txt", [tmp_path])
    assert resolved == path.resolve()

    with safe_open("subdir/../data.txt", encoding="utf-8") as file:
        assert file.read() == "hello"


@pytest.mark.parametrize("mode", ["r", "w"])
def test_parent_escape_is_denied(tmp_path, mode):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("keep", encoding="utf-8")
    safe_open = _make_safe_open([str(allowed)])

    with pytest.raises(PermissionError):
        with safe_open(allowed / ".." / "outside.txt", mode):
            pytest.fail("Access outside the allowed directory succeeded.")

    assert outside.read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize("mode", ["r", "w"])
def test_symlink_escape_is_denied(tmp_path, mode):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("keep", encoding="utf-8")
    link = allowed / "link.txt"
    link.symlink_to(outside)
    safe_open = _make_safe_open([str(allowed)])

    with pytest.raises(PermissionError):
        with safe_open(link, mode):
            pytest.fail("Access through an outside symlink succeeded.")

    assert outside.read_text(encoding="utf-8") == "keep"


def test_similar_directory_prefix_is_denied(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    other = tmp_path / "allowed_extra"
    other.mkdir()
    path = other / "data.txt"
    path.write_text("outside", encoding="utf-8")
    safe_open = _make_safe_open([str(allowed)])

    with pytest.raises(PermissionError):
        with safe_open(path):
            pytest.fail("A similar directory prefix was accepted.")


def test_empty_allowlist_denies_access(tmp_path):
    path = tmp_path / "data.txt"
    path.write_text("hello", encoding="utf-8")
    safe_open = _make_safe_open([])

    with pytest.raises(PermissionError):
        with safe_open(path):
            pytest.fail("An empty allowlist permitted access.")


@pytest.mark.parametrize("path", [b"data.txt", object()])
def test_unsupported_path_types_are_rejected(tmp_path, path):
    safe_open = _make_safe_open([str(tmp_path)])

    with pytest.raises(TypeError):
        safe_open(path)


def test_file_descriptor_is_rejected(tmp_path):
    path = tmp_path / "data.txt"
    path.write_text("hello", encoding="utf-8")
    safe_open = _make_safe_open([str(tmp_path)])

    with path.open() as file:
        with pytest.raises(TypeError):
            safe_open(file.fileno())
        assert file.read() == "hello"


def test_custom_opener_is_rejected(tmp_path):
    safe_open = _make_safe_open([str(tmp_path)])

    def custom_opener(path, flags):
        pytest.fail("The custom opener must not be called.")

    with pytest.raises(ValueError):
        safe_open(tmp_path / "new.txt", "w", opener=custom_opener)

    assert not (tmp_path / "new.txt").exists()


def test_closefd_false_is_rejected(tmp_path):
    safe_open = _make_safe_open([str(tmp_path)])

    with pytest.raises(ValueError):
        safe_open(tmp_path / "new.txt", "w", closefd=False)

    assert not (tmp_path / "new.txt").exists()


def test_missing_file_error_is_propagated(tmp_path):
    safe_open = _make_safe_open([str(tmp_path)])

    with pytest.raises(FileNotFoundError):
        safe_open(tmp_path / "missing.txt")


def test_invalid_mode_error_is_propagated(tmp_path):
    safe_open = _make_safe_open([str(tmp_path)])

    with pytest.raises(ValueError):
        safe_open(tmp_path / "data.txt", "invalid")


def test_builtin_open_is_unchanged(tmp_path):
    original_open = builtins.open
    safe_open = _make_safe_open([str(tmp_path)])
    assert builtins.open is original_open

    with safe_open(tmp_path / "new.txt", "w") as file:
        file.write("hello")

    assert builtins.open is original_open
