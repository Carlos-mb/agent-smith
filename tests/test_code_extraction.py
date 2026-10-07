from agent_smith.code_extraction import (
    CONVERTED_TOOL_CALL_FEEDBACK, extract_agent_code, extract_python_code,
)


def test_extract_python_fenced_block():
    llm_output = """
I will call the tool.

```python
result = run_tests(code="solution", test_imports=[], test_list=[])
print(result)
```
"""

    code, feedback = extract_python_code(llm_output)

    expected_code = (
        'result = run_tests(code="solution", test_imports=[], test_list=[])\n'
        "print(result)"
    )

    assert code == expected_code
    assert feedback == ""


def test_a_nested_fence_runs_the_inner_block():
    # Both models write their Thought inside the fence and then open a second
    # ```python. The first block closes against that opening, so it never
    # parses: six saved MBPP requests executed nothing because of this.
    llm_output = (
        "```python\n"
        "Thought: I will define frequency using the count method.\n"
        "```python\n"
        'solution = r"""def frequency(a, x):\n'
        "    return a.count(x)\n"
        '"""\n'
        "print(run_tests(code=solution))\n"
        "```\n"
    )

    code, feedback = extract_python_code(llm_output)

    assert code.startswith('solution = r"""def frequency(a, x):')
    assert code.endswith("print(run_tests(code=solution))")
    assert feedback == ""


def test_a_block_without_a_nested_fence_still_reports_its_syntax_error():
    code, feedback = extract_python_code("```python\nThought: no code\n```\n")

    assert code == ""
    assert "syntax error" in feedback



# def test_extract_py_fenced_block():
#     llm_output = """
# ```py
# print("hello")
# ```
# """

#     code, feedback = extract_python_code(llm_output)

#     assert code == 'print("hello")'
#     assert feedback == ""


# def test_extract_unlabelled_fenced_block():
#     llm_output = """
# Here is the code:

# ```
# value = 42
# print(value)
# ```
# """

#     code, feedback = extract_python_code(llm_output)

#     expected_code = "value = 42\nprint(value)"

#     assert code == expected_code
#     assert feedback == ""


# def test_extract_raw_python():
#     llm_output = """
# result = run_tests(code="solution", test_imports=[], test_list=[])
# print(result)
# """

#     code, feedback = extract_python_code(llm_output)

#     expected_code = (
#         'result = run_tests(code="solution", test_imports=[], test_list=[])\n'
#         "print(result)"
#     )

#     assert code == expected_code
#     assert feedback == ""


# def test_extract_unclosed_python_block():
#     llm_output = """
# I will call the tool.

# ```python
# print("hello")
# """

#     code, feedback = extract_python_code(llm_output)

#     assert code == 'print("hello")'
#     assert feedback == (
#         "Malformed Python code block was interpreted without a closing fence."
#     )


# def test_reject_response_without_python():
#     llm_output = "I think we should inspect the tests first."

#     code, feedback = extract_python_code(llm_output)

#     assert code == ""
#     assert feedback == (
#         "No valid Python code was found in the model response."
#     )

def test_closed_block_with_syntax_error_is_rejected():
    code, feedback = extract_python_code("```python\ndef broken(\n```")

    assert code == ""
    assert feedback.startswith("Python syntax error on line 1:")
    assert "closing fence" not in feedback


def test_empty_response_has_specific_feedback():
    for response in ("", " \n\t"):
        assert extract_python_code(response) == ("", "Model response was empty.")


def test_response_without_code_is_rejected():
    assert extract_python_code("I will inspect the tests.") == (
        "", "No valid Python code was found in the model response."
    )


def test_unclosed_block_is_rejected_without_recovery():
    code, feedback = extract_python_code("```python\nprint('hello')")

    assert code == ""
    assert feedback == "Python code block is missing its closing fence; not executed."


