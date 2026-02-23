"""Redis client — get/set with TTL."""

from __future__ import annotations

import logging

import redis.asyncio as redis
from redis.backoff import ExponentialBackoff
from redis.retry import Retry

from src.api.schemas import ResearchResult

logger = logging.getLogger(__name__)

KEY_PREFIX = "result:"


class RedisCache:
    """Thin async wrapper around Redis for caching research results."""

    def __init__(self, client: redis.Redis, default_ttl: int = 3600) -> None:
        self._client = client
        self._default_ttl = default_ttl

    async def get(self, task_id: str) -> ResearchResult | None:
        """Return cached result, or ``None`` on miss / error."""
        try:
            raw = await self._client.get(f"{KEY_PREFIX}{task_id}")
            if raw is None:
                logger.debug("cache miss", extra={"task_id": task_id})
                return None
            logger.debug("cache hit", extra={"task_id": task_id})
            return ResearchResult.model_validate_json(raw)
        except redis.RedisError:
            logger.warning("cache get failed", extra={"task_id": task_id}, exc_info=True)
            return None

    async def set(
        self, task_id: str, result: ResearchResult, ttl: int | None = None
    ) -> bool:
        """Store *result* with a TTL. Returns ``False`` on error."""
        effective_ttl = ttl if ttl is not None else self._default_ttl
        try:
            payload = result.model_dump_json()
            await self._client.set(
                f"{KEY_PREFIX}{task_id}",
                payload,
                ex=effective_ttl,
            )
            logger.debug("cache set", extra={"task_id": task_id, "ttl": effective_ttl})
            return True
        except redis.RedisError:
            logger.warning("cache set failed", extra={"task_id": task_id}, exc_info=True)
            return False


async def create_redis_client(redis_url: str) -> redis.Redis:
    # Strip credentials for logging (everything before @ if present)
    safe_url = redis_url.split("@")[-1] if "@" in redis_url else redis_url
    logger.info("connecting to redis", extra={"redis_url": safe_url})
    retry = Retry(ExponentialBackoff(), retries=3)
    return redis.from_url(
        redis_url,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
        health_check_interval=30,
        retry=retry,
        retry_on_error=[redis.ConnectionError, redis.TimeoutError],
    )
