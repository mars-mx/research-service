"""Firecrawl page loader implementation."""

from __future__ import annotations

import logging
from typing import Protocol

from firecrawl import AsyncFirecrawl

from .models import ScrapedPage

logger = logging.getLogger(__name__)


class PageLoader(Protocol):
    """Protocol for page loaders."""

    async def load(self, url: str) -> ScrapedPage | None: ...


class FirecrawlLoader:
    """Loads pages using the Firecrawl API."""

    def __init__(self, api_key: str, api_url: str = "") -> None:
        kwargs: dict = {"api_key": api_key}
        if api_url:
            kwargs["api_url"] = api_url
        self._client = AsyncFirecrawl(**kwargs)

    async def load(self, url: str) -> ScrapedPage | None:
        """Scrape a single URL via Firecrawl and return a ScrapedPage."""
        logger.debug("firecrawl loading", extra={"url": url})
        try:
            response = await self._client.scrape(
                url=url,
                formats=["markdown"],
            )
            markdown = response.markdown or ""

            if len(markdown) < 100:
                logger.debug("firecrawl content too short, discarding", extra={"url": url, "length": len(markdown)})
                return None

            title = ""
            if response.metadata:
                title = response.metadata.title or ""

            # Deduplicate images while preserving order
            images: list[str] = []
            seen: set[str] = set()
            for img in response.images or []:
                if img not in seen:
                    seen.add(img)
                    images.append(img)

            logger.debug(
                "firecrawl loaded",
                extra={"url": url, "title": title[:80], "content_length": len(markdown), "image_count": len(images)},
            )
            return ScrapedPage(
                url=url,
                title=title,
                content=markdown,
                images=images,
            )
        except Exception:
            logger.warning("firecrawl scrape failed", extra={"url": url}, exc_info=True)
            return None