def test_py_block_and_optional_end_code_marker():
    for suffix in ("", "<end_code>"):
        assert extract_python_code("```py\nprint('hello')\n```" + suffix) == (
            "print('hello')", ""
        )


def test_tool_call_becomes_a_printed_python_call():
    output = (
        "<tool_call>read_file\n"
        "<arg_key>filepath</arg_key>\n<arg_value>/testbed/x.py</arg_value>\n"
        "<arg_key>start_line</arg_key>\n<arg_value>586</arg_value>\n"
        "</tool_call>"
    )

    code, feedback = extract_agent_code(output)

    assert code == "print(read_file(filepath='/testbed/x.py', start_line=586))"
    assert feedback == CONVERTED_TOOL_CALL_FEEDBACK


def test_a_python_fence_wins_over_a_tool_call():
    output = "```python\nprint(1)\n```\n<tool_call>read_file\n</tool_call>"

    assert extract_agent_code(output)[0] == "print(1)"


def test_several_tool_calls_keep_their_order():
    output = (
        "<tool_call>list_files\n<arg_key>directory</arg_key>\n<arg_value>/testbed</arg_value>\n</tool_call>\n"
        "<tool_call>get_patch\n</tool_call>"
    )

    code, _ = extract_agent_code(output)

    assert code.splitlines() == [
        "print(list_files(directory='/testbed'))", "print(get_patch())",
    ]


def test_a_truncated_tool_call_executes_nothing():
    code, feedback = extract_agent_code("<tool_call>read_file\n<arg_key>filepath</arg_key>")

    assert code == ""
    assert "No valid Python code" in feedback


def test_an_unclosed_argument_name_is_refused():
    output = "<tool_call>read_file\n<arg_key>filepath\n</tool_call>"

    code, feedback = extract_agent_code(output)

    assert code == ""
    assert "Malformed tool call" in feedback


def test_a_forgotten_arg_value_opening_tag_still_converts():
    # Observado en una ejecucion real: el modelo abre el valor sin la etiqueta
    # y solo pone el cierre. Antes esto costaba 23 iteraciones seguidas.
    output = (
        "<tool_call>run_command\n<arg_key>command</arg_key>\n\n"
        "cd /testbed && echo \"hola\"</arg_value>\n</tool_call>"
    )

    code, feedback = extract_agent_code(output)

    assert code == 'print(run_command(command=\'cd /testbed && echo "hola"\'))'
    assert feedback == CONVERTED_TOOL_CALL_FEEDBACK


def test_a_tool_call_without_arguments_converts():
    assert extract_agent_code("<tool_call>get_patch\n</tool_call>")[0] == "print(get_patch())"


def test_a_forgotten_arg_value_closing_tag_still_converts():
    # Observado en una ejecucion real: con valores largos el modelo se deja el
    # cierre y antes perdiamos la iteracion entera.
    output = (
        "<tool_call>run_command\n<arg_key>command</arg_key>\n"
        "<arg_value>cd /testbed && python -c \"print(1)\"\n</tool_call>"
    )

    code, feedback = extract_agent_code(output)

    assert code == 'print(run_command(command=\'cd /testbed && python -c "print(1)"\'))'
    assert feedback == CONVERTED_TOOL_CALL_FEEDBACK


def test_an_unusable_tool_name_is_refused():
    code, feedback = extract_agent_code("<tool_call>rm -rf /\n</tool_call>")

    assert code == ""
    assert "Malformed tool call" in feedback


def test_argument_values_keep_quotes_and_newlines_as_data():
    output = (
        "<tool_call>edit_file\n"
        "<arg_key>old_str</arg_key>\n<arg_value>x = \"a\"\nreturn x</arg_value>\n"
        "</tool_call>"
    )

    code, _ = extract_agent_code(output)

    # El valor viaja como literal, nunca como codigo que se pueda ejecutar.
    assert code == 'print(edit_file(old_str=\'x = "a"\\nreturn x\'))'


