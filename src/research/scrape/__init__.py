"""Web scraping submodule with pluggable loader registry."""

from __future__ import annotations

import logging

from .firecrawl_loader import FirecrawlLoader, PageLoader
from .models import ScrapedPage
from .registry import ScraperRegistry

__all__ = [
    "FirecrawlLoader",
    "PageLoader",
    "ScrapedPage",
    "ScraperRegistry",
    "scrape",
]

logger = logging.getLogger(__name__)


def _build_default_registry() -> ScraperRegistry:
    """Build the default scraper registry."""
    registry = ScraperRegistry()

    # TODO: implement a dedicated RedditLoader; for now falls back to FirecrawlLoader
    registry.register(
        patterns=(r".*reddit\.com$", r".*reddit\.de$"),
        loader_class=FirecrawlLoader,
    )

    # Default catch-all: use Firecrawl for any unmatched domain
    registry.set_default(FirecrawlLoader)

    return registry


async def scrape(
    urls: list[str],
    api_key: str,
    api_url: str = "",
) -> list[ScrapedPage]:
    """Scrape a list of URLs via the loader registry and return markdown content."""
    if not urls:
        return []

    registry = _build_default_registry()

    pages: list[ScrapedPage] = []
    for url in urls:
        loader_class = registry.get_loader(url)
        if loader_class is None:
            logger.warning("no loader found for %s, skipping", url)
            continue

        loader = loader_class(api_key=api_key, api_url=api_url)
        page = await loader.load(url)
        if page is not None:
            pages.append(page)

    return pages
