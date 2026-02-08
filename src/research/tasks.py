"""Background task runner and callback logic."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from src.api.schemas import ResearchResult
from src.cache.redis import RedisCache
from src.config import Settings
from src.research.engine import ResearchEngine

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetryConfig:
    """Configuration for exponential-backoff retry on callback POST."""

    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0


_DEFAULT_RETRY = RetryConfig()

_VALID_SCHEMES = {"http", "https"}


def validate_callback_url(url: str, allowed_hosts: str) -> bool:
    """Check that *url*'s host is in the comma-separated allow-list.

    Also enforces:
    - http or https scheme
    - No embedded credentials (username/password)
    - Non-empty hostname
    - Case-insensitive hostname comparison
    """
    if not allowed_hosts:
        return False

    parsed = urlparse(url)

    # Require http or https scheme
    if parsed.scheme not in _VALID_SCHEMES:
        return False

    # Reject embedded credentials
    if parsed.username or parsed.password:
        return False

    # Require non-empty hostname
    hostname = parsed.hostname
    if not hostname:
        return False

    allowed = {h.strip().lower() for h in allowed_hosts.split(",") if h.strip()}
    return hostname.lower() in allowed


async def post_callback(
    url: str,
    payload: dict,
    retry_config: RetryConfig = _DEFAULT_RETRY,
) -> None:
    """POST a JSON payload to the callback URL with exponential-backoff retry.

    Retries only on network-related errors (connection errors, timeouts).
    Server errors (5xx) are NOT retried.
    """
    import asyncio

    for attempt in range(1 + retry_config.max_retries):
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                return
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout) as exc:
            if attempt < retry_config.max_retries:
                delay = min(
                    retry_config.base_delay * (2 ** attempt),
                    retry_config.max_delay,
                )
                logger.warning(
                    "callback POST to %s failed (attempt %d/%d), retrying in %.1fs: %s",
                    url, attempt + 1, retry_config.max_retries + 1, delay, exc,
                )
                await asyncio.sleep(delay)
            else:
                logger.warning(
                    "callback POST to %s failed after %d attempts",
                    url, retry_config.max_retries + 1, exc_info=True,
                )
        except Exception:
            logger.warning("callback POST to %s failed (non-retryable)", url, exc_info=True)
            return


async def run_background_research(
    engine: ResearchEngine,
    cache: RedisCache,
    settings: Settings,
    query: str,
    report_type: str,
    depth: int,
    breadth: int,
    task_id: str,
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
        # Override engine-generated task_id with the one provided by the caller
        # so polling via GET /research/{task_id} works with the id returned at 202.
        result = result.model_copy(update={"task_id": task_id})
        await cache.set(task_id, result, ttl=settings.result_ttl_seconds)

        if callback_url:
            await post_callback(
                callback_url,
                {
                    "task_id": task_id,
                    "status": "completed",
                    "result_url": f"/research/{task_id}",
                },
            )
    except Exception:
        logger.exception("background research failed for query=%r", query)
