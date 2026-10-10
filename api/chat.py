"""POST /api/chat - Server-Sent Events stream (spec section 10 event types).

The orchestrator owns the model loop; this module only validates input and
formats SSE frames.
"""
from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from api.orchestrator import run_turn
from api.prompt_loader import load_core_prompt, operator_context

logger = logging.getLogger(__name__)

MAX_MESSAGE_CHARS = 8000

router = APIRouter()


def sse(event: str, data: dict) -> str:
    """Format one Server-Sent Event frame."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post("/api/chat")
async def chat(request: Request) -> StreamingResponse:
    settings = request.app.state.settings

    # Fail closed: no model calls without configured secrets.
    if not settings.secrets_ready:
        raise HTTPException(status_code=503, detail="Secrets not configured - see /api/health")

    # M1.3: reject non-JSON bodies at the boundary.
    content_type = request.headers.get("content-type", "")
    if "application/json" not in content_type:
        raise HTTPException(status_code=415, detail="Content-Type must be application/json")

    try:
        body = await request.json()
    except Exception as exc:  # noqa: BLE001 - malformed JSON
        raise HTTPException(status_code=400, detail="Body must be valid JSON") from exc

    message = (body or {}).get("message", "")
    if not isinstance(message, str) or not message.strip():
        raise HTTPException(status_code=400, detail="Body must include a non-empty 'message'")
    if len(message) > MAX_MESSAGE_CHARS:
        raise HTTPException(status_code=413, detail=f"Message too long (max {MAX_MESSAGE_CHARS} chars)")

    client = request.app.state.gemini_client()
    tools = await request.app.state.ensure_tools()

    async def event_stream() -> AsyncIterator[str]:
        try:
            async for event_name, data in run_turn(
                gemini_client=client,
                model=settings.gemini_model,
                fallback_model=settings.gemini_model_fallback,
                system_prompt=load_core_prompt() + operator_context(settings.default_calendar_id),
                message=message,
                tools=tools,
                mcp=request.app.state.mcp_client,
                classes=request.app.state.tool_classes,
                store=request.app.state.store,
                conversation_id=str(uuid.uuid4()),  # real conversations arrive in M6
                hash_secret=request.app.state.hash_secret,
            ):
                yield sse(event_name, data)
        except Exception:  # noqa: BLE001 - never leak internals to the client
            logger.exception("chat turn failed")
            yield sse("error", {"message": "The assistant hit an unexpected error."})

    return StreamingResponse(event_stream(), media_type="text/event-stream")
