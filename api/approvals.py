"""Approval integrity (CodeReviewer finding 2).

- Server-side HMAC-SHA256 over canonical JSON of {pending_id, tool, args}.
- Single-use state machine: pending -> approved -> executed (or rejected/expired).
- Expiry is enforced at execution time, not just visually.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone


def canonical_args(args: dict) -> str:
    """Canonical JSON: sorted keys, no whitespace - hash-stable across key order."""
    return json.dumps(args, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_args_hash(pending_id: str, tool: str, args: dict, secret: str) -> str:
    payload = f"{pending_id}|{tool}|{canonical_args(args)}"
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_args_hash(pending_id: str, tool: str, args: dict, secret: str, expected: str) -> bool:
    return hmac.compare_digest(compute_args_hash(pending_id, tool, args, secret), expected)


def is_expired(expires_at_iso: str, now: datetime | None = None) -> bool:
    reference = now or datetime.now(timezone.utc)
    try:
        expires_at = datetime.fromisoformat(expires_at_iso)
    except ValueError:
        return True  # unparseable expiry fails closed
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at < reference
