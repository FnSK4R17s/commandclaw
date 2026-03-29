"""Wrap MCP tools as LangChain tools for the AgentExecutor."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from pydantic import Field, create_model

from commandclaw.mcp.client import MCPClient, MCPToolDef

log = logging.getLogger(__name__)

# JSON Schema type → Python type mapping
_JSON_TYPE_MAP: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "object": dict,
    "array": list,
}


def _build_input_model(tool_def: MCPToolDef) -> type:
    """Build a Pydantic model from a JSON Schema ``inputSchema``.

    Handles required vs optional fields and maps JSON Schema types to Python
    types.  Unknown or missing types default to ``Any``.
    """
    schema = tool_def.input_schema
    properties: dict[str, Any] = schema.get("properties", {})
    required_fields: set[str] = set(schema.get("required", []))

    field_definitions: dict[str, Any] = {}
    for name, prop in properties.items():
        json_type = prop.get("type", "")
        py_type = _JSON_TYPE_MAP.get(json_type, Any)
        description = prop.get("description", "")

        if name in required_fields:
            field_definitions[name] = (
                py_type,
                Field(description=description),
            )
        else:
            field_definitions[name] = (
                Optional[py_type],
                Field(default=None, description=description),
            )

    model_name = f"MCPInput_{tool_def.name}"
    return create_model(model_name, **field_definitions)  # type: ignore[call-overload]


async def create_mcp_tools(client: MCPClient) -> list[Any]:
    """Discover MCP tools and wrap each as a LangChain ``StructuredTool``.

    Returns an empty list when:
    - The MCP gateway is not configured (client is ``None``).
    - The gateway is unreachable or returns an error.

    This allows the agent to keep working without MCP tools.
    """
    # Lazy import so the module can be loaded without langchain installed.
    from langchain_core.tools import StructuredTool

    try:
        tool_defs = await client.list_tools()
    except Exception:
        log.exception("Failed to list MCP tools — agent will run without them")
        return []

    tools: list[StructuredTool] = []
    for tool_def in tool_defs:
        lc_tool = _wrap_tool(client, tool_def, StructuredTool)
        tools.append(lc_tool)
        log.debug("Registered LangChain tool: %s", lc_tool.name)

    log.info("Created %d LangChain tool(s) from MCP gateway", len(tools))
    return tools


def _wrap_tool(
    client: MCPClient,
    tool_def: MCPToolDef,
    StructuredTool: type,
) -> Any:
    """Create a single LangChain StructuredTool from an MCPToolDef."""
    input_model = _build_input_model(tool_def)
    # Prefix with mcp_ to avoid name collisions with built-in tools.
    lc_name = f"mcp_{tool_def.name}"

    # Capture tool_def.name in the closure (not the loop variable).
    mcp_name = tool_def.name

    async def _invoke(**kwargs: Any) -> str:
        return await client.call_tool(mcp_name, kwargs)

    return StructuredTool.from_function(
        coroutine=_invoke,
        name=lc_name,
        description=tool_def.description,
        args_schema=input_model,
    )
