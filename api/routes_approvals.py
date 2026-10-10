"""POST /api/approvals/{id} - approve, reject, or edit a pending action (spec 6.2).

Integrity rules (CodeReviewer findings 1, 2, 5 + M3.7 review):
- Single-use state machine enforced at the storage layer (status-guarded UPDATE);
  expiry enforced here at decision time.
- Approve executes EXACTLY the stored args after re-verifying the HMAC.
- Edit validates the new args against the tool schema, re-hashes, audits
  original vs edited, and keeps the action pending.
- Only the approved tool's tool_result resolves the pending action (a follow-up
  auto-read must not misattribute audit rows or flip the status).
"""
from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from api.approvals import compute_args_hash, is_expired, verify_args_hash
from api.chat import sse
from api.mcp_client import McpError
from api.orchestrator import resume_after_approval
from api.policy import validate_args
from api.prompt_loader import load_core_prompt, operator_context
from api.store import EXPIRED, PENDING, REJECTED

logger = logging.getLogger(__name__)

router = APIRouter()


def _tool_schema(request: Request, tool_name: str) -> dict | None:
    for tool in request.app.state.zapier_tools:
        if tool.name == tool_name:
            return tool.input_schema
    return None


@router.post("/api/approvals/{pending_id}")
async def decide(pending_id: str, request: Request) -> object:
    settings = request.app.state.settings
    store = request.app.state.store
    mcp = request.app.state.mcp_client

    if mcp is None:
        raise HTTPException(status_code=503, detail="Zapier is not configured")

    try:
        body = await request.json()
    except Exception as exc:  # noqa: BLE001 - malformed JSON
        raise HTTPException(status_code=400, detail="Body must be valid JSON") from exc

    action = (body or {}).get("action")
    pending = store.get_pending_action(pending_id)
    if pending is None:
        raise HTTPException(status_code=404, detail="Unknown approval id")
    if pending["status"] != PENDING:
        raise HTTPException(status_code=409, detail=f"Approval already {pending['status']}")
    if is_expired(pending["expires_at"]):
        store.set_pending_status(pending_id, EXPIRED)
        store.audit(tool=pending["tool"], args_json=pending["args_json"], status="expired")
        raise HTTPException(status_code=410, detail="Approval expired - discard and ask again")

    if action == "edit":
        new_args = (body or {}).get("args")
        errors = validate_args(new_args, _tool_schema(request, pending["tool"]))
        if errors:
            raise HTTPException(status_code=422, detail="; ".join(errors))
        new_hash = compute_args_hash(
            pending_id, pending["tool"], new_args, request.app.state.hash_secret
        )
        store.update_pending_args(pending_id, new_args, new_hash)
        store.audit(
            tool=pending["tool"],
            args_json=json.dumps(
                {"original": json.loads(pending["args_json"]), "edited": new_args},
                ensure_ascii=False,
            ),
            status="edited",
        )
        return {"status": PENDING, "args": new_args}

    if action == "reject":
        # Storage-level single-use: the UPDATE only lands from 'pending'.
        if not store.set_pending_status(pending_id, REJECTED):
            raise HTTPException(status_code=409, detail="Approval already processed")
        store.audit(tool=pending["tool"], args_json=pending["args_json"], status="rejected")
        return {"status": "rejected"}

    if action == "approve":
        args = json.loads(pending["args_json"])
        if not verify_args_hash(
            pending_id, pending["tool"], args, request.app.state.hash_secret, pending["args_hash"]
        ):
            store.set_pending_status(pending_id, REJECTED)
            store.audit(tool=pending["tool"], args_json=pending["args_json"], status="hash_mismatch")
            raise HTTPException(status_code=409, detail="Stored arguments do not match their hash")

        # Storage-level single-use claim (M3.7): two concurrent approves cannot
        # both pass - the second UPDATE matches no 'pending' row.
        if not store.set_pending_status(pending_id, "approved"):
            raise HTTPException(status_code=409, detail="Approval already processed")

        async def continuation() -> AsyncIterator[str]:
            # Audit BEFORE execution, then record the outcome (finding 9).
            store.audit(tool=pending["tool"], args_json=pending["args_json"], status="running")
            resolved = False
            try:
                async for event_name, data in resume_after_approval(
                    pending,
                    request.app.state.gemini_client(),
                    settings.gemini_model,
                    settings.gemini_model_fallback,
                    load_core_prompt() + operator_context(settings.default_calendar_id),
                    request.app.state.zapier_tools,
                    mcp,
                    request.app.state.tool_classes,
                ):
                    # Only the approved tool's result resolves the action; a
                    # follow-up auto-read's tool_result must not touch it.
                    if (
                        event_name == "tool_result"
                        and data.get("tool") == pending["tool"]
                        and not resolved
                    ):
                        resolved = True
                        succeeded = bool(data.get("ok"))
                        store.set_pending_status(
                            pending_id,
                            "executed" if succeeded else "failed",
                            from_status="approved",
                        )
                        store.audit(
                            tool=pending["tool"],
                            args_json=pending["args_json"],
                            status="executed" if succeeded else "failed",
                            tasks_used=2 if succeeded else 0,
                        )
                    elif event_name == "error" and not resolved:
                        # Refused tool / model-call limit before execution:
                        # never leave the action stuck at 'approved'.
                        resolved = True
                        store.set_pending_status(pending_id, "failed", from_status="approved")
                        store.audit(
                            tool=pending["tool"],
                            args_json=pending["args_json"],
                            status="failed",
                            error=str(data.get("message", ""))[:500],
                        )
                    yield sse(event_name, data)
            except McpError as exc:
                if not resolved:
                    store.set_pending_status(pending_id, "failed", from_status="approved")
                    store.audit(
                        tool=pending["tool"],
                        args_json=pending["args_json"],
                        status="failed",
                        error=str(exc),
                    )
                yield sse("error", {"message": str(exc)})
            except Exception:  # noqa: BLE001 - never leak internals; never stick at 'approved'
                logger.exception("approval continuation failed")
                if not resolved:
                    store.set_pending_status(pending_id, "failed", from_status="approved")
                    store.audit(
                        tool=pending["tool"],
                        args_json=pending["args_json"],
                        status="failed",
                        error="unexpected error",
                    )
                yield sse("error", {"message": "The action hit an unexpected error."})

        return StreamingResponse(continuation(), media_type="text/event-stream")

    raise HTTPException(status_code=400, detail="action must be approve, reject, or edit")
