"""Firecrawl web scraping wrapper."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from firecrawl import AsyncFirecrawl

logger = logging.getLogger(__name__)


@dataclass
class ScrapedPage:
    url: str
    title: str = ""
    content: str = ""
    images: list[str] = field(default_factory=list)


async def scrape(
    urls: list[str],
    api_key: str,
    api_url: str = "",
) -> list[ScrapedPage]:
    """Scrape a list of URLs via Firecrawl and return markdown content."""
    if not urls:
        return []

    kwargs: dict = {"api_key": api_key}
    if api_url:
        kwargs["api_url"] = api_url
    client = AsyncFirecrawl(**kwargs)

    pages: list[ScrapedPage] = []
    for url in urls:
        try:
            response = await client.scrape_url(
                url=url,
                formats=["markdown"],
            )
            metadata = response.get("metadata", {}) if isinstance(response, dict) else {}
            markdown = response.get("markdown", "") if isinstance(response, dict) else ""
            # Some Firecrawl versions return a ScrapeResponse object
            if hasattr(response, "markdown"):
                markdown = response.markdown or ""
            if hasattr(response, "metadata"):
                metadata = response.metadata or {}
                if hasattr(metadata, "title"):
                    metadata = {"title": metadata.title}

            if len(markdown) < 100:
                continue

            pages.append(
                ScrapedPage(
                    url=url,
                    title=metadata.get("title", "") if isinstance(metadata, dict) else "",
                    content=markdown,
                )
            )
        except Exception:
            logger.warning("scrape failed for %s", url, exc_info=True)

    return pages
