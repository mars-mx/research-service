"""Background task runner and callback logic."""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlparse

import httpx

from src.api.schemas import ResearchResult
from src.cache.redis import RedisCache
from src.config import Settings
from src.research.engine import ResearchEngine

logger = logging.getLogger(__name__)


def validate_callback_url(url: str, allowed_hosts: str) -> bool:
    """Check that *url*'s host is in the comma-separated allow-list."""
    if not allowed_hosts:
        return False
    allowed = {h.strip() for h in allowed_hosts.split(",") if h.strip()}
    parsed = urlparse(url)
    return parsed.hostname in allowed


async def post_callback(url: str, payload: dict) -> None:
    """POST a JSON payload to the callback URL. Best-effort, no retries."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
    except Exception:
        logger.warning("callback POST to %s failed", url, exc_info=True)


async def run_background_research(
    engine: ResearchEngine,
    cache: RedisCache,
    settings: Settings,
    query: str,
    report_type: str,
    depth: int,
    breadth: int,
    callback_url: str | None = None,
) -> None:
    """Run research in the background, cache the result, and optionally POST callback."""
    try:
        result: ResearchResult = await engine.run(
            query=query,
            report_type=report_type,
            depth=depth,
            breadth=breadth,
        )
        await cache.set(result.task_id, result, ttl=settings.result_ttl_seconds)

        if callback_url:
            await post_callback(
                callback_url,
                {
                    "task_id": result.task_id,
                    "status": "completed",
                    "result_url": f"/research/{result.task_id}",
                },
            )
    except Exception:
        logger.exception("background research failed for query=%r", query)
