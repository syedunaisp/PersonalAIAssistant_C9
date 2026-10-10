"""Orchestrator: the model loop with Zapier tools (spec section 5).

Security invariants (non-negotiable):
- Automatic function calling is DISABLED: the model can never execute a tool
  by itself. Every function call is classified by the policy layer first.
- read -> executed via the MCP client, result fed back to the model.
- write / destructive / unlisted -> pending_action saved, approval_required
  event emitted, turn STOPS. Execution happens only after /api/approvals.
- At most MAX_MODEL_CALLS model calls per turn (R4) and MAX_READ_EXECUTES
  read executions per turn (CodeReviewer finding 3).
- Zapier management meta-tools are never offered to the model (spec 6.3 step 4).
"""
from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

from google.genai import types

from api.approvals import compute_args_hash
from api.gemini_client import GeminiUnavailable, stream_raw_with_fallback
from api.mcp_client import McpClient, McpError, McpTool
from api.policy import READ, classify
from api.store import Store, load_contents

MAX_MODEL_CALLS = 6  # R4
MAX_READ_EXECUTES = 2  # CodeReviewer finding 3: cap auto-reads per turn
ESTIMATED_COST_TASKS = 2  # one successful Zapier call = 2 tasks

# Management meta-tools: never exposed to the model (spec 6.3 step 4).
# M3.7 review: also block Zapier's agentic meta-executors and connection
# managers, and re-check at the gate and execute time, not just declaration time.
FORBIDDEN_TOOL_PATTERNS = (
    "enable_zapier",
    "disable_zapier",
    "auto_provision",
    "manage_zapier",
    "zapier_skill",
    "write_code_action",
    "send_feedback",
    "workflow",
    "get_configuration_url",
    "discover_zapier",
    "inspect_zapier",
    "execute_zapier",
    "list_zapier",
    "connection",
    # M3.8: real Zapier server meta-tools observed in Managed mode.
    "dynamic_properties",
    "dynamic_enum",
)


def is_allowed_tool(name: str) -> bool:
    """Management meta-tools must never reach the model."""
    lowered = name.lower()
    return not any(pattern in lowered for pattern in FORBIDDEN_TOOL_PATTERNS)


# Keys Gemini's types.Schema accepts. Zapier's live schemas carry extras
# ($schema, _meta with dynamic-enum annotations) that fail model_validate -
# M3.8: strip everything not in this whitelist, recursively.
# NOTE: additionalProperties is accepted by the SDK model but the REST API
# rejects its serialized form ("Unknown name additional_properties") - so it
# must be stripped too.
_GEMINI_SCHEMA_KEYS = {
    "type",
    "format",
    "description",
    "nullable",
    "enum",
    "required",
    "properties",
    "items",
    "minItems",
    "maxItems",
    "anyOf",
}


def _clean_schema(schema: object) -> dict:
    """Recursive whitelist-copy of a JSON schema for Gemini's Schema model."""
    if not isinstance(schema, dict):
        return {}
    cleaned = {key: value for key, value in schema.items() if key in _GEMINI_SCHEMA_KEYS}
    props = cleaned.get("properties")
    if isinstance(props, dict):
        cleaned["properties"] = {
            name: _clean_schema(sub) if isinstance(sub, dict) else {}
            for name, sub in props.items()
        }
    items = cleaned.get("items")
    if isinstance(items, dict):
        cleaned["items"] = _clean_schema(items)
    any_of = cleaned.get("anyOf")
    if isinstance(any_of, list):
        cleaned["anyOf"] = [_clean_schema(sub) for sub in any_of if isinstance(sub, dict)]
    return cleaned


def build_function_declarations(tools: list[McpTool]) -> list[types.FunctionDeclaration]:
    """Convert MCP tool schemas to Gemini function declarations, minus forbidden tools."""
    declarations: list[types.FunctionDeclaration] = []
    for tool in tools:
        if not is_allowed_tool(tool.name):
            continue
        parameters = types.Schema.model_validate(_clean_schema(tool.input_schema)) if tool.input_schema else None
        declarations.append(
            types.FunctionDeclaration(
                name=tool.name,
                description=tool.description or tool.name,
                parameters=parameters,
            )
        )
    return declarations


