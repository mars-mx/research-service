"""Tavily web search wrapper."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from tavily import AsyncTavilyClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SearchResult:
    url: str
    title: str
    snippet: str


async def search(
    query: str,
    api_key: str,
    max_results: int = 5,
) -> list[SearchResult]:
    """Search the web via Tavily and return structured results."""
    logger.debug("searching", extra={"query": query[:100], "max_results": max_results})
    client = AsyncTavilyClient(api_key=api_key)
    try:
        response = await client.search(
            query=query,
            max_results=max_results,
            include_answer=False,
        )
    except Exception:
        logger.warning("search failed", extra={"query": query[:100]}, exc_info=True)
        return []

    results: list[SearchResult] = []
    for item in response.get("results", []):
        results.append(
            SearchResult(
                url=item.get("url", ""),
                title=item.get("title", ""),
                snippet=item.get("content", ""),
            )
        )
    logger.debug("search results received", extra={"query": query[:100], "result_count": len(results)})
    return results
