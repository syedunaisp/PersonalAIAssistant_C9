"""Chat endpoint tests. Gemini is faked - no real model calls, no network."""
from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from api.config import Settings
from api.main import create_app

HOST = {"host": "localhost:8000"}


def ready_settings() -> Settings:
    return Settings(
        gemini_api_key="fake-key",
        zapier_mcp_token="fake-token",
        local_api_token="test-token",
        next_public_api_url="http://localhost:8000",
        gemini_model="gemini-2.5-flash",
        gemini_model_fallback="gemini-2.5-flash-lite",
    )


class FakeGeminiClient:
    """Duck-typed stand-in for genai.Client with a canned chunk stream."""

    def __init__(self, chunks: list[str], fail_with: Exception | None = None) -> None:
        self._chunks = chunks
        self._fail_with = fail_with
        self.aio = SimpleNamespace(models=SimpleNamespace(generate_content_stream=self._stream))

    async def _stream(self, *, model: str, contents: str, config=None):  # noqa: ANN001, ARG002
        async def gen():
            if self._fail_with:
                raise self._fail_with
            for chunk in self._chunks:
                yield SimpleNamespace(text=chunk)

        return gen()


def make_client(chunks: list[str], fail_with: Exception | None = None) -> FakeGeminiClient:
    return FakeGeminiClient(chunks, fail_with)


def parse_sse(text: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for frame in text.split("\n\n"):
        if not frame.strip():
            continue
        event_name = ""
        data: dict = {}
        for line in frame.split("\n"):
            if line.startswith("event:"):
                event_name = line[len("event:"):].strip()
            elif line.startswith("data:"):
                import json

                data = json.loads(line[len("data:"):].strip())
        events.append((event_name, data))
    return events


def test_chat_streams_tokens_then_done() -> None:
    """Section 16 test 1: a plain rewrite request streams text with no tool events."""
    app = create_app(ready_settings(), gemini_client_factory=lambda: make_client(["Hello ", "there"]))
    client = TestClient(app)

    response = client.post(
        "/api/chat",
        json={"message": "Rewrite this email: hi"},
        headers={**HOST, "Content-Type": "application/json"},
    )

    assert response.status_code == 200
    events = parse_sse(response.text)
    names = [name for name, _ in events]
    assert names[0] == "token"
    assert names[-1] == "done"
    assert "tool_proposed" not in names
    assert "approval_required" not in names
    joined = "".join(data.get("text", "") for name, data in events if name == "token")
    assert joined == "Hello there"


def test_chat_rejects_non_json_body() -> None:
    app = create_app(ready_settings(), gemini_client_factory=lambda: make_client(["x"]))
    client = TestClient(app)

    response = client.post(
        "/api/chat",
        content="message=hi",
        headers={**HOST, "Content-Type": "text/plain"},
    )

    assert response.status_code == 415


def test_chat_rejects_empty_message() -> None:
    app = create_app(ready_settings(), gemini_client_factory=lambda: make_client(["x"]))
    client = TestClient(app)

    response = client.post(
        "/api/chat",
        json={"message": "   "},
        headers={**HOST, "Content-Type": "application/json"},
    )

    assert response.status_code == 400


def test_chat_fails_closed_without_secrets() -> None:
    settings = Settings(
        gemini_api_key="",
        zapier_mcp_token="",
        local_api_token="test-token",
        next_public_api_url="http://localhost:8000",
        gemini_model="m",
        gemini_model_fallback="m-lite",
    )
    app = create_app(settings, gemini_client_factory=lambda: make_client(["x"]))
    client = TestClient(app)

    response = client.post(
        "/api/chat",
        json={"message": "hi"},
        headers={**HOST, "Content-Type": "application/json"},
    )

    assert response.status_code == 503


def test_chat_rejects_foreign_host() -> None:
    app = create_app(ready_settings(), gemini_client_factory=lambda: make_client(["x"]))
    client = TestClient(app)

    response = client.get("/api/health", headers={"host": "evil.example"})

    assert response.status_code == 403


def test_chat_works_without_token_header() -> None:
    """M3.7: the browser cannot hold a secret - transport auth is Host+CORS,
    and LOCAL_API_TOKEN is only the HMAC integrity secret for approvals."""
    app = create_app(ready_settings(), gemini_client_factory=lambda: make_client(["x"]))
    client = TestClient(app)

    response = client.post(
        "/api/chat",
        json={"message": "hi"},
        headers={**HOST, "Content-Type": "application/json"},
    )

    assert response.status_code == 200


def test_chat_emits_error_event_when_gemini_fails() -> None:
    app = create_app(
        ready_settings(),
        gemini_client_factory=lambda: make_client([], fail_with=RuntimeError("boom")),
    )
    client = TestClient(app)

    response = client.post(
        "/api/chat",
        json={"message": "hi"},
        headers={**HOST, "Content-Type": "application/json"},
    )

    events = parse_sse(response.text)
    names = [name for name, _ in events]
    assert "error" in names
    assert "boom" not in response.text  # internals never leak to the client
