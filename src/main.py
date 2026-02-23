"""FastAPI app entrypoint."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.api.routes import router
from src.cache.redis import RedisCache, create_redis_client
from src.config import get_settings
from src.logging_config import setup_logging
from src.research.engine import ResearchEngine

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    # Initialize logging FIRST so all subsequent operations produce JSON logs
    setup_logging(settings.log_level)
    logger.info("starting research service")

    # Create Redis client
    redis_client = await create_redis_client(settings.redis_url)
    cache = RedisCache(redis_client, default_ttl=settings.result_ttl_seconds)

    # Create research engine
    engine = ResearchEngine(settings)

    # Attach to app state for dependency injection
    app.state.settings = settings
    app.state.cache = cache
    app.state.engine = engine

    logger.info(
        "research service ready",
        extra={
            "llm_provider": settings.llm_provider,
            "fast_llm": settings.fast_llm,
            "smart_llm": settings.smart_llm,
            "embedding_model": settings.embedding_model,
        },
    )

    yield

    # Cleanup
    logger.info("shutting down research service")
    await redis_client.aclose()


app = FastAPI(title="Research Service", lifespan=lifespan)
app.include_router(router)


@app.get("/health")
async def health():
    return {"status": "ok"}
