"""Data models for the scrape submodule."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ScrapedPage:
    """A single scraped web page with extracted content."""

    url: str
    title: str = ""
    content: str = ""
    images: list[str] = field(default_factory=list)
