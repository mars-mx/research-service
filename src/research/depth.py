"""Depth tier configuration for the research pipeline."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DepthTier:
    """Configuration for a research depth preset."""

    name: str
    report_type: str
    depth: int
    breadth: int
    min_words: int


DEPTH_TIERS: dict[str, DepthTier] = {
    "quick": DepthTier(name="quick", report_type="research_report", depth=1, breadth=2, min_words=500),
    "standard": DepthTier(name="standard", report_type="research_report", depth=2, breadth=4, min_words=1000),
    "deep": DepthTier(name="deep", report_type="detailed_report", depth=3, breadth=6, min_words=2000),
}
