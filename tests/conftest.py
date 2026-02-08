"""Fixtures — test client, mock Redis."""

import pytest_asyncio
from fakeredis.aioredis import FakeRedis

from src.cache.redis import RedisCache


@pytest_asyncio.fixture
async def redis_cache():
    """RedisCache backed by an in-memory FakeRedis instance."""
    client = FakeRedis(decode_responses=True)
    cache = RedisCache(client, default_ttl=3600)
    yield cache
    await client.aclose()
