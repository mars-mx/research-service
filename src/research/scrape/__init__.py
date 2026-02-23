"""Web scraping submodule with pluggable loader registry."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .firecrawl_loader import FirecrawlLoader, PageLoader
from .models import ScrapedPage
from .reddit_loader import RedditLoader
from .registry import ScraperRegistry

if TYPE_CHECKING:
    from src.config import Settings

__all__ = [
    "FirecrawlLoader",
    "PageLoader",
    "RedditLoader",
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

    reddit = RedditLoader(
        max_comments=settings.reddit_max_comments,
        max_comment_depth=settings.reddit_max_comment_depth,
        min_comment_score=settings.reddit_min_comment_score,
        max_content_length=settings.reddit_max_content_length,
        request_delay=settings.reddit_request_delay,
        user_agent=settings.reddit_user_agent,
    )

    registry = ScraperRegistry()

    registry.register(
        patterns=(r".*reddit\.com$", r".*reddit\.de$", r".*redd\.it$"),
        loader=reddit,
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

    logger.debug("scraping urls", extra={"url_count": len(urls)})
    pages: list[ScrapedPage] = []
    for url in urls:
        loader = registry.get_loader(url)
        if loader is None:
            logger.warning("no loader found, skipping", extra={"url": url})
            continue

        loader_name = type(loader).__name__
        logger.debug("loader selected", extra={"url": url, "loader": loader_name})
        page = await loader.load(url)
        if page is not None:
            pages.append(page)

    logger.debug("scrape batch complete", extra={"urls_attempted": len(urls), "pages_returned": len(pages)})
    return pages
