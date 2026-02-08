"""Web scraping submodule with pluggable loader registry."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .firecrawl_loader import FirecrawlLoader, PageLoader
from .models import ScrapedPage
from .registry import ScraperRegistry

if TYPE_CHECKING:
    from src.config import Settings

__all__ = [
    "FirecrawlLoader",
    "PageLoader",
    "ScrapedPage",
    "ScraperRegistry",
    "build_default_registry",
    "scrape",
]

logger = logging.getLogger(__name__)


def build_default_registry(settings: Settings) -> ScraperRegistry:
    """Build the default scraper registry with configured loader instances."""
    firecrawl = FirecrawlLoader(
        api_key=settings.firecrawl_api_key,
        api_url=settings.firecrawl_api_url,
    )

    registry = ScraperRegistry()

    # TODO: implement a dedicated RedditLoader; for now falls back to FirecrawlLoader
    registry.register(
        patterns=(r".*reddit\.com$", r".*reddit\.de$"),
        loader=firecrawl,
    )

    # Default catch-all: use Firecrawl for any unmatched domain
    registry.set_default(firecrawl)

    return registry


async def scrape(
    urls: list[str],
    registry: ScraperRegistry,
) -> list[ScrapedPage]:
    """Scrape a list of URLs via the loader registry and return markdown content."""
    if not urls:
        return []

    pages: list[ScrapedPage] = []
    for url in urls:
        loader = registry.get_loader(url)
        if loader is None:
            logger.warning("no loader found for %s, skipping", url)
            continue

        page = await loader.load(url)
        if page is not None:
            pages.append(page)

    return pages
