"""Orchestrator tests. All Zapier and Gemini calls are faked - zero real calls."""
from __future__ import annotations

import pytest

from api.orchestrator import (
    MAX_MODEL_CALLS,
    MAX_READ_EXECUTES,
    build_function_declarations,
    is_allowed_tool,
    run_turn,
)
from api.tests.fakes import (
    FakeMcpClient,
    ScriptedGeminiClient,
    function_call_chunk,
    load_fixture_tools,
    text_chunk,
)

CLASSES = {
    "google_calendar_find_events": "read",
    "gmail_find_email": "read",
    "gmail_create_draft": "write",
}


async def collect(turn: ScriptedGeminiClient, mcp: FakeMcpClient | None, tools=None):
    events: list[tuple[str, dict]] = []
    async for event in run_turn(
        gemini_client=turn,
        model="gemini-2.5-flash",
        fallback_model="gemini-2.5-flash-lite",
        system_prompt="test prompt",
        message="do a thing",
        tools=tools if tools is not None else await mcp.list_tools(),
        mcp=mcp,
        classes=CLASSES,
    ):
        events.append(event)
    return events


async def test_read_tool_runs_and_model_continues() -> None:
    """Read call auto-executes, result goes back to the model, final answer streams."""
    gemini = ScriptedGeminiClient(
        [
            [function_call_chunk("google_calendar_find_events", {"date": "tomorrow"}), text_chunk("Checking.")],
            [text_chunk("You have a team sync at 10:00 tomorrow.")],
        ]
    )
    mcp = FakeMcpClient()

    events = await collect(gemini, mcp)
    names = [name for name, _ in events]

    assert names == ["token", "tool_proposed", "tool_result", "token", "done"]
    assert mcp.calls == [("google_calendar_find_events", {"date": "tomorrow"})]
    assert ("approval_required" in names) is False


async def test_write_tool_requires_approval_and_stops() -> None:
    """Write call is never executed; the turn stops with approval_required."""
    gemini = ScriptedGeminiClient(
        [[function_call_chunk("gmail_create_draft", {"to": "a@b.c", "subject": "s", "body": "b"})]]
    )
    mcp = FakeMcpClient()

    events = await collect(gemini, mcp)
    names = [name for name, _ in events]

    assert "approval_required" in names
    assert mcp.calls == []  # write was NOT executed
    approval = next(d for n, d in events if n == "approval_required")
    assert approval["classification"] == "write"
    assert approval["estimated_cost_tasks"] == 2
    final = events[-1]
    assert final[0] == "done" and final[1].get("stopped_for_approval") is True


async def test_unlisted_tool_defaults_to_write() -> None:
    """Anything not in tools.yaml is treated as write (fail safe)."""
    gemini = ScriptedGeminiClient([[function_call_chunk("some_unknown_tool", {"x": 1})]])
    mcp = FakeMcpClient()

    events = await collect(gemini, mcp)
    approval = next(d for n, d in events if n == "approval_required")

    assert approval["classification"] == "write"
    assert approval["listed"] is False


async def test_forbidden_meta_tools_never_offered() -> None:
    """Management meta-tools are filtered out of the model's tool list."""
    declarations = build_function_declarations(await FakeMcpClient().list_tools())
    names = [d.name for d in declarations]

    assert "enable_zapier_action" not in names
    assert "google_calendar_find_events" in names


def test_live_zapier_schemas_are_sanitized_for_gemini() -> None:
    """M3.8: real Zapier schemas carry $schema and _meta keys that Gemini's
    Schema model rejects - build_function_declarations must sanitize them."""
    from api.mcp_client import McpTool

    zapier_style = McpTool(
        name="gmail_send_email",
        description="Send an email",
        input_schema={
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "additionalProperties": True,
            "properties": {
                "to": {"type": "string", "description": "Recipient"},
                "label_ids": {
                    "anyOf": [
                        {
                            "items": {
                                "type": "string",
                                "_meta": {"zapier/dynamic_enum": {"resolver": "x"}},
                            },
                            "type": "array",
                        }
                    ]
                },
            },
            "required": ["to"],
        },
    )
    declarations = build_function_declarations([zapier_style])
    assert [d.name for d in declarations] == ["gmail_send_email"]
    params = declarations[0].parameters
    assert params is not None
    assert "to" in params.properties
    assert "label_ids" in params.properties