def test_tool_use_with_json_arguments_becomes_a_python_call():
    output = (
        "I will search.\n\n<tool_use>\n<server_name>sympy</server_name>\n"
        "<tool_name>search_code</tool_name>\n<arguments>\n"
        '{"pattern": "cotm", "file_pattern": "*.py"}\n</arguments>\n</tool_use>'
    )

    code, feedback = extract_agent_code(output)

    assert code == "print(search_code(pattern='cotm', file_pattern='*.py'))"
    assert feedback == CONVERTED_TOOL_CALL_FEEDBACK


def test_tool_use_without_arguments_converts():
    assert extract_agent_code(
        "<tool_use>\n<tool_name>get_patch</tool_name>\n</tool_use>"
    )[0] == "print(get_patch())"


def test_tool_use_keeps_newlines_inside_string_arguments():
    output = (
        "<tool_use>\n<tool_name>edit_file</tool_name>\n<arguments>\n"
        '{"old_str": "a\\nb", "new_str": "a\\nc"}\n</arguments>\n</tool_use>'
    )

    code, _ = extract_agent_code(output)

    assert code == "print(edit_file(old_str='a\\nb', new_str='a\\nc'))"


def test_tool_use_with_broken_json_is_refused():
    output = (
        "<tool_use>\n<tool_name>search_code</tool_name>\n"
        '<arguments>\n{"pattern": }\n</arguments>\n</tool_use>'
    )

    code, feedback = extract_agent_code(output)

    assert code == ""
    assert "Malformed tool call" in feedback


def test_a_python_fence_still_wins_over_tool_use():
    output = "```python\nprint(1)\n```\n<tool_use>\n<tool_name>get_patch</tool_name>\n</tool_use>"

    assert extract_agent_code(output)[0] == "print(1)"


# Change 1 of notes/PLAN_CAMBIOS_14711.md: given the tool names discovered by
# MCP, run the first block that calls one of them, not an example before it.
TOOLS = ["edit_file", "get_patch", "run_tests", "final_answer"]


def test_an_example_block_before_the_call_is_not_executed():
    # Qwen, sympy-14711, 29/09, step 11 (shortened): we ran the example, the
    # model saw "printed nothing" and concluded its edit had not worked.
    output = (
        "The fix should be:\n"
        "```python\ndef __add__(self, other):\n    if other == 0:\n        return self\n```\n"
        "Let me apply this fix.\n"
        "```python\nprint(edit_file(filepath='/testbed/vector.py', old_str='a', new_str='b'))\n```"
    )

    code, feedback = extract_agent_code(output, TOOLS)

    assert code == "print(edit_file(filepath='/testbed/vector.py', old_str='a', new_str='b'))"
    assert feedback == ""


def test_an_action_followed_by_final_answer_runs_the_action():
    # Codestral writes both in one reply: running the last block would submit
    # the patch before seeing the test results.
    output = "```python\nprint(run_tests())\n```\n```python\nfinal_answer(get_patch())\n```"

    assert extract_agent_code(output, TOOLS)[0] == "print(run_tests())"


def test_when_no_block_calls_a_tool_the_first_one_runs_as_before():
    output = "```python\nx = 1\nprint(x)\n```\n```python\ny = 2\n```"

    assert extract_agent_code(output, TOOLS) == ("x = 1\nprint(x)", "")


def test_without_tool_names_the_first_block_runs_as_before():
    output = "```python\nx = 1\n```\n```python\nprint(get_patch())\n```"

    assert extract_agent_code(output) == ("x = 1", "")


def test_a_block_that_calls_a_tool_but_does_not_compile_is_skipped():
    # A broken block is left to today's code, which reports the syntax error
    # instead of sending it to the sandbox.
    output = (
        "```python\nx = 1\n```\n"
        "```python\nprint(edit_file(filepath=\n```\n"
        "```python\nprint(get_patch())\n```"
    )

    assert extract_agent_code(output, TOOLS)[0] == "print(get_patch())"
