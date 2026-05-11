"""Tests for MCP server integration in ask."""

import json

import pytest

from reasons_lib.ask import (
    _build_tools_section,
    _build_mcp_instructions,
    build_ask_prompt,
    extract_tool_call,
)


class FakeBridge:
    """Minimal McpBridge substitute for testing."""

    def __init__(self, tools=None, instructions=""):
        self._tools = tools or []
        self._instructions = instructions

    def list_tools(self):
        return self._tools

    def get_instructions(self):
        return self._instructions

    def call_tool(self, name, arguments):
        return json.dumps({"tool": name, "args": arguments, "result": "ok"})


class TestBuildToolsSection:

    def test_no_mcp_servers(self):
        section = _build_tools_section([])
        assert "search_beliefs" in section

    def test_includes_mcp_tools(self):
        bridge = FakeBridge(tools=[
            {
                "name": "execute_query",
                "description": "Execute a read-only SQL query",
                "input_schema": {
                    "properties": {
                        "sql": {"description": "A single SELECT statement", "type": "string"}
                    }
                },
            }
        ])
        section = _build_tools_section([bridge])
        assert "search_beliefs" in section
        assert "execute_query" in section
        assert "SELECT" in section

    def test_multiple_servers(self):
        b1 = FakeBridge(tools=[
            {"name": "tool_a", "description": "Tool A", "input_schema": {"properties": {}}},
        ])
        b2 = FakeBridge(tools=[
            {"name": "tool_b", "description": "Tool B", "input_schema": {"properties": {}}},
        ])
        section = _build_tools_section([b1, b2])
        assert "tool_a" in section
        assert "tool_b" in section

    def test_no_params_no_trailing_comma(self):
        bridge = FakeBridge(tools=[
            {"name": "list_tables", "description": "List tables", "input_schema": {"properties": {}}},
        ])
        section = _build_tools_section([bridge])
        assert '{"tool": "list_tables"}' in section
        assert '{"tool": "list_tables", }' not in section


class TestBuildMcpInstructions:

    def test_no_instructions(self):
        bridge = FakeBridge(instructions="")
        result = _build_mcp_instructions([bridge])
        assert result == ""

    def test_collects_instructions(self):
        b1 = FakeBridge(instructions="Use mart X for sales data")
        b2 = FakeBridge(instructions="Use API Y for user data")
        result = _build_mcp_instructions([b1, b2])
        assert "mart X" in result
        assert "API Y" in result


class TestAskPromptWithMcp:

    def test_default_tools_section(self):
        prompt = build_ask_prompt("question", "context")
        assert "one tool available" in prompt

    def test_custom_tools_section(self):
        prompt = build_ask_prompt("question", "context",
                                  tools_section="Custom tools here")
        assert "Custom tools here" in prompt
        assert "one tool available" not in prompt

    def test_mcp_instructions_injected(self):
        prompt = build_ask_prompt("question", "context",
                                  mcp_instructions="Use snowflake for queries")
        assert "Data Source Instructions" in prompt
        assert "Use snowflake for queries" in prompt

    def test_no_mcp_instructions(self):
        prompt = build_ask_prompt("question", "context", mcp_instructions="")
        assert "Data Source Instructions" not in prompt


class TestExtractToolCallMcp:

    def test_mcp_tool_call(self):
        text = '{"tool": "execute_query", "sql": "SELECT 1"}'
        result = extract_tool_call(text)
        assert result["tool"] == "execute_query"
        assert result["sql"] == "SELECT 1"

    def test_search_beliefs_unchanged(self):
        text = '{"tool": "search_beliefs", "query": "retraction"}'
        result = extract_tool_call(text)
        assert result["tool"] == "search_beliefs"
        assert result["query"] == "retraction"
