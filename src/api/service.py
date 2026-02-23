"""Service layer — orchestrates research operations for the API routes."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, AsyncGenerator

from src.api.schemas import ResearchRequest, ResearchResult
from src.cache.redis import RedisCache
from src.config import Settings
from src.research.engine import ResearchEngine, resolve_params
from src.research.tasks import post_callback, run_background_research

logger = logging.getLogger(__name__)


def _generate_task_id() -> str:
    return uuid.uuid4().hex[:12]


async def start_background_research(
    engine: ResearchEngine,
    cache: RedisCache,
    settings: Settings,
    body: ResearchRequest,
) -> dict[str, str]:
    """Launch background research and return the acceptance payload with task_id."""
    report_type, depth, breadth = resolve_params(
        body.depth, body.research_depth, body.research_breadth, body.report_type
    )
    task_id = _generate_task_id()
    logger.info(
        "background research started",
        extra={
            "task_id": task_id,
            "query": body.query[:100],
            "report_type": report_type,
            "depth": depth,
            "breadth": breadth,
        },
    )

    asyncio.create_task(
        run_background_research(
            engine=engine,
            cache=cache,
            settings=settings,
            query=body.query,
            report_type=report_type,
            depth=depth,
            breadth=breadth,
            task_id=task_id,
            callback_url=body.callback_url,
        )
    )

    return {
        "status": "accepted",
        "task_id": task_id,
        "message": "Research started. Results will be sent to callback URL.",
    }


async def stream_research(
    engine: ResearchEngine,
    cache: RedisCache,
    settings: Settings,
    body: ResearchRequest,
) -> AsyncGenerator[dict[str, str], None]:
    """Yield SSE-formatted events from the research engine.

    If the client disconnects, the research task continues in the background
    so the result still gets cached.
    """
    report_type, depth, breadth = resolve_params(
        body.depth, body.research_depth, body.research_breadth, body.report_type
    )
    logger.info(
        "streaming research started",
        extra={
            "query": body.query[:100],
            "report_type": report_type,
            "depth": depth,
            "breadth": breadth,
        },
    )

    queue: asyncio.Queue[tuple[str, dict[str, Any]] | None] = asyncio.Queue()

    async def on_event(event: str, data: dict[str, Any]) -> None:
        await queue.put((event, data))

    async def run_and_signal_done() -> None:
        try:
            result = await engine.run(
                query=body.query,
                report_type=report_type,
                depth=depth,
                breadth=breadth,
                on_event=on_event,
            )
            await cache.set(result.task_id, result, ttl=settings.result_ttl_seconds)
            logger.info("streaming research completed", extra={"task_id": result.task_id})

            if body.callback_url:
                await post_callback(
                    body.callback_url,
                    {
                        "task_id": result.task_id,
                        "status": "completed",
                        "result_url": f"/research/{result.task_id}",
                    },
                )
        except Exception:
            logger.exception("streaming research failed", extra={"query": body.query[:100]})
            await queue.put(("error", {"message": "Research failed"}))
        finally:
            await queue.put(None)  # sentinel

    task = asyncio.create_task(run_and_signal_done())

    try:
        while True:
            item = await queue.get()
            if item is None:
                break
            event, data = item
            yield {"event": event, "data": json.dumps(data)}
    finally:
        # Do NOT cancel the task on client disconnect — let it run to
        # completion so the result still gets cached.
        pass


async def get_research_result(
    cache: RedisCache,
    task_id: str,
) -> ResearchResult | None:
    """Retrieve a cached research result by task_id."""
    return await cache.get(task_id)
