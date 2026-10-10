"""Health endpoint structure tests. No real network calls - settings are faked empty."""
from __future__ import annotations

from fastapi.testclient import TestClient

from api.config import Settings
from api.main import create_app


def fake_settings() -> Settings:
    return Settings(
        gemini_api_key="",
        zapier_mcp_token="",
        local_api_token="test-token",
        next_public_api_url="http://localhost:8000",
        gemini_model="gemini-2.5-flash",
        gemini_model_fallback="gemini-2.5-flash-lite",
    )


def test_health_reports_degraded_without_secrets() -> None:
    """With empty secrets the endpoint must answer honestly: degraded, not ok."""
    client = TestClient(create_app(fake_settings()))
    response = client.get("/api/health", headers={"host": "localhost:8000"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["gemini"]["ok"] is False
    assert "not set" in body["gemini"]["detail"]
    assert body["zapier"]["ok"] is False
    assert "not set" in body["zapier"]["detail"]


def test_health_never_echoes_secrets() -> None:
    """Secrets must never appear in the health response (M3.7: hit the real
    200 path, not the Host-403 path, or the assertion is vacuous)."""
    client = TestClient(create_app(fake_settings()))
    response = client.get("/api/health", headers={"host": "localhost:8000"})
    assert response.status_code == 200
    assert "sk-test" not in str(response.json())
