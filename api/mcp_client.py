"""Zapier MCP client (Streamable HTTP + Bearer token, per official Zapier docs).

Cost rules (PLAN section 5): list_tools is free per official docs; call_tool
executes ONE action - a successful call spends 2 of the 100 monthly tasks.
Never call call_tool without the policy layer and (for writes) user approval.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Protocol

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

ZAPIER_MCP_URL = "https://mcp.zapier.com/api/v1/connect"
_CALL_TIMEOUT_SECONDS = 60.0


class McpError(Exception):
    """MCP call failed. Failed calls cost 0 tasks (per Zapier docs)."""


@dataclass(frozen=True)
class McpTool:
    name: str
    description: str
    input_schema: dict = field(default_factory=dict)


class McpClient(Protocol):
    """Interface both the real client and the test fake implement."""

    async def list_tools(self) -> list[McpTool]: ...

    async def call_tool(self, name: str, arguments: dict) -> str: ...


class ZapierMcpClient:
    """Real MCP client. Connects per operation (short-lived sessions)."""

    def __init__(self, token: str) -> None:
        self._transport = StreamableHttpTransport(
            ZAPIER_MCP_URL,
            headers={"Authorization": f"Bearer {token}"},
        )

    async def list_tools(self) -> list[McpTool]:
        try:
            async with Client(transport=self._transport) as client:
                tools = await asyncio.wait_for(client.list_tools(), timeout=_CALL_TIMEOUT_SECONDS)
        except Exception as exc:  # noqa: BLE001 - boundary: wrap, never leak the token
            raise McpError(f"Zapier MCP list_tools failed ({type(exc).__name__}).") from exc
        return [
            McpTool(
                name=tool.name,
                description=getattr(tool, "description", "") or "",
                input_schema=getattr(tool, "inputSchema", {}) or {},
            )
            for tool in tools
        ]

    async def call_tool(self, name: str, arguments: dict) -> str:
        """Execute ONE tool call. Successful calls cost 2 tasks; failures cost 0."""
        try:
            async with Client(transport=self._transport) as client:
                result = await asyncio.wait_for(
                    client.call_tool(name, arguments), timeout=_CALL_TIMEOUT_SECONDS
                )
        except Exception as exc:  # noqa: BLE001 - boundary: wrap, never leak the token
            raise McpError(f"Zapier MCP call '{name}' failed ({type(exc).__name__}).") from exc
        # M3.8: fastmcp v2 returns a CallToolResult object (not an iterable).
        # Text lives in result.content blocks; .data carries the parsed payload.
        parts: list[str] = []
        for block in getattr(result, "content", None) or []:
            text = getattr(block, "text", None)
            if text:
                parts.append(text)
        if not parts:
            data = getattr(result, "data", None)
            if data is not None:
                parts.append(str(data))
        return "\n".join(parts) if parts else "(no text content returned)"
