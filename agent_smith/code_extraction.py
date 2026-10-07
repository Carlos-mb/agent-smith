"""Extract Python blocks and describe the pending JSON tool-call conversion."""

from agent_smith.logging_config import get_logger

import ast
import json
import re

logger = get_logger('agent_smith.code_extraction')


def extract_python_code(llm_output: str) -> tuple[str, str]:
    """Return Python source and extraction feedback without executing it.

    Accept a closed python or py fenced block and check its body with
    ast.parse. Empty responses, missing blocks, missing closing fences, and
    invalid syntax return empty source with a diagnostic. Valid source has
    empty feedback. Raw Python and unlabelled blocks are unsupported. The one
    repair is a nested fence: when the block does not parse and a second
    ```python opens inside it, the rest is retried, because models write their
    Thought inside the first fence. An optional <end_code> marker belongs
    after the closing fence.
    """
    logger.debug("Entrando en extract_python_code")

    code: str = ""
    feedback: str = ""
    if (llm_output.strip() == ""):
        logger.warning("Extracción rechazada: respuesta vacía")
        feedback = "Model response was empty."
        return code, feedback

    feedback = "No valid Python code was found in the model response."

    code_starts = llm_output.find("```python")
    if (code_starts == -1):
        code_starts = llm_output.find("```py")
        if (code_starts != -1):
            code_starts = code_starts + 5
    else:
        code_starts = code_starts + 9

    if code_starts != -1:
        code_ends = llm_output.find("```", code_starts)
        if (code_ends != -1):
            code = llm_output[code_starts:code_ends].strip()
        else:
            logger.warning("Bloque Python incompleto: falta el cierre; "
                           "no se ejecutará")
            return "", ("Python code block is missing its closing fence; "
                        "not executed.")

    if code != "":
        try:
            ast.parse(code)
            feedback = ""
            logger.debug("Bloque Python completo y sintaxis válida: "
                         "%s caracteres", len(code))
        except SyntaxError as exc:
            logger.warning("Sintaxis Python inválida en línea %s: %s",
                           exc.lineno, exc.msg)
            # Both models sometimes write "Thought:" inside the fence and then
            # open a second ```python with the real code. The first block ends
            # against that second opening, so it never parses and the whole
            # request was wasted: six of the saved MBPP steps, 3,795 input
            # tokens, and two of them died later for lack of budget.
            rest = llm_output[code_ends:]
            if "```py" in rest:
                retried, retried_feedback = extract_python_code(rest)
                if retried:
                    logger.info("Valla anidada reparada: se ejecuta el "
                                "bloque interior")
                    return retried, retried_feedback
            code = ""
            feedback = f"Python syntax error on line {exc.lineno}: {exc.msg}"

    if not code:
        logger.warning("No se ha extraído código ejecutable: %s", feedback)
    return code, feedback


def _literal(value: str) -> str:
    """Render an argument value as a Python literal; integers stay integers."""
    logger.debug("Entrando en _literal")
    text = value.strip()
    if re.fullmatch(r"-?\d+", text):
        return text
    return repr(value)


def convert_tool_calls(llm_output: str) -> str:
    """Convert <tool_call> blocks into the equivalent Python calls.

    The subject asks the extraction layer to fit what the models were trained
    on. The free models used here fall back to this tool-call dialect as soon
    as they have seen a tool result, so converting it is what keeps them
    usable. Returns empty source when the response contains no complete call.
    """
    logger.debug("Entrando en convert_tool_calls")
    calls = re.findall(r"<tool_call>(.*?)</tool_call>", llm_output, re.DOTALL)
    if not calls:
        return ""

    statements = []
    for call in calls:
        body = call.strip()
        name = body.splitlines()[0].strip() if body else ""
        if not name.isidentifier():
            raise ValueError(f"Tool call without a usable name: {name!r}")

        # The <arg_value> and </arg_value> markers are optional on purpose:
        # with long values the models drop one of the two, and we used to
        # lose the whole iteration. The value is whatever follows the key,
        # up to the next key or the end of the call.
        arguments = []
        for chunk in re.split(r"<arg_key>", body)[1:]:
            key, separator, rest = chunk.partition("</arg_key>")
            if not separator:
                raise ValueError(f"Tool call {name} has an argument name "
                                 "that is never closed.")
            key = key.strip()
            if not key.isidentifier():
                raise ValueError(f"Tool call {name} has an unusable "
                                 f"argument name: {key!r}")

            opened = "<arg_value>" in rest
            value = rest.split("<arg_value>", 1)[1] if opened else rest
            closed = "</arg_value>" in value
            if closed:
                value = value.rsplit("</arg_value>", 1)[0]
            if not (opened and closed):
                # A marker is missing: the surrounding line breaks are not
                # part of the value.
                value = value.strip()
            arguments.append(f"{key}={_literal(value)}")

        logger.info("Convertida una llamada en formato tool_call: %s", name)
        statements.append(f"print({name}({', '.join(arguments)}))")

    return "\n".join(statements)


