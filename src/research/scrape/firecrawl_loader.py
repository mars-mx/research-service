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
        try:
            response = await self._client.scrape_url(
                url=url,
                formats=["markdown"],
            )
            metadata = (
                response.get("metadata", {}) if isinstance(response, dict) else {}
            )
            markdown = (
                response.get("markdown", "") if isinstance(response, dict) else ""
            )
            # Some Firecrawl versions return a ScrapeResponse object
            if hasattr(response, "markdown"):
                markdown = response.markdown or ""
            if hasattr(response, "metadata"):
                metadata = response.metadata or {}
                if hasattr(metadata, "title"):
                    metadata = {"title": metadata.title}

            if len(markdown) < 100:
                return None

            # Extract title
            title = ""
            if isinstance(metadata, dict):
                title = metadata.get("title", "")

            # Extract images from the response
            images: list[str] = []
            # Check for images field on the response object
            if hasattr(response, "images") and response.images:
                images.extend(response.images)
            # Check for images/image in metadata dict
            if isinstance(metadata, dict):
                meta_images = metadata.get("images", [])
                if isinstance(meta_images, list):
                    images.extend(meta_images)
                meta_image = metadata.get("image", "")
                if isinstance(meta_image, str) and meta_image:
                    images.append(meta_image)
            # Check for images in dict-style response
            if isinstance(response, dict):
                resp_images = response.get("images", [])
                if isinstance(resp_images, list):
                    images.extend(resp_images)
            # Deduplicate while preserving order
            seen: set[str] = set()
            unique_images: list[str] = []
            for img in images:
                if img not in seen:
                    seen.add(img)
                    unique_images.append(img)

            return ScrapedPage(
                url=url,
                title=title,
                content=markdown,
                images=unique_images,
            )
        except Exception:
            logger.warning("scrape failed for %s", url, exc_info=True)
            return None
