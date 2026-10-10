"""Application settings loaded from .env. Secrets never live in code or logs."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str
    zapier_mcp_token: str
    local_api_token: str
    next_public_api_url: str
    gemini_model: str
    gemini_model_fallback: str
    default_calendar_id: str = ""

    @property
    def gemini_ready(self) -> bool:
        return bool(self.gemini_api_key.strip())

    @property
    def zapier_ready(self) -> bool:
        return bool(self.zapier_mcp_token.strip())

    @property
    def secrets_ready(self) -> bool:
        """Fail-closed flag: privileged endpoints must check this before acting."""
        return self.gemini_ready and self.zapier_ready


def load_settings(env_path: Path | None = None) -> Settings:
    """Load settings from .env. Missing secrets become empty strings; callers must fail closed."""
    load_dotenv(dotenv_path=env_path or PROJECT_ROOT / ".env")
    return Settings(
        gemini_api_key=os.environ.get("GEMINI_API_KEY", ""),
        zapier_mcp_token=os.environ.get("ZAPIER_MCP_TOKEN", ""),
        local_api_token=os.environ.get("LOCAL_API_TOKEN", ""),
        next_public_api_url=os.environ.get("NEXT_PUBLIC_API_URL", "http://localhost:8000"),
        gemini_model=os.environ.get("GEMINI_MODEL", "gemini-3.8-flash"),
        gemini_model_fallback=os.environ.get("GEMINI_MODEL_FALLBACK", "gemini-3.5-flash-lite"),
        default_calendar_id=os.environ.get("DEFAULT_CALENDAR_ID", ""),
    )