def convert_tool_use(llm_output: str) -> str:
    """Convert <tool_use> blocks with JSON arguments into Python calls.

    A third dialect seen live. In that run the model diagnosed the bug
    correctly and wrote the right edit, but in this format, so nothing ran
    in 23 of 29 iterations. The server name is ignored: the tool is already
    a local function in the sandbox.
    """
    logger.debug("Entrando en convert_tool_use")
    statements = []
    for block in re.findall(r"<tool_use>(.*?)</tool_use>", llm_output,
                            re.DOTALL):
        found = re.search(r"<tool_name>(.*?)</tool_name>", block, re.DOTALL)
        name = found.group(1).strip() if found else ""
        if not name.isidentifier():
            raise ValueError(f"Tool use without a usable name: {name!r}")

        found = re.search(r"<arguments>(.*?)</arguments>", block, re.DOTALL)
        try:
            arguments = (json.loads(found.group(1).strip() or "{}")
                         if found else {})
        except ValueError as exc:
            raise ValueError(
                f"Tool use {name} has invalid JSON arguments: {exc}")
        if not isinstance(arguments, dict):
            raise ValueError(
                f"Tool use {name} did not pass an object of arguments.")

        rendered = []
        for key, value in arguments.items():
            if not key.isidentifier():
                raise ValueError(f"Tool use {name} has an unusable "
                                 f"argument name: {key!r}")
            rendered.append(f"{key}={value!r}")

        logger.info("Convertida una llamada en formato tool_use: %s", name)
        statements.append(f"print({name}({', '.join(rendered)}))")

    return "\n".join(statements)


CONVERTED_TOOL_CALL_FEEDBACK = (
    "No ```python block was found; the tool call was converted to Python "
    "and executed."
)


def _first_block_calling(llm_output: str, tool_names: list = []) -> str:
    """Return the first closed ```python block that calls one of tool_names."""
    logger.debug("Entrando en _first_block_calling")

    blocks = re.findall(r"```python(.*?)```", llm_output, re.DOTALL)

    # Enumarete is only needed for logging.
    for number, block in enumerate(blocks, start=1):
        block = block.strip()
        for tool_name in tool_names:
            if tool_name + "(" in block:
                try:
                    ast.parse(block)
                    if number > 1:
                        logger.info("Se ejecuta el bloque %s: los anteriores "
                                    "no llaman a ninguna herramienta o no "
                                    "compilan", number)
                    return block
                except SyntaxError:
                    logger.debug("El bloque %s llama a %s pero no compila; "
                                 "se salta", number, tool_name)
                    break

    return ""


def extract_agent_code(llm_output: str, tool_names: list = []) -> tuple[str, str]:
    """Return executable Python from a fenced block, or from tool calls.

    With tool_names, the first closed ```python block that calls one of them
    wins: models often write an example block before the real call. Without
    a match, or without names, the first block is used as before.
    """
    logger.debug("Entrando en extract_agent_code")

    code = _first_block_calling(llm_output, tool_names)
    if code:
        return code, ""

    code, feedback = extract_python_code(llm_output)
    if code:
        return code, feedback

    # Do the same loop with 2 functions
    for convertir in (convert_tool_calls, convert_tool_use):
        try:
            converted = convertir(llm_output)
        except ValueError as exc:
            logger.warning("Llamada de herramienta malformada: %s", exc)
            return "", f"Malformed tool call: {exc}"
        if converted:
            # The subject requires a notice when a malformed block is
            # interpreted anyway.
            return converted, CONVERTED_TOOL_CALL_FEEDBACK
    return code, feedback
