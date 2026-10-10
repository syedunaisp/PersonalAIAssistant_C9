"""Connectivity checks for /api/health.

Zapier check runs MCP list_tools ONLY (free per Zapier docs) - never executes an action.
Error details are sanitized: exception TYPE only reaches the client (M3.7 review -
matches mcp_client.py); the full exception is logged server-side, never the token.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

ZAPIER_MCP_URL = "https://mcp.zapier.com/api/v1/connect"
_TIMEOUT_SECONDS = 20.0


@dataclass(frozen=True)
class HealthResult:
    service: str
    ok: bool
    detail: str


def check_gemini(api_key: str, model: str) -> HealthResult:
    """One tiny live generate call (free tier). Returns an honest result, never a guess."""
    if not api_key.strip():
        return HealthResult("gemini", False, "GEMINI_API_KEY not set")
    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model,
            contents="Reply with the single word OK",
            # M3.8: gemini-3.x models think by default (dynamic budget) - a
            # tiny output cap yielded empty replies. Disable thinking and give
            # a small but sufficient budget so the check is deterministic.
            config=types.GenerateContentConfig(
                max_output_tokens=200,
                temperature=0,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        text = (response.text or "").strip()
        return HealthResult("gemini", bool(text), f"model={model} replied: {text[:40]}")
    except Exception as exc:  # noqa: BLE001 - boundary: report type, never the key
        logger.warning("gemini health check failed: %s", exc)  # server-side only
        return HealthResult("gemini", False, type(exc).__name__)


async def check_zapier(token: str) -> HealthResult:
    """MCP list_tools over Streamable HTTP with Bearer auth. No actions are executed."""
    if not token.strip():
        return HealthResult("zapier", False, "ZAPIER_MCP_TOKEN not set")
    try:
        transport = StreamableHttpTransport(
            ZAPIER_MCP_URL,
            headers={"Authorization": f"Bearer {token}"},
        )
        async with Client(transport=transport) as client:
            tools = await asyncio.wait_for(client.list_tools(), timeout=_TIMEOUT_SECONDS)
        names = [tool.name for tool in tools]
        preview = ", ".join(names[:5]) + ("..." if len(names) > 5 else "")
        return HealthResult("zapier", True, f"{len(names)} tools available: {preview}")
    except Exception as exc:  # noqa: BLE001 - boundary: report type, never the token
        logger.warning("zapier health check failed: %s", exc)  # server-side only
        return HealthResult("zapier", False, type(exc).__name__)
