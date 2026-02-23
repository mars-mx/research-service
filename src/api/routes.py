"""POST /research, GET /research/{id}, GET /health endpoint handlers."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from src.api.schemas import ResearchRequest
from src.api.service import (
    get_research_result,
    start_background_research,
    stream_research,
)
from src.auth.dependencies import require_api_key
from src.cache.redis import RedisCache
from src.config import Settings
from src.research.engine import ResearchEngine
from src.research.tasks import validate_callback_url

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_api_key)])


def _get_engine(request: Request) -> ResearchEngine:
    return request.app.state.engine


def _get_cache(request: Request) -> RedisCache:
    return request.app.state.cache


def _get_settings(request: Request) -> Settings:
    return request.app.state.settings


@router.post("/research")
async def create_research(
    body: ResearchRequest,
    request: Request,
    engine: ResearchEngine = Depends(_get_engine),
    cache: RedisCache = Depends(_get_cache),
    settings: Settings = Depends(_get_settings),
):
    logger.info(
        "research request received",
        extra={"query": body.query[:100], "mode": body.mode, "depth": body.depth},
    )

    # Validate callback_url if provided
    if body.callback_url:
        if not validate_callback_url(body.callback_url, settings.allowed_callback_hosts):
            logger.warning("invalid callback URL rejected", extra={"callback_url": body.callback_url})
            raise HTTPException(
                status_code=422,
                detail="Invalid callback URL",
            )

    if body.mode == "background":
        if not body.callback_url:
            logger.warning("background mode missing callback_url")
            raise HTTPException(
                status_code=422,
                detail="callback_url is required for background mode",
            )
        return await start_background_research(engine, cache, settings, body)

    # Streaming mode
    return EventSourceResponse(stream_research(engine, cache, settings, body))


@router.get("/research/{task_id}")
async def get_research(
    task_id: str,
    cache: RedisCache = Depends(_get_cache),
):
    result = await get_research_result(cache, task_id)
    if result is None:
        logger.info("research result not found", extra={"task_id": task_id})
        raise HTTPException(status_code=404, detail="Result not found or expired")
    return result
