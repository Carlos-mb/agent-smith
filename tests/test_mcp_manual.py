"""Tests for the MCP manual."""

from agent_smith.mcp_client import MCPManual


def test_manual_shows_tools_and_parameters() -> None:
    """The manual should describe discovered tools."""

    manual = MCPManual(
        instructions="Use the available tools.",
        tools=[
            {
                "name": "zeta",
                "description": "Second tool",
                "inputSchema": {
                    "properties": {},
                    "required": [],
                },
            },
            {
                "name": "saludar",
                "description": "Say hello",
                "inputSchema": {
                    "properties": {
                        "nombre": {
                            "type": "string",
                        },
                        "veces": {
                            "type": "integer",
                            "default": 1,
                        },
                    },
                    "required": ["nombre"],
                },
            },
        ],
        resources=[],
        resource_templates=[],
        prompts=[],
    )

    text = manual.as_text()

    assert "Use the available tools." in text

    assert "Tool: saludar" in text
    assert "Description: Say hello" in text

    assert "- nombre: string (required)" in text
    assert "- veces: integer (optional), default=1" in text

    # Tools are sorted by name.
    assert text.index("Tool: saludar") < text.index("Tool: zeta")

    # Parameters keep the order from properties.
    assert text.index("- nombre:") < text.index("- veces:")


def test_manual_shows_resources_and_prompts() -> None:
    """The manual should show other discovered MCP capabilities."""

    manual = MCPManual(
        instructions="",
        tools=[],
        resources=[
            {
                "name": "config",
                "uri": "file:///config.txt",
            },
        ],
        resource_templates=[
            {
                "name": "user",
                "uriTemplate": "file:///users/{id}",
            },
        ],
        prompts=[
            {
                "name": "fix_bug",
            },
        ],
    )

    text = manual.as_text()

    assert "RESOURCES" in text
    assert "config" in text
    assert "file:///config.txt" in text
    assert "Use read_resource(uri)." in text

    assert "RESOURCE TEMPLATES" in text
    assert "user" in text
    assert "file:///users/{id}" in text

    assert "PROMPTS" in text
    assert "fix_bug" in text
    assert "Use get_prompt(name, arguments)." in text


def test_manual_protects_sandbox_names() -> None:
    """Unsafe MCP tool names should use mcp_call_tool."""

    manual = MCPManual(
        instructions="",
        tools=[
            {
                "name": "bad-tool",
                "description": "",
                "inputSchema": {
                    "properties": {},
                    "required": [],
                },
            },
            {
                "name": "final_answer",
                "description": "",
                "inputSchema": {
                    "properties": {},
                    "required": [],
                },
            },
        ],
        resources=[],
        resource_templates=[],
        prompts=[],
    )

    text = manual.as_text()

    assert "Tool: bad-tool" in text
    assert "Tool: final_answer" in text

    assert text.count(
        "Call with mcp_call_tool(name, arguments)."
    ) == 2

    assert (
        "final_answer is provided by the sandbox "
        "and is never replaced by an MCP tool."
        in text
    )


def test_manual_accepts_empty_capabilities() -> None:
    """An MCP server may advertise no optional capabilities."""

    manual = MCPManual(
        instructions="",
        tools=[],
        resources=[],
        resource_templates=[],
        prompts=[],
    )

    text = manual.as_text()

    assert "TOOLS" in text
    assert "RESOURCES" in text
    assert "RESOURCE TEMPLATES" in text
    assert "PROMPTS" in text
