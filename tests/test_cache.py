"""Redis cache tests."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
import redis.asyncio as redis

from src.api.schemas import ResearchMetadata, ResearchResult, ResearchSource, Usage
from src.cache.redis import KEY_PREFIX, RedisCache


pytestmark = pytest.mark.asyncio


def _make_result(task_id: str = "task-1", **overrides) -> ResearchResult:
    defaults = dict(
        task_id=task_id,
        report="# Some markdown",
        sources=[ResearchSource(url="https://example.com", title="Example")],
        source_urls=["https://example.com"],
        images=["https://example.com/img.png"],
        usage=Usage(prompt_tokens=300, completion_tokens=200, total_tokens=500),
        metadata=ResearchMetadata(
            requests=2, llm_provider="openai", fast_llm="gpt-4o-mini", smart_llm="gpt-4o",
        ),
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return ResearchResult(**defaults)


async def test_set_and_get(redis_cache: RedisCache):
    result = _make_result()
    assert await redis_cache.set("task-1", result) is True
    cached = await redis_cache.get("task-1")
    assert cached == result


async def test_get_missing_key(redis_cache: RedisCache):
    assert await redis_cache.get("nonexistent") is None


async def test_ttl_is_set(redis_cache: RedisCache):
    await redis_cache.set("task-ttl", _make_result("task-ttl"))
    ttl = await redis_cache._client.ttl(f"{KEY_PREFIX}task-ttl")
    assert 0 < ttl <= 3600


async def test_custom_ttl(redis_cache: RedisCache):
    await redis_cache.set("task-custom", _make_result("task-custom"), ttl=120)
    ttl = await redis_cache._client.ttl(f"{KEY_PREFIX}task-custom")
    assert 0 < ttl <= 120


async def test_key_prefix(redis_cache: RedisCache):
    await redis_cache.set("abc-123", _make_result("abc-123"))
    assert await redis_cache._client.exists(f"{KEY_PREFIX}abc-123")
    assert not await redis_cache._client.exists("abc-123")


async def test_usage_round_trip(redis_cache: RedisCache):
    result = _make_result(
        usage=Usage(prompt_tokens=100, completion_tokens=400, total_tokens=500),
        metadata=ResearchMetadata(
            requests=3, llm_provider="openai", fast_llm="gpt-4o-mini", smart_llm="gpt-4o",
        ),
    )
    await redis_cache.set("task-meta", result)
    cached = await redis_cache.get("task-meta")
    assert cached.usage.prompt_tokens == 100
    assert cached.usage.completion_tokens == 400
    assert cached.usage.total_tokens == 500
    assert cached.metadata.requests == 3
    assert cached.metadata.llm_provider == "openai"


async def test_legacy_cached_json_defaults_usage(redis_cache: RedisCache):
    """Old cached JSON (tokens in metadata, no usage key) deserializes with usage defaulting to zeros."""
    import json

    legacy_json = json.dumps({
        "task_id": "task-legacy",
        "status": "completed",
        "report": "# Legacy",
        "sources": [],
        "source_urls": [],
        "images": [],
        "metadata": {
            "requests": 1,
            "llm_provider": "openai",
            "fast_llm": "gpt-4o-mini",
            "smart_llm": "gpt-4o",
        },
        "created_at": "2026-01-01T00:00:00Z",
    })
    await redis_cache._client.set(f"{KEY_PREFIX}task-legacy", legacy_json, ex=3600)
    cached = await redis_cache.get("task-legacy")
    assert cached is not None
    assert cached.usage.prompt_tokens == 0
    assert cached.usage.completion_tokens == 0
    assert cached.usage.total_tokens == 0


async def test_source_urls_and_images_round_trip(redis_cache: RedisCache):
    result = _make_result(
        source_urls=["https://a.com", "https://b.com"],
        images=["https://a.com/1.png", "https://b.com/2.png"],
    )
    await redis_cache.set("task-extra", result)
    cached = await redis_cache.get("task-extra")
    assert cached.source_urls == ["https://a.com", "https://b.com"]
    assert cached.images == ["https://a.com/1.png", "https://b.com/2.png"]


async def test_get_handles_connection_error(redis_cache: RedisCache):
    redis_cache._client.get = AsyncMock(
        side_effect=redis.ConnectionError("down")
    )
    assert await redis_cache.get("task-err") is None


async def test_set_handles_connection_error(redis_cache: RedisCache):
    redis_cache._client.set = AsyncMock(
        side_effect=redis.ConnectionError("down")
    )
    assert await redis_cache.set("task-err", _make_result()) is False