def test_meta_tool_patterns_cover_real_zapier_server() -> None:
    """M3.8: the real Zapier server exposes meta-tools that must never reach the model."""
    assert not is_allowed_tool("get_dynamic_properties_schema")
    assert not is_allowed_tool("list_dynamic_enum_values")
    assert not is_allowed_tool("get_configuration_url")
    # Real action tools from the user's server (2026-10-10) must pass the gate.
    assert is_allowed_tool("gmail_create_draft")
    assert is_allowed_tool("gmail_find_email")
    assert is_allowed_tool("google_calendar_find_events")


async def test_forbidden_tool_refused_at_gate() -> None:
    """M3.7: a hallucinated/injected meta-tool is refused at the gate - no
    approval card, no pending action, no execution."""
    gemini = ScriptedGeminiClient(
        [[function_call_chunk("execute_zapier_write_action", {"instructions": "send"})]]
    )
    mcp = FakeMcpClient()

    events = await collect(gemini, mcp)
    names = [name for name, _ in events]

    assert "approval_required" not in names
    assert "tool_result" not in names
    assert mcp.calls == []
    assert names[-1] == "error"


async def test_read_executes_capped_per_turn() -> None:
    """Third read in one turn is blocked and requires approval (finding 3)."""
    gemini = ScriptedGeminiClient(
        [
            [function_call_chunk("google_calendar_find_events", {"date": "d1"})],
            [function_call_chunk("gmail_find_email", {"query": "q"})],
            [function_call_chunk("google_calendar_find_events", {"date": "d3"})],
        ]
    )
    mcp = FakeMcpClient()

    events = await collect(gemini, mcp)
    approvals = [d for n, d in events if n == "approval_required"]

    assert len(mcp.calls) == MAX_READ_EXECUTES
    assert len(approvals) == 1
    assert approvals[0]["tool"] == "google_calendar_find_events"


async def test_model_call_cap_stops_the_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    """R4: the loop stops after MAX_MODEL_CALLS with an honest message."""
    monkeypatch.setattr("api.orchestrator.MAX_MODEL_CALLS", 2)
    monkeypatch.setattr("api.orchestrator.MAX_READ_EXECUTES", 5)
    gemini = ScriptedGeminiClient(
        [
            [function_call_chunk("google_calendar_find_events", {"date": "d1"})],
            [function_call_chunk("google_calendar_find_events", {"date": "d2"})],
            [function_call_chunk("google_calendar_find_events", {"date": "d3"})],
        ]
    )
    mcp = FakeMcpClient()

    events = await collect(gemini, mcp)
    last_name, last_data = events[-1]

    assert last_name == "error"
    assert "model-call limit" in last_data["message"]
    assert gemini.model_calls == 2


async def test_mcp_failure_reported_honestly() -> None:
    """A failing tool call is fed back as an error result, not a success."""
    class FailingMcp(FakeMcpClient):
        async def call_tool(self, name: str, arguments: dict) -> str:
            from api.mcp_client import McpError

            raise McpError("Zapier MCP call failed (ConnectError).")

    gemini = ScriptedGeminiClient(
        [
            [function_call_chunk("google_calendar_find_events", {"date": "tomorrow"})],
            [text_chunk("The calendar action failed, so I could not check.")],
        ]
    )

    events = await collect(gemini, FailingMcp())
    tool_result = next(d for n, d in events if n == "tool_result")

    assert tool_result["result"].startswith("Error:")
    assert events[-1][0] == "done"
