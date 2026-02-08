"""URL loader registry with regex domain matching."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from .firecrawl_loader import PageLoader


@dataclass
class LoaderRegistration:
    """A loader registration with domain patterns."""

    patterns: tuple[str, ...]  # regex patterns for domains
    loader: PageLoader  # a configured loader instance


class ScraperRegistry:
    """Registry mapping URL domain patterns to loader instances."""

    def __init__(self) -> None:
        self._registrations: list[LoaderRegistration] = []
        self._default_loader: PageLoader | None = None

    def register(self, patterns: tuple[str, ...], loader: PageLoader) -> None:
        """Register a loader instance for domain patterns (regex supported)."""
        self._registrations.append(
            LoaderRegistration(patterns=patterns, loader=loader),
        )

    def set_default(self, loader: PageLoader) -> None:
        """Set the default loader for unmatched URLs."""
        self._default_loader = loader

    def get_loader(self, url: str) -> PageLoader | None:
        """Find the loader instance for a given URL."""
        hostname = urlparse(url).hostname or ""

        for reg in self._registrations:
            for pattern in reg.patterns:
                if re.match(pattern, hostname):
                    return reg.loader

        return self._default_loader
