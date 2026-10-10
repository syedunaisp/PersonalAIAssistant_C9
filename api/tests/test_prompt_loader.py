"""Prompt loader tests: operator context injection (M3.8)."""
from __future__ import annotations

from api.prompt_loader import operator_context


def test_operator_context_empty_when_unset() -> None:
    assert operator_context("") == ""
    assert operator_context("   ") == ""


def test_operator_context_names_primary_calendar() -> None:
    context = operator_context("user@example.com")

    assert "user@example.com" in context
    assert "calendarid" in context
