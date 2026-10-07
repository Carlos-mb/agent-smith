"""SWE-bench tools: one execution helper and nine direct tools.

Every operation runs where the checkout lives. With AGENT_SMITH_CONTAINER_ID
the helper runs `docker exec` inside that task container; otherwise it runs
on the host under TESTBED_PATH, which lets the tools be tested without a
container. The generated-code worker never receives the container id, a Docker
client or keys.

Paths are always exchanged as /testbed/... so the model sees the same layout in
both modes; the helper maps that prefix onto the real root.
"""

from __future__ import annotations

from agent_smith.logging_config import get_logger

import os
from pathlib import Path
import re
import subprocess
import sys
import time

logger = get_logger('agent_smith.swebench_tools')


TESTBED_DIRECTORY = "/testbed"
DEFAULT_COMMAND_TIMEOUT_SECONDS = 120
TEST_TIMEOUT_SECONDS = 900
# Every observation is resent to the model on ALL following iterations, so
# its real cost is its size times what is left of the task. With the old
# 12,000 limit, a single search used 72,264 of the 300,000 input tokens.
# The patch does not go through here: get_patch is returned in full.
MAX_TOOL_OUTPUT_CHARACTERS = 4_000
MAX_SEARCH_MATCHES = 50
SKIPPED_DIRECTORIES = {".git", "__pycache__", ".tox", ".venv", "node_modules"}

# These programs run where the checkout lives. Their arguments travel as
# separate argv, never interpolated: that way neither the model's quotes
# nor its line breaks can turn into another command.
_READ_PROGRAM = """
import pathlib, sys
lines = pathlib.Path(sys.argv[1]).read_text(errors="replace").splitlines()
start, end = int(sys.argv[2]), int(sys.argv[3])
for number in range(max(1, start), min(len(lines), end) + 1):
    print(f"{number}: {lines[number - 1]}")
"""

_EDIT_PROGRAM = """
import pathlib, sys
path = pathlib.Path(sys.argv[1])
old, new = sys.argv[2], sys.argv[3]
content = path.read_text()
count = content.count(old)
if count != 1:
    print("edit_file refused: expected exactly one match of old_str, "
          f"found {count}.")
    if count > 1:
        # Tell it WHERE they are: without this the model retries blindly.
        # Seen in a real task: eight iterations in a row against a repeated
        # docstring.
        places, start = [], 0
        while True:
            found = content.find(old, start)
            if found < 0:
                break
            places.append(str(content.count(chr(10), 0, found) + 1))
            start = found + 1
        print("It matches starting at lines: " + ", ".join(places))
        print("Extend old_str with nearby lines until it appears "
              "exactly once.")
    raise SystemExit(2)
if old == new:
    # We used to answer "Edit applied successfully." to an edit that changes
    # nothing. In scikit-learn-13439 codestral sent the same no-op edit 13
    # times, believed the confirmation each time, and burned the whole task:
    # 30 iterations and 288,129 input tokens without the tests ever passing.
    print("edit_file refused: old_str and new_str are identical; "
          "the file is unchanged.")
    raise SystemExit(4)
updated = content.replace(old, new, 1)
if path.suffix == ".py":
    try:
        compile(updated, str(path), "exec")
    except SyntaxError as error:
        print(f"edit_file refused: the result would not compile: {error}")
        raise SystemExit(3)
path.write_text(updated)
print("Edit applied successfully.")
"""

_LIST_PROGRAM = """
import fnmatch, os, sys
root, directory, pattern = sys.argv[1], sys.argv[2], sys.argv[3]
skip = set(sys.argv[4].split(","))
for base, directories, names in os.walk(directory):
    directories[:] = [name for name in directories if name not in skip]
    for name in sorted(names):
        if fnmatch.fnmatch(name, pattern):
            print("/testbed" + os.path.join(base, name)[len(root):])
"""

_SEARCH_PROGRAM = """
import fnmatch, os, re, sys
root, file_pattern = sys.argv[1], sys.argv[3]
expression = re.compile(sys.argv[2])
skip = set(sys.argv[4].split(","))
limit = int(sys.argv[5])
found = 0
for base, directories, names in os.walk(root):
    directories[:] = [name for name in directories if name not in skip]
    for name in sorted(names):
        if not fnmatch.fnmatch(name, file_pattern):
            continue
        path = os.path.join(base, name)
        try:
            with open(path, errors="replace") as handle:
                for number, line in enumerate(handle, 1):
                    if expression.search(line):
                        print(f"/testbed{path[len(root):]}:{number}: "
                              f"{line.rstrip()}")
                        found += 1
                        if found >= limit:
                            print(f"[Only the first {limit} matches are "
                                  "shown. Narrow the pattern to see the "
                                  "rest.]")
                            raise SystemExit(0)
        except OSError:
            pass
"""


