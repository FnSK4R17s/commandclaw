"""Unit tests for commandclaw.mcp.tools — JSON Schema → Pydantic → StructuredTool."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from commandclaw.mcp.client import MCPClient, MCPToolDef
from commandclaw.mcp.tools import _build_input_model, create_mcp_tools

# ============================================================
# _build_input_model — schema fidelity
# ============================================================


def _tool(name: str, schema: dict) -> MCPToolDef:
    return MCPToolDef(name=name, description="", input_schema=schema)


def test_build_model_handles_required_string() -> None:
    model = _build_input_model(_tool("search", {
        "type": "object",
        "properties": {"q": {"type": "string"}},
        "required": ["q"],
    }))
    instance = model(q="hello")
    assert instance.q == "hello"

    with pytest.raises(Exception):  # noqa: PT011 — pydantic ValidationError
        model()  # missing required field


def test_build_model_handles_optional_field() -> None:
    model = _build_input_model(_tool("search", {
        "type": "object",
        "properties": {
            "q": {"type": "string"},
            "limit": {"type": "integer"},
        },
        "required": ["q"],
    }))
    instance = model(q="x")
    assert instance.limit is None
    instance2 = model(q="x", limit=10)
    assert instance2.limit == 10


@pytest.mark.parametrize("json_type,value", [
    ("string", "hello"),
    ("integer", 42),
    ("number", 3.14),
    ("boolean", True),
    ("object", {"k": "v"}),
    ("array", [1, 2, 3]),
])
def test_build_model_maps_json_types(json_type: str, value) -> None:
    model = _build_input_model(_tool("t", {
        "type": "object",
        "properties": {"x": {"type": json_type}},
        "required": ["x"],
    }))
    instance = model(x=value)
    assert instance.x == value


def test_build_model_unknown_type_falls_back_to_any() -> None:
    model = _build_input_model(_tool("t", {
        "type": "object",
        "properties": {"x": {"type": "weird"}},
        "required": ["x"],
    }))
    # Any → accepts anything without raising
    assert model(x={"nested": [1]}).x == {"nested": [1]}


def test_build_model_empty_schema_yields_empty_model() -> None:
    model = _build_input_model(_tool("t", {}))
    assert model() is not None


# ============================================================
# create_mcp_tools — wraps client.call_tool with mcp_<name>
# ============================================================


async def test_create_mcp_tools_wraps_each_tool_def() -> None:
    client = MCPClient(gateway_url="http://gateway/mcp")
    client.list_tools = AsyncMock(return_value=[
        _tool("search", {
            "type": "object",
            "properties": {"q": {"type": "string"}},
            "required": ["q"],
        }),
        _tool("ping", {"type": "object", "properties": {}}),
    ])

    tools = await create_mcp_tools(client)

    names = [t.name for t in tools]
    assert names == ["mcp_search", "mcp_ping"]


async def test_create_mcp_tools_returns_empty_when_list_fails() -> None:
    client = MCPClient(gateway_url="http://gateway/mcp")
    client.list_tools = AsyncMock(side_effect=RuntimeError("gateway down"))

    tools = await create_mcp_tools(client)
    assert tools == []


async def test_wrapped_tool_invokes_call_tool_with_kwargs() -> None:
    client = MCPClient(gateway_url="http://gateway/mcp")
    client.list_tools = AsyncMock(return_value=[
        _tool("search", {
            "type": "object",
            "properties": {"q": {"type": "string"}},
            "required": ["q"],
        }),
    ])
    client.call_tool = AsyncMock(return_value="search-result")

    tools = await create_mcp_tools(client)
    result = await tools[0].ainvoke({"q": "hello"})

    assert result == "search-result"
    client.call_tool.assert_awaited_once_with("search", {"q": "hello"})
