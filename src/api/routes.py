"""POST /research, GET /research/{id}, GET /health endpoint handlers."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from src.api.schemas import ResearchRequest, ResearchResult
from src.auth.dependencies import verify_api_key
from src.cache.redis import RedisCache
from src.config import Settings
from src.research.engine import EventCallback, ResearchEngine, resolve_params
from src.research.tasks import run_background_research, validate_callback_url

router = APIRouter(dependencies=[Depends(verify_api_key)])


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
    report_type, depth, breadth = resolve_params(
        body.depth, body.research_depth, body.research_breadth, body.report_type
    )

    # Validate callback_url if provided
    if body.callback_url:
        if not validate_callback_url(body.callback_url, settings.allowed_callback_hosts):
            raise HTTPException(
                status_code=422,
                detail="callback_url host not in ALLOWED_CALLBACK_HOSTS",
            )

    if body.mode == "background":
        if not body.callback_url:
            raise HTTPException(
                status_code=422,
                detail="callback_url is required for background mode",
            )

        # Fire-and-forget background task
        asyncio.create_task(
            run_background_research(
                engine=engine,
                cache=cache,
                settings=settings,
                query=body.query,
                report_type=report_type,
                depth=depth,
                breadth=breadth,
                callback_url=body.callback_url,
            )
        )
        return {
            "status": "accepted",
            "message": "Research started. Results will be sent to callback URL.",
        }

    # Streaming mode
    async def event_generator():
        queue: asyncio.Queue[tuple[str, dict[str, Any]] | None] = asyncio.Queue()

        async def on_event(event: str, data: dict[str, Any]) -> None:
            await queue.put((event, data))

        async def run_and_signal_done():
            try:
                result = await engine.run(
                    query=body.query,
                    report_type=report_type,
                    depth=depth,
                    breadth=breadth,
                    on_event=on_event,
                )
                # Cache the result
                await cache.set(result.task_id, result, ttl=settings.result_ttl_seconds)

                # Fire callback if provided
                if body.callback_url:
                    from src.research.tasks import post_callback

                    await post_callback(
                        body.callback_url,
                        {
                            "task_id": result.task_id,
                            "status": "completed",
                            "result_url": f"/research/{result.task_id}",
                        },
                    )
            except Exception:
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
            if not task.done():
                task.cancel()

    return EventSourceResponse(event_generator())


@router.get("/research/{task_id}")
async def get_research(
    task_id: str,
    cache: RedisCache = Depends(_get_cache),
):
    result = await cache.get(task_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Result not found or expired")
    return result
