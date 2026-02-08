"""FastAPI app entrypoint."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.api.routes import router
from src.cache.redis import RedisCache, create_redis_client
from src.config import get_settings
from src.research.engine import ResearchEngine


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    # Create Redis client
    redis_client = await create_redis_client(settings.redis_url)
    cache = RedisCache(redis_client, default_ttl=settings.result_ttl_seconds)

    # Create research engine
    engine = ResearchEngine(settings)

    # Attach to app state for dependency injection
    app.state.settings = settings
    app.state.cache = cache
    app.state.engine = engine

    yield

    # Cleanup
    await redis_client.aclose()


app = FastAPI(title="Research Service", lifespan=lifespan)
app.include_router(router)


@app.get("/health")
async def health():
    return {"status": "ok"}
