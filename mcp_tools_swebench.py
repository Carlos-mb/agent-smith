"""MCP server exposing the mandatory SWE-bench repository tools.

Each function is a thin wrapper: the decorator and signature give the SDK the
name, arguments and English description that build the manual the model reads,
and the work itself belongs to agent_smith.swebench_tools.
"""

from mcp.server.fastmcp import FastMCP

from agent_smith import swebench_tools
from agent_smith.logging_config import configure_logging, get_logger

logger = get_logger('mcp_tools_swebench')


mcp = FastMCP("Agent Smith SWE-bench tools")


@mcp.tool()
def read_file(filepath: str, start_line: int = 1, end_line: int = 200) -> str:
    """Read an inclusive range of one file as numbered lines.

    Args:
        filepath: Path inside the repository, for example /testbed/module.py.
        start_line: First line to return, counting from 1.
        end_line: Last line to return, included.

    Returns:
        The requested lines, each prefixed by its line number.
    """
    logger.debug("Entrando en read_file")
    return swebench_tools.read_file(filepath, start_line, end_line)


@mcp.tool()
def edit_file(filepath: str, old_str: str, new_str: str) -> str:
    """Replace one exact fragment of a file with another.

    The edit is refused unless old_str appears exactly once, and refused for a
    Python file whose result would no longer compile. Include enough
    surrounding context in old_str to make it unique.

    Args:
        filepath: Path inside the repository to modify.
        old_str: Exact text to replace, appearing exactly once in the file.
        new_str: Text to write in its place.

    Returns:
        Confirmation, or the reason the edit was refused.
    """
    logger.debug("Entrando en edit_file")
    return swebench_tools.edit_file(filepath, old_str, new_str)


@mcp.tool()
def list_files(directory: str = "/testbed", pattern: str = "*.py") -> str:
    """List the files under a directory whose name matches a shell pattern.

    Args:
        directory: Directory to walk, for example /testbed.
        pattern: Shell pattern applied to the file name, for example *.py.

    Returns:
        One path per line.
    """
    logger.debug("Entrando en list_files")
    return swebench_tools.list_files(directory, pattern)


@mcp.tool()
def search_code(pattern: str, file_pattern: str = "*.py") -> str:
    """Search the repository for a regular expression.

    Args:
        pattern: Python regular expression to look for in each line.
        file_pattern: Shell pattern selecting which files to search.

    Returns:
        One matching line per result, with its path and line number.
    """
    logger.debug("Entrando en search_code")
    return swebench_tools.search_code(pattern, file_pattern)


@mcp.tool()
def search_function_or_class_definition_in_code(name: str) -> str:
    """Find where a function or class with this exact name is defined.

    Args:
        name: Exact function or class name, without def or class.

    Returns:
        One line per definition found, with its path and line number.
    """
    logger.debug("Entrando en search_function_or_class_definition_in_code")
    return swebench_tools.search_function_or_class_definition_in_code(name)


@mcp.tool()
def find_references(name: str, filepath: str = "", line: int = 0) -> str:
    """Find where a name is used across the repository.

    This is a textual search: it cannot tell apart two different symbols that
    share a name. filepath and line record which definition you are asking
    about; they do not narrow the search.

    Args:
        name: Name to look for.
        filepath: File where the definition lives, if known.
        line: Line of that definition, if known.

    Returns:
        One matching line per result, with its path and line number.
    """
    logger.debug("Entrando en find_references")
    return swebench_tools.find_references(name, filepath, line)


@mcp.tool()
def run_command(command: str, workdir: str = "/testbed") -> str:
    """Run one shell command inside the repository.

    Args:
        command: Shell command to run.
        workdir: Directory to run it from.

    Returns:
        The exit code with the command's standard output and standard error.
    """
    logger.debug("Entrando en run_command")
    return swebench_tools.run_command(command, workdir)


@mcp.tool()
def run_tests() -> str:
    """Run the evaluation script supplied with this task.

    Returns:
        The exit code with the test run's standard output and standard error.
    """
    logger.debug("Entrando en run_tests")
    return swebench_tools.run_tests()


@mcp.tool()
def get_patch() -> str:
    """Return the complete diff of every change made so far.

    Returns:
        The unified diff, or a note saying there are no changes yet.
    """
    logger.debug("Entrando en get_patch")
    return swebench_tools.get_patch()


if __name__ == "__main__":
    configure_logging()
    logger.info("Iniciando servidor MCP SWE-bench mediante mcp.run "
                "con transporte stdio")
    mcp.run(transport="stdio")
    logger.info("Servidor MCP SWE-bench cerrado")