def _build_config(system_prompt: str, tools: list[McpTool]) -> types.GenerateContentConfig:
    declarations = build_function_declarations(tools)
    return types.GenerateContentConfig(
        system_instruction=system_prompt,
        temperature=0.7,
        # SECURITY: AFC disabled - the model must never execute tools itself.
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        tools=[types.Tool(function_declarations=declarations)] if declarations else None,
    )


async def _model_loop(
    gemini_client: Any,
    model: str,
    fallback_model: str,
    config: types.GenerateContentConfig,
    contents: list[types.Content],
    mcp: McpClient | None,
    classes: dict[str, str],
    store: Store | None,
    conversation_id: str,
    hash_secret: str,
    model_calls: int,
    read_executes: int,
) -> AsyncIterator[tuple[str, dict]]:
    """The shared loop: stream, classify, execute reads, gate everything else."""
    while model_calls < MAX_MODEL_CALLS:
        model_calls += 1
        function_calls: list[Any] = []
        raw_function_parts: list[types.Part] = []
        try:
            async for chunk in stream_raw_with_fallback(
                gemini_client, model, fallback_model, config, contents
            ):
                # M3.8: prefer the raw candidate parts - gemini-3.x attaches a
                # thought_signature to function-call parts that MUST be sent
                # back verbatim, so keep the original Part objects.
                handled_raw = False
                candidates = getattr(chunk, "candidates", None)
                if candidates:
                    content = getattr(candidates[0], "content", None)
                    for part in (getattr(content, "parts", None) or []):
                        fc = getattr(part, "function_call", None)
                        if fc is not None:
                            function_calls.append(fc)
                            raw_function_parts.append(part)
                            handled_raw = True
                        else:
                            text = getattr(part, "text", None)
                            if text:
                                yield ("token", {"text": text})
                                handled_raw = True
                if not handled_raw:
                    calls = getattr(chunk, "function_calls", None) or []
                    function_calls.extend(calls)
                    text = getattr(chunk, "text", None)
                    if text:
                        yield ("token", {"text": text})
        except GeminiUnavailable as exc:
            yield ("error", {"message": str(exc)})
            return

        if not function_calls:
            yield ("done", {})
            return

        if raw_function_parts and len(raw_function_parts) == len(function_calls):
            call_parts = raw_function_parts  # signatures preserved
        else:
            # Fallback (tests/fakes): rebuild plain parts.
            call_parts = [
                types.Part(
                    function_call=types.FunctionCall(name=fc.name, args=dict(fc.args or {}))
                )
                for fc in function_calls
            ]
        contents.append(types.Content(role="model", parts=call_parts))
        response_parts: list[types.Part] = []
        stop_for_approval = False
        last_pending_id: str | None = None

        for fc in function_calls:
            args = dict(fc.args or {})
            # M3.7: a hallucinated/injected meta-tool must never reach the gate
            # or execution - refuse the whole call, audit, and stop the turn.
            if not is_allowed_tool(fc.name):
                if store is not None:
                    store.audit(
                        tool=fc.name,
                        args_json=json.dumps(args, ensure_ascii=False),
                        status="forbidden_tool_refused",
                    )
                yield ("error", {"message": "That action is not permitted for the assistant."})
                return

            classification = classify(fc.name, classes)
            yield (
                "tool_proposed",
                {
                    "tool": fc.name,
                    "classification": classification.classification,
                    "listed": classification.listed,
                    "args": args,
                },
            )

            can_auto_run = (
                classification.classification == READ
                and mcp is not None
                and read_executes < MAX_READ_EXECUTES
            )

            if can_auto_run and mcp is not None:
                read_executes += 1
                ok = True
                try:
                    result = await mcp.call_tool(fc.name, args)
                except McpError as exc:
                    # Failures cost 0 tasks; the model is told the honest result.
                    result = f"Error: {exc}"
                    ok = False
                yield ("tool_result", {"tool": fc.name, "result": result[:500], "ok": ok})
                response_parts.append(
                    types.Part.from_function_response(
                        name=fc.name, response={"result": result}
                    )
                )
            else:
                # write / destructive / unlisted / read-cap-hit -> approval gate, STOP.
                pending_id = str(uuid.uuid4())
                last_pending_id = pending_id
                if store is not None and hash_secret:
                    args_hash = compute_args_hash(pending_id, fc.name, args, hash_secret)
                    store.create_pending_action(
                        pending_id=pending_id,
                        conversation_id=conversation_id,
                        tool=fc.name,
                        args=args,
                        args_hash=args_hash,
                        classification=classification.classification,
                        contents=contents,  # snapshot BEFORE the WAITING placeholder is appended
                    )
                    store.audit(
                        tool=fc.name,
                        args_json=json.dumps(args, ensure_ascii=False),
                        status="proposed",
                    )
                yield (
                    "approval_required",
                    {
                        "pending_action_id": pending_id,
                        "tool": fc.name,
                        "classification": classification.classification,
                        "listed": classification.listed,
                        "args": args,
                        "estimated_cost_tasks": ESTIMATED_COST_TASKS,
                    },
                )
                response_parts.append(
                    types.Part.from_function_response(
                        name=fc.name,
                        response={"result": "WAITING_FOR_USER_APPROVAL"},
                    )
                )
                stop_for_approval = True

        # M3.8: gemini-3.x has no 'tool' role - function responses ride in a
        # 'user' turn (valid roles: SYSTEM, USER, MODEL, ...).
        contents.append(types.Content(role="user", parts=response_parts))

        if stop_for_approval:
            yield ("done", {"stopped_for_approval": True, "pending_action_id": last_pending_id})
            return

    yield ("error", {"message": "Stopped after the model-call limit for this turn."})


