"""Shared test fakes. No network, no real Zapier calls, no real Gemini calls."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from api.mcp_client import McpTool

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture_tools() -> list[McpTool]:
    """Real McpTool objects built from fixtures/tools.json (interface parity with the real client)."""
    data = json.loads((FIXTURES / "tools.json").read_text(encoding="utf-8"))
    return [
        McpTool(
            name=item["name"],
            description=item["description"],
            input_schema=item["input_schema"],
        )
        for item in data
    ]


class FakeMcpClient:
    """Same interface as ZapierMcpClient; returns canned fixture results."""

    def __init__(self, results: dict[str, str] | None = None) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._results = results if results is not None else json.loads(
            (FIXTURES / "results.json").read_text(encoding="utf-8")
        )

    async def list_tools(self) -> list[Any]:
        return load_fixture_tools()

    async def call_tool(self, name: str, arguments: dict) -> str:
        self.calls.append((name, arguments))
        if name not in self._results:
            raise RuntimeError(f"no fixture result for {name}")  # test bug, not product behavior
        return self._results[name]


def text_chunk(text: str) -> Any:
    return SimpleNamespace(text=text, function_calls=None)


def function_call_chunk(name: str, args: dict | None) -> Any:
    call = SimpleNamespace(name=name, args=args)
    return SimpleNamespace(text=None, function_calls=[call])


class ScriptedGeminiClient:
    """Duck-typed genai.Client returning scripted chunk lists, one list per model call."""

    def __init__(self, turns: list[list[Any]]) -> None:
        self._turns = turns
        self.model_calls = 0
        self.aio = SimpleNamespace(models=SimpleNamespace(generate_content_stream=self._stream))

    async def _stream(self, *, model: str, contents: list, config=None):  # noqa: ANN001, ARG002
        async def gen():
            index = self.model_calls
            self.model_calls += 1
            if index >= len(self._turns):
                return
            for chunk in self._turns[index]:
                yield chunk

        return gen()