def _container_id() -> str:
    """Return the task container, or empty text when running on the host."""
    logger.debug("Entrando en _container_id")
    return os.environ.get("AGENT_SMITH_CONTAINER_ID", "")


def _root() -> str:
    """Return the checkout root: the host testbed or /testbed in Docker."""
    logger.debug("Entrando en _root")
    if _container_id():
        return TESTBED_DIRECTORY
    root = Path(os.environ.get("TESTBED_PATH", TESTBED_DIRECTORY))
    return str(root.resolve(strict=False))


def _real_path(filepath: str) -> str:
    """Map a /testbed path onto the real root; refuse anything outside it."""
    logger.debug("Entrando en _real_path")
    root = _root()
    candidate = Path(filepath)
    if candidate.is_absolute() and candidate.parts[:2] == ("/", "testbed"):
        candidate = Path(root).joinpath(*candidate.parts[2:])
    elif not candidate.is_absolute():
        candidate = Path(root) / candidate
    resolved = candidate.resolve(strict=False)
    if resolved != Path(root) and Path(root) not in resolved.parents:
        logger.warning("Ruta rechazada: queda fuera del testbed")
        raise ValueError(f"Path outside the testbed: {filepath}")
    return str(resolved)


def _remaining_seconds(limit: int) -> int:
    """Bound a tool timeout by what is left of the whole task deadline."""
    logger.debug("Entrando en _remaining_seconds")
    deadline = os.environ.get("AGENT_SMITH_DEADLINE")
    if not deadline:
        return limit
    return max(1, min(limit, int(float(deadline) - time.monotonic())))


def _truncate(text: str) -> str:
    """Keep the beginning and the end, announcing how much was dropped."""
    logger.debug("Entrando en _truncate")
    if len(text) <= MAX_TOOL_OUTPUT_CHARACTERS:
        return text
    half = MAX_TOOL_OUTPUT_CHARACTERS // 2
    omitted = len(text) - 2 * half
    logger.warning("Salida de herramienta truncada: %s caracteres omitidos",
                   omitted)
    return (f"{text[:half]}\n[Output truncated: {omitted} characters "
            f"omitted.]\n{text[-half:]}")


