"""Event handling helpers for the research pipeline."""

from __future__ import annotations

from typing import Any, Callable, Coroutine

# Type alias for the SSE event callback used across the pipeline.
EventCallback = Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]]


async def emit_event(
    on_event: EventCallback | None,
    event: str,
    data: dict[str, Any] | None = None,
) -> None:
    """Emit a pipeline event if a callback is registered."""
    if on_event:
        await on_event(event, data or {})
