"""Unit tests for commandclaw.mcp.client — uses httpx.MockTransport.

No network. Each test scripts the gateway responses and asserts the JSON-RPC
contract: payload shape, header propagation, error mapping, SSE parsing.
"""

from __future__ import annotations

import json

import httpx
import pytest

from commandclaw.mcp.client import (
    MCPAgentNotEnrolledError,
    MCPClient,
    MCPGatewayUnavailableError,
    _extract_text,
    _parse_sse_response,
)

# ============================================================
# Pure helpers
# ============================================================


def test_parse_sse_response_extracts_json() -> None:
    sse = "event: message\ndata: {\"jsonrpc\":\"2.0\",\"id\":1,\"result\":{\"x\":1}}\n\n"
    assert _parse_sse_response(sse)["result"] == {"x": 1}


def test_parse_sse_response_raises_when_no_data_line() -> None:
    with pytest.raises(RuntimeError, match="No data line"):
        _parse_sse_response("event: message\n\n")


def test_extract_text_concatenates_text_blocks() -> None:
    blocks = [
        {"type": "text", "text": "first"},
        {"type": "image", "data": "..."},
        {"type": "text", "text": "second"},
    ]
    assert _extract_text(blocks) == "first\nsecond"


def test_extract_text_returns_empty_when_no_text_blocks() -> None:
    assert _extract_text([{"type": "image"}]) == ""
    assert _extract_text([]) == ""


# ============================================================
# Connection bootstrap
# ============================================================


def _make_client_with_transport(
    handler, *, gateway_url: str = "http://gateway/mcp", agent_id: str = "agent-1"
) -> MCPClient:
    """Build an MCPClient with its `_http` pre-set to a MockTransport client."""
    client = MCPClient(gateway_url=gateway_url, agent_id=agent_id)
    transport = httpx.MockTransport(handler)
    client._http = httpx.AsyncClient(transport=transport)
    return client


async def test_bootstrap_session_raises_when_unenrolled() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "agent unknown"})

    client = _make_client_with_transport(handler)
    with pytest.raises(MCPAgentNotEnrolledError, match="agent unknown"):
        await client._bootstrap_session()
    await client._http.aclose()


async def test_bootstrap_session_raises_when_unreachable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("name resolution failed")

    client = _make_client_with_transport(handler)
    with pytest.raises(MCPGatewayUnavailableError, match="Cannot reach"):
        await client._bootstrap_session()
    await client._http.aclose()


async def test_bootstrap_session_returns_session_on_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body == {"agent_id": "agent-1"}
        return httpx.Response(200, json={
            "phantom_token": "tok",
            "hmac_key": "hmac",
            "expires_at": "2099-01-01",
            "agent_id": "agent-1",
        })

    client = _make_client_with_transport(handler)
    session = await client._bootstrap_session()
    assert session.phantom_token == "tok"
    assert session.agent_id == "agent-1"
    await client._http.aclose()


# ============================================================
# JSON-RPC envelope + auth headers
# ============================================================


async def test_jsonrpc_sends_correct_payload_and_returns_result() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={
            "jsonrpc": "2.0",
            "id": captured["body"]["id"],
            "result": {"value": 42},
        })

    client = MCPClient(gateway_url="http://gateway/mcp", agent_key="secret")
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = await client._jsonrpc("ping", {"hello": "world"})

    assert result == {"value": 42}
    assert captured["body"]["jsonrpc"] == "2.0"
    assert captured["body"]["method"] == "ping"
    assert captured["body"]["params"] == {"hello": "world"}
    assert captured["auth"] == "Bearer secret"
    await client._http.aclose()


async def test_jsonrpc_raises_on_error_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(200, json={
            "jsonrpc": "2.0",
            "id": body["id"],
            "error": {"code": -32601, "message": "method not found"},
        })

    client = MCPClient(gateway_url="http://gateway/mcp")
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(RuntimeError, match=r"-32601.*method not found"):
        await client._jsonrpc("missing")
    await client._http.aclose()


async def test_jsonrpc_parses_sse_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        sse = (
            f"event: message\ndata: "
            f"{{\"jsonrpc\":\"2.0\",\"id\":{body['id']},\"result\":{{\"sse\":true}}}}\n\n"
        )
        return httpx.Response(
            200,
            text=sse,
            headers={"content-type": "text/event-stream"},
        )

    client = MCPClient(gateway_url="http://gateway/mcp")
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = await client._jsonrpc("ping")
    assert result == {"sse": True}
    await client._http.aclose()


async def test_jsonrpc_captures_session_id_header() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": body["id"], "result": {}},
            headers={"mcp-session-id": "sess-abc"},
        )

    client = MCPClient(gateway_url="http://gateway/mcp")
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await client._jsonrpc("ping")
    assert client._mcp_session_id == "sess-abc"
    await client._http.aclose()


# ============================================================
# tools/list and tools/call
# ============================================================


async def test_list_tools_parses_tool_defs() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(200, json={
            "jsonrpc": "2.0",
            "id": body["id"],
            "result": {"tools": [
                {
                    "name": "search",
                    "description": "Search the web",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"q": {"type": "string"}},
                        "required": ["q"],
                    },
                },
                {"name": "noop"},
            ]},
        })

    client = MCPClient(gateway_url="http://gateway/mcp")
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    tools = await client.list_tools()

    assert len(tools) == 2
    assert tools[0].name == "search"
    assert tools[0].description == "Search the web"
    assert tools[0].input_schema["required"] == ["q"]
    assert tools[1].name == "noop"
    assert tools[1].description == ""
    assert tools[1].input_schema == {}
    await client._http.aclose()


async def test_call_tool_extracts_text_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(200, json={
            "jsonrpc": "2.0",
            "id": body["id"],
            "result": {"content": [
                {"type": "text", "text": "result A"},
                {"type": "text", "text": "result B"},
            ]},
        })

    client = MCPClient(gateway_url="http://gateway/mcp")
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    out = await client.call_tool("search", {"q": "hello"})
    assert out == "result A\nresult B"
    await client._http.aclose()


async def test_call_tool_raises_on_isError_flag() -> None:  # noqa: N802 — matches MCP field name
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(200, json={
            "jsonrpc": "2.0",
            "id": body["id"],
            "result": {
                "isError": True,
                "content": [{"type": "text", "text": "rate limit hit"}],
            },
        })

    client = MCPClient(gateway_url="http://gateway/mcp")
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(RuntimeError, match="rate limit hit"):
        await client.call_tool("search", {})
    await client._http.aclose()
