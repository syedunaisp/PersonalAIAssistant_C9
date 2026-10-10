"""FastAPI entrypoint.

Binds to 127.0.0.1 only (localhost is not a trust boundary - spec section 11).
Fail-closed: without secrets the app boots degraded so /api/health can diagnose;
privileged endpoints check settings.secrets_ready before acting.
Hardening (M1.3 + M3.7 review): CORS locked to the web origin, Host header
validated, non-JSON POST bodies rejected. LOCAL_API_TOKEN is the HMAC
integrity secret for approval args - NOT transport auth (the browser cannot
hold a secret; browser traffic is protected by the Host allowlist + CORS +
JSON-only bodies). If LOCAL_API_TOKEN is unset, an ephemeral random secret is
generated per process so the approval gate always works.
"""
from __future__ import annotations

import asyncio
import logging
import secrets
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.chat import router as chat_router
from api.config import Settings, load_settings
from api.gemini_client import make_client
from api.health import check_gemini, check_zapier
from api.mcp_client import McpClient, McpError, McpTool, ZapierMcpClient
from api.policy import load_classes
from api.routes_approvals import router as approvals_router
from api.store import Store

logger = logging.getLogger(__name__)

WEB_ORIGIN = "http://localhost:3000"
ALLOWED_HOSTS = {"localhost:8000", "127.0.0.1:8000"}


def create_app(
    settings: Settings | None = None,
    gemini_client_factory: Callable[[], object] | None = None,
    mcp_client: McpClient | None = None,
    store: Store | None = None,
    db_path: Path | None = None,
) -> FastAPI:
    """App factory with explicit dependency injection (code-quality standard)."""
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if not settings.local_api_token:
            print(
                "[startup] WARNING: LOCAL_API_TOKEN not set - mutating endpoints are "
                "protected only by the Host check (localhost-only deployment)"
            )
        if settings.secrets_ready:
            print("[startup] secrets present - full mode")
        else:
            print("[startup] FAIL-CLOSED: GEMINI_API_KEY / ZAPIER_MCP_TOKEN missing - degraded mode")
        yield

    app = FastAPI(title="Personal AI Assistant API", lifespan=lifespan)
    app.state.settings = settings
    # M3.7: HMAC secret for approval-args integrity. Ephemeral fallback so the
    # approval gate never silently dies when LOCAL_API_TOKEN is unset.
    app.state.hash_secret = settings.local_api_token or secrets.token_hex(32)
    app.state.gemini_client = gemini_client_factory or (lambda: make_client(settings.gemini_api_key))
    app.state.mcp_client = mcp_client if mcp_client is not None else (
        ZapierMcpClient(settings.zapier_mcp_token) if settings.zapier_ready else None
    )
    app.state.store = store if store is not None else Store(db_path)
    app.state.tool_classes = load_classes()
    app.state.zapier_tools = []

    async def ensure_tools() -> list[McpTool]:
        """Load the Zapier tool list once per process (list_tools is free per docs)."""
        if not app.state.zapier_tools and app.state.mcp_client is not None:
            try:
                app.state.zapier_tools = await app.state.mcp_client.list_tools()
            except McpError as exc:
                logger.warning("Zapier tool list unavailable: %s", exc)
                app.state.zapier_tools = []
        return app.state.zapier_tools

    app.state.ensure_tools = ensure_tools

    # M1.3: CORS locked to the web origin.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[WEB_ORIGIN],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type"],
    )

    # M1.3 + M3.7: Host validation. The X-Local-Token transport check was
    # removed (M3.7 review): the browser cannot hold a secret, and the
    # Host allowlist + CORS + JSON-only bodies already cover the threat.
    @app.middleware("http")
    async def guard(request: Request, call_next):
        host = request.headers.get("host", "")
        if host not in ALLOWED_HOSTS:
            return JSONResponse({"detail": "Invalid host"}, status_code=403)
        return await call_next(request)

    app.include_router(chat_router)
    app.include_router(approvals_router)

    @app.get("/api/health")
    async def health() -> dict:
        gemini = await asyncio.to_thread(
            check_gemini, settings.gemini_api_key, settings.gemini_model
        )
        zapier = await check_zapier(settings.zapier_mcp_token)
        return {
            "status": "ok" if (gemini.ok and zapier.ok) else "degraded",
            "gemini": {"ok": gemini.ok, "detail": gemini.detail},
            "zapier": {"ok": zapier.ok, "detail": zapier.detail},
        }

    return app


app = create_app()
