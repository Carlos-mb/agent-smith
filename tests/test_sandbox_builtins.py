"""Test builtin connections with known Python code and temporary files."""

import builtins

import pytest

from agent_smith.models import SandboxConfig
from agent_smith.sandbox import _make_safe_builtins


def test_allowed_builtins_work_in_python_code():
    safe = _make_safe_builtins(SandboxConfig())
    namespace = {"__builtins__": safe, "__name__": "__sandbox__"}

    exec(
        "class Counter:\n"
        "    def total(self):\n"
        "        return sum(range(4))\n"
        "result = Counter().total()\n",
        namespace,
    )

    assert namespace["result"] == 6


def test_restricted_names_are_not_exposed():
    safe = _make_safe_builtins(SandboxConfig())

    for name in (
        "eval", "exec", "compile", "input", "breakpoint",
        "help", "globals", "locals", "vars",
    ):
        assert name not in safe


@pytest.mark.parametrize("code", [
    "import math\nresult = math.sqrt(9)",
    "from math import sqrt\nresult = sqrt(9)",
])
def test_allowed_imports_work(code):
    config = SandboxConfig(authorized_imports=["math"])
    namespace = {"__builtins__": _make_safe_builtins(config)}

    exec(code, namespace)

    assert namespace["result"] == 3


@pytest.mark.parametrize("code", [
    "import collections.abc\nresult = collections.abc.Iterable",
    "from collections import abc\nresult = abc.Iterable",
])
def test_allowed_submodule_imports_work(code):
    config = SandboxConfig(
        authorized_imports=["collections", "collections.*"],
    )
    namespace = {"__builtins__": _make_safe_builtins(config)}

    exec(code, namespace)

    assert isinstance([], namespace["result"])


@pytest.mark.parametrize("code", [
    "import collections.abc",
    "from collections import abc",
])
def test_submodule_requires_permission(code):
    config = SandboxConfig(authorized_imports=["collections"])
    namespace = {"__builtins__": _make_safe_builtins(config)}

    with pytest.raises(ImportError):
        exec(code, namespace)


def test_unlisted_import_is_denied():
    config = SandboxConfig(authorized_imports=["math"])
    namespace = {"__builtins__": _make_safe_builtins(config)}

    with pytest.raises(ImportError):
        exec("import json", namespace)


def test_empty_allowlists_deny_imports_and_files(tmp_path):
    path = tmp_path / "data.txt"
    path.write_text("hello", encoding="utf-8")
    config = SandboxConfig(authorized_imports=[], allowed_directories=[])
    namespace = {
        "__builtins__": _make_safe_builtins(config),
        "path": str(path),
    }

    with pytest.raises(ImportError):
        exec("import math", namespace)

    with pytest.raises(PermissionError):
        exec("with open(path) as file:\n    result = file.read()", namespace)


def test_allowed_open_works_in_python_code(tmp_path):
    config = SandboxConfig(allowed_directories=[str(tmp_path)])
    namespace = {
        "__builtins__": _make_safe_builtins(config),
        "path": str(tmp_path / "data.txt"),
    }

    exec(
        "with open(path, 'w', encoding='utf-8') as file:\n"
        "    file.write('hello')\n"
        "with open(path, encoding='utf-8') as file:\n"
        "    result = file.read()\n",
        namespace,
    )

    assert namespace["result"] == "hello"
    assert (tmp_path / "data.txt").read_text(encoding="utf-8") == "hello"


def test_open_outside_allowed_directory_is_denied(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    config = SandboxConfig(allowed_directories=[str(allowed)])
    namespace = {
        "__builtins__": _make_safe_builtins(config),
        "path": str(outside),
    }

    with pytest.raises(PermissionError):
        exec("with open(path) as file:\n    result = file.read()", namespace)


def test_global_builtins_are_unchanged(tmp_path):
    original_builtins = vars(builtins).copy()
    config = SandboxConfig(
        authorized_imports=["math"], allowed_directories=[str(tmp_path)],
    )
    namespace = {
        "__builtins__": _make_safe_builtins(config),
        "path": str(tmp_path / "data.txt"),
    }

    exec(
        "import math\n"
        "with open(path, 'w') as file:\n"
        "    file.write(str(math.sqrt(9)))\n",
        namespace,
    )

    assert vars(builtins) == original_builtins
