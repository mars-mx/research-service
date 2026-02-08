"""URL loader registry with regex domain matching."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass
class LoaderRegistration:
    """A loader registration with domain patterns."""

    patterns: tuple[str, ...]  # regex patterns for domains
    loader_class: type  # the loader class


class ScraperRegistry:
    """Registry mapping URL domain patterns to loader classes."""

    def __init__(self) -> None:
        self._registrations: list[LoaderRegistration] = []
        self._default_loader: type | None = None

    def register(self, patterns: tuple[str, ...], loader_class: type) -> None:
        """Register a loader for domain patterns (regex supported)."""
        self._registrations.append(
            LoaderRegistration(patterns=patterns, loader_class=loader_class),
        )

    def set_default(self, loader_class: type) -> None:
        """Set the default loader for unmatched URLs."""
        self._default_loader = loader_class

    def get_loader(self, url: str) -> type | None:
        """Find the loader class for a given URL."""
        hostname = urlparse(url).hostname or ""

        for reg in self._registrations:
            for pattern in reg.patterns:
                if re.match(pattern, hostname):
                    return reg.loader_class

        return self._default_loader
