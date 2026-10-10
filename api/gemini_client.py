"""Thin primitives around google-genai. No policy logic lives here.

R5 (429 -> backoff -> lighter model -> tell the user) is implemented in
stream_raw_with_fallback; the orchestrator consumes raw chunks so it can
inspect both .text and .function_calls.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)


class GeminiUnavailable(Exception):
    """Gemini failed after backoff and fallback. Message is safe to show the user."""


def make_client(api_key: str) -> genai.Client:
    """Factory so routes/tests can inject a fake client."""
    return genai.Client(api_key=api_key)


async def stream_raw_with_fallback(
    client: Any,
    model: str,
    fallback_model: str,
    config: types.GenerateContentConfig,
    contents: list[types.Content],
) -> AsyncIterator[Any]:
    """Yield raw response chunks. R5: 429 -> backoff retry -> fallback model.

    If chunks were already yielded before a failure, do not retry (it would
    duplicate text); surface GeminiUnavailable instead.
    """
    attempts = ((model, 0.0), (model, 2.0), (fallback_model, 4.0))
    yielded_any = False
    last_error: Exception | None = None

    for attempt_model, delay in attempts:
        if delay:
            await asyncio.sleep(delay)
        try:
            stream = await client.aio.models.generate_content_stream(
                model=attempt_model,
                contents=contents,
                config=config,
            )
            async for chunk in stream:
                yielded_any = True
                yield chunk
            return
        except GeminiUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 - boundary: classify, then decide
            last_error = exc
            logger.warning("gemini stream failed on %s: %s", attempt_model, exc)  # server-side only
            if yielded_any:
                raise GeminiUnavailable("The reply was interrupted. Please try again.") from exc
            if getattr(exc, "code", None) != 429:
                raise GeminiUnavailable(
                    f"The assistant could not reach Gemini ({type(exc).__name__})."
                ) from exc

    raise GeminiUnavailable(
        "Gemini is rate limited right now. Try again in a moment."
    ) from last_error