async def run_turn(
    gemini_client: Any,
    model: str,
    fallback_model: str,
    system_prompt: str,
    message: str,
    tools: list[McpTool],
    mcp: McpClient | None,
    classes: dict[str, str],
    store: Store | None = None,
    conversation_id: str = "",
    hash_secret: str = "",
) -> AsyncIterator[tuple[str, dict]]:
    """Run one fresh user turn. Yields (event_name, data) pairs for the SSE layer."""
    config = _build_config(system_prompt, tools)
    contents: list[types.Content] = [
        types.Content(role="user", parts=[types.Part(text=message)])
    ]
    async for event in _model_loop(
        gemini_client, model, fallback_model, config, contents, mcp, classes,
        store, conversation_id, hash_secret, model_calls=0, read_executes=0,
    ):
        yield event


async def resume_after_approval(
    pending: dict,
    gemini_client: Any,
    model: str,
    fallback_model: str,
    system_prompt: str,
    tools: list[McpTool],
    mcp: McpClient | None,
    classes: dict[str, str],
) -> AsyncIterator[tuple[str, dict]]:
    """Execute the approved call with EXACTLY the stored args, then continue the loop."""
    tool = pending["tool"]
    args = json.loads(pending["args_json"])
    stored_contents = load_contents(pending["contents_json"])
    contents = [types.Content.model_validate(item) for item in stored_contents]

    # M3.7: defense in depth - never execute a meta-tool even if one somehow
    # reached the store (the gate refuses them first).
    if not is_allowed_tool(tool):
        yield ("error", {"message": "That action is not permitted for the assistant."})
        return

    ok = True
    try:
        result = await mcp.call_tool(tool, args) if mcp else "Error: MCP client unavailable"
    except McpError as exc:
        result = f"Error: {exc}"
        ok = False

    yield ("tool_result", {"tool": tool, "result": result[:500], "ok": ok})
    contents.append(
        types.Content(
            # M3.8: gemini-3.x has no 'tool' role - use 'user'.
            role="user",
            parts=[types.Part.from_function_response(name=tool, response={"result": result})],
        )
    )

    config = _build_config(system_prompt, tools)
    async for event in _model_loop(
        gemini_client, model, fallback_model, config, contents, mcp, classes,
        store=None, conversation_id=str(pending["conversation_id"]), hash_secret="",
        model_calls=0, read_executes=0,
    ):
        yield event