def _run(
    arguments: list[str],
    workdir: str = TESTBED_DIRECTORY,
    timeout_seconds: int = DEFAULT_COMMAND_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess:
    """Run one command where the checkout lives: container or host."""
    logger.debug("Entrando en _run")
    container = _container_id()
    if container:
        arguments = ["docker", "exec", "-w", workdir, container] + arguments
        cwd = None
    else:
        cwd = _real_path(workdir)
    logger.info("Ejecutando en el testbed: %s", arguments[0])
    return subprocess.run(
        arguments, cwd=cwd, text=True, capture_output=True,
        timeout=timeout_seconds, check=False,
    )


def _python() -> str:
    """Return the interpreter name to use where the command runs."""
    logger.debug("Entrando en _python")
    return "python" if _container_id() else sys.executable


def _report(completed: subprocess.CompletedProcess) -> str:
    """Return stdout when the command succeeded, or the full diagnosis."""
    logger.debug("Entrando en _report")
    if completed.returncode == 0:
        return _truncate(completed.stdout)
    logger.warning("La orden termino con codigo %s", completed.returncode)
    return _truncate(
        f"exit_code: {completed.returncode}\n"
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )


def _run_program(
    program: str,
    *arguments: str,
    timeout_seconds: int = DEFAULT_COMMAND_TIMEOUT_SECONDS,
) -> str:
    """Run one of the small Python programs above with separate arguments."""
    logger.debug("Entrando en _run_program")
    try:
        completed = _run([_python(), "-c", program, *arguments],
                         timeout_seconds=timeout_seconds)
    except subprocess.TimeoutExpired:
        logger.error("La orden supero su timeout de %ss", timeout_seconds)
        return ("exit_code: timeout\nCommand timed out after "
                f"{timeout_seconds} seconds.")
    return _report(completed)


def read_file(filepath: str, start_line: int, end_line: int) -> str:
    """Return the requested lines of one file, each prefixed by its number."""
    logger.debug("Entrando en read_file")
    return _run_program(_READ_PROGRAM, _real_path(filepath),
                        str(start_line), str(end_line))


def edit_file(filepath: str, old_str: str, new_str: str) -> str:
    """Replace one unique fragment.

    Refuses an ambiguous match, a result that would not compile, and an edit
    that changes nothing, so a no-op never comes back as a success.
    """
    logger.debug("Entrando en edit_file")
    return _run_program(_EDIT_PROGRAM, _real_path(filepath), old_str, new_str)


def list_files(directory: str, pattern: str = "*") -> str:
    """List the files under a directory whose name matches the pattern."""
    logger.debug("Entrando en list_files")
    return _run_program(
        _LIST_PROGRAM, _root(), _real_path(directory), pattern,
        ",".join(SKIPPED_DIRECTORIES),
    )


def search_code(pattern: str, file_pattern: str = "*.py") -> str:
    """Return every line matching a regex, with its file and line number."""
    logger.debug("Entrando en search_code")
    return _run_program(
        _SEARCH_PROGRAM, _root(), pattern, file_pattern,
        ",".join(SKIPPED_DIRECTORIES), str(MAX_SEARCH_MATCHES),
    )


def search_function_or_class_definition_in_code(name: str) -> str:
    """Find where a function or class with this exact name is defined."""
    logger.debug("Entrando en search_function_or_class_definition_in_code")
    return search_code(rf"^\s*(def|class)\s+{re.escape(name)}\b")


def find_references(name: str, filepath: str = "", line: int = 0) -> str:
    """Find where a name is used. This is a textual search, not a semantic one.

    filepath and line say which definition the model is asking about; the
    search itself cannot tell two same-named symbols apart.
    """
    logger.debug("Entrando en find_references")
    logger.info("Buscando referencias textuales de %s (definida en %s:%s)",
                name, filepath, line)
    return search_code(rf"\b{re.escape(name)}\b")


def run_command(command: str, workdir: str = TESTBED_DIRECTORY) -> str:
    """Run one shell command inside the testbed and return what it printed."""
    logger.debug("Entrando en run_command")
    try:
        completed = _run(
            ["/bin/bash", "-lc", command], workdir=workdir,
            timeout_seconds=_remaining_seconds(
                DEFAULT_COMMAND_TIMEOUT_SECONDS),
        )
    except subprocess.TimeoutExpired:
        logger.error("La orden supero su timeout")
        return ("exit_code: timeout\nCommand timed out after "
                f"{DEFAULT_COMMAND_TIMEOUT_SECONDS} seconds.")
    return _truncate(
        f"exit_code: {completed.returncode}\n"
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )


def run_tests() -> str:
    """Run the evaluation script supplied with the task, or pytest when absent.

    With an eval_script, only the part between its Start/End Test Output
    markers is returned: that is where the test result is.
    """
    logger.debug("Entrando en run_tests")
    script = os.environ.get("AGENT_SMITH_EVAL_SCRIPT", "")
    if not script:
        logger.warning("Sin eval_script en el entorno; se usa pytest")
        script = "pytest -q"
    try:
        # stderr is merged into stdout in order: unittest (Django) writes its
        # summary there, and so do the markers printed by the eval_script's
        # set -x.
        completed = _run(
            ["/bin/bash", "-lc", "exec 2>&1\n" + script],
            timeout_seconds=_remaining_seconds(TEST_TIMEOUT_SECONDS),
        )
    except subprocess.TimeoutExpired:
        logger.error("Los tests superaron su timeout")
        return ("exit_code: timeout\nTests timed out after "
                f"{TEST_TIMEOUT_SECONDS} seconds.")
    output = completed.stdout
    # The old truncation kept the beginning (git status, mode changes) and
    # the end (warnings), and the test result fell in the middle: the model
    # never saw it. The exit_code is no use either: it belongs to the
    # script's final git checkout.
    start = output.find(">>>>> Start Test Output")
    end = output.rfind(">>>>> End Test Output")
    if 0 <= start < end:
        return _truncate(output[start:end])
    return _truncate(f"exit_code: {completed.returncode}\noutput:\n{output}")


def get_patch() -> str:
    """Return the complete diff of the work done so far, never truncated."""
    logger.debug("Entrando en get_patch")
    try:
        completed = _run(["git", "-c", "core.fileMode=false", "diff"],
                         timeout_seconds=60)
    except subprocess.TimeoutExpired:
        logger.error("git diff supero su timeout")
        return "exit_code: timeout\ngit diff timed out."
    if completed.returncode != 0:
        logger.error("git diff fallo con codigo %s", completed.returncode)
        return (f"exit_code: {completed.returncode}\n"
                f"stderr:\n{completed.stderr}")
    if not completed.stdout.strip():
        logger.info("git diff vacio: todavia no hay cambios")
        return "No changes yet."
    # The patch is the deliverable: it is kept whole however long it is.
    return completed.stdout
