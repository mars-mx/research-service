"""Research engine — PydanticAI-based pipeline orchestrator."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic_ai import Agent

from src.api.schemas import (
    ResearchMetadata,
    ResearchResult,
    ResearchSource,
)
from src.config import Settings
from src.research.compress import compress_context
from src.research.depth import DEPTH_TIERS, DepthTier
from src.research.events import EventCallback, emit_event
from src.research.prompts import (
    format_follow_up_prompt,
    format_plan_prompt,
    format_report_prompt,
)
from src.research.scrape import ScrapedPage, scrape
from src.research.search import SearchResult, search

logger = logging.getLogger(__name__)


def _reasoning_tokens(usage: Any) -> int:
    """Extract reasoning tokens from PydanticAI usage details, if present."""
    details = getattr(usage, "details", None) or {}
    return details.get("reasoning_tokens", 0)


def resolve_params(
    depth: str | None,
    research_depth: int | None,
    research_breadth: int | None,
    report_type: str | None,
) -> tuple[str, int, int]:
    """Resolve depth tier or custom overrides into (report_type, depth, breadth)."""
    if depth is not None:
        tier = DEPTH_TIERS[depth]
        return (tier.report_type, tier.depth, tier.breadth)
    return (
        report_type or "research_report",
        research_depth or 2,
        research_breadth or 4,
    )


class ResearchEngine:
    """Orchestrates the plan -> search -> scrape -> compress -> write pipeline."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._model = f"{settings.llm_provider}:{settings.fast_llm}"
        self._smart_model = f"{settings.llm_provider}:{settings.smart_llm}"

    async def run(
        self,
        query: str,
        report_type: str = "research_report",
        depth: int = 2,
        breadth: int = 4,
        on_event: EventCallback | None = None,
    ) -> ResearchResult:
        """Execute the full research pipeline and return a result."""
        task_id = uuid.uuid4().hex[:12]
        total_input = 0
        total_output = 0
        total_requests = 0

        await emit_event(on_event, "started", {"task_id": task_id})

        # --- Stage 1: Plan sub-queries ---
        await emit_event(on_event, "status", {"step": "planning", "message": "Generating research questions..."})
        all_context: list[str] = []
        all_urls: set[str] = set()
        all_sources: list[ResearchSource] = []
        all_images: list[str] = []

        context_text, urls, sources, images, inp, out, reqs = await self._research_level(
            query=query,
            breadth=breadth,
            prior_context="",
            on_event=on_event,
        )
        all_context.append(context_text)
        all_urls.update(urls)
        all_sources.extend(sources)
        all_images.extend(images)
        total_input += inp
        total_output += out
        total_requests += reqs

        # --- Recursive depth levels ---
        for level in range(1, depth):
            await emit_event(
                on_event,
                "status",
                {
                    "step": "researching",
                    "message": f"Depth level {level + 1}/{depth} — generating follow-up queries...",
                },
            )
            next_breadth = max(2, breadth // (2 ** level))
            context_text, urls, sources, images, inp, out, reqs = await self._research_level(
                query=query,
                breadth=next_breadth,
                prior_context="\n\n".join(all_context),
                on_event=on_event,
            )
            all_context.append(context_text)
            all_urls.update(urls)
            all_sources.extend(sources)
            all_images.extend(images)
            total_input += inp
            total_output += out
            total_requests += reqs

        # --- Stage 5: Write report ---
        await emit_event(on_event, "status", {"step": "writing", "message": "Generating final report..."})
        combined_context = "\n\n---\n\n".join(all_context)

        # Compress context via embeddings instead of naive word trimming
        words = combined_context.split()
        if len(words) > 25000:
            passages = combined_context.split("\n\n---\n\n")
            passages, embed_usage = await compress_context(
                query=query,
                passages=passages,
                api_key=self._settings.openai_api_key,
                model=self._settings.embedding_model,
                top_k=len(passages),
            )
            total_input += embed_usage.get("input_tokens", 0)
            total_requests += embed_usage.get("requests", 0)
            combined_context = "\n\n---\n\n".join(passages)

        # Determine min_words from depth tier config if available
        tier = _find_tier(report_type, depth, breadth)
        if tier is not None:
            min_words = tier.min_words
        else:
            detailed = report_type == "detailed_report"
            min_words = 2000 if detailed else 1000

        detailed = report_type == "detailed_report"
        prompt = format_report_prompt(query, combined_context, detailed=detailed, min_words=min_words)

        writer = Agent(self._smart_model)
        write_result = await writer.run(prompt)
        report = write_result.output
        total_input += write_result.usage.input_tokens or 0
        total_output += (write_result.usage.output_tokens or 0) + _reasoning_tokens(write_result.usage)
        total_requests += write_result.usage.requests or 0

        # Deduplicate sources by URL
        seen_urls: set[str] = set()
        unique_sources: list[ResearchSource] = []
        for src in all_sources:
            if src.url not in seen_urls:
                seen_urls.add(src.url)
                unique_sources.append(src)

        now = datetime.now(timezone.utc)
        result = ResearchResult(
            task_id=task_id,
            status="completed",
            report=report,
            sources=unique_sources,
            source_urls=sorted(all_urls),
            images=all_images,
            metadata=ResearchMetadata(
                input_tokens=total_input,
                output_tokens=total_output,
                total_tokens=total_input + total_output,
                requests=total_requests,
                llm_provider=self._settings.llm_provider,
                fast_llm=self._settings.fast_llm,
                smart_llm=self._settings.smart_llm,
            ),
            created_at=now,
        )

        await emit_event(on_event, "result", {"task_id": task_id, "report": report, "sources": [s.model_dump() for s in unique_sources]})
        await emit_event(on_event, "done", {})

        return result

    async def _research_level(
        self,
        query: str,
        breadth: int,
        prior_context: str,
        on_event: EventCallback | None,
    ) -> tuple[str, list[str], list[ResearchSource], list[str], int, int, int]:
        """Run one level of plan -> search -> scrape -> compress.

        Returns (context_text, urls, sources, images, input_tokens, output_tokens, requests).
        """
        total_input = 0
        total_output = 0
        total_requests = 0

        # Plan sub-queries
        if prior_context:
            prompt = format_follow_up_prompt(query, breadth, prior_context)
        else:
            prompt = format_plan_prompt(query, breadth)

        planner = Agent(self._model, output_type=list[str])
        plan_result = await planner.run(prompt)
        sub_queries = plan_result.output[:breadth]
        total_input += plan_result.usage.input_tokens or 0
        total_output += (plan_result.usage.output_tokens or 0) + _reasoning_tokens(plan_result.usage)
        total_requests += plan_result.usage.requests or 0

        # Search all sub-queries in parallel
        await emit_event(on_event, "status", {"step": "researching", "message": f"Searching {len(sub_queries)} queries..."})
        search_tasks = [
            search(q, api_key=self._settings.tavily_api_key)
            for q in sub_queries
        ]
        search_results_list: list[list[SearchResult]] = await asyncio.gather(*search_tasks)

        # Collect URLs and emit findings
        all_search_results: list[SearchResult] = []
        for results in search_results_list:
            for r in results:
                all_search_results.append(r)
                await emit_event(on_event, "finding", {"source": r.url, "summary": r.snippet[:200]})

        urls_to_scrape = list({r.url for r in all_search_results})

        # Scrape in parallel (Firecrawl handles batching internally)
        await emit_event(on_event, "status", {"step": "researching", "message": f"Scraping {len(urls_to_scrape)} pages..."})
        pages: list[ScrapedPage] = await scrape(
            urls_to_scrape,
            api_key=self._settings.firecrawl_api_key,
            api_url=self._settings.firecrawl_api_url,
        )

        # Build passages from scraped content
        passages = [f"Source: {p.url}\nTitle: {p.title}\n\n{p.content}" for p in pages]

        # Compress context via embeddings
        if passages:
            await emit_event(on_event, "status", {"step": "researching", "message": "Compressing context..."})
            passages, embed_usage = await compress_context(
                query=query,
                passages=passages,
                api_key=self._settings.openai_api_key,
                model=self._settings.embedding_model,
                top_k=10,
            )
            total_input += embed_usage.get("input_tokens", 0)
            total_requests += embed_usage.get("requests", 0)

        context_text = "\n\n---\n\n".join(passages)

        # Collect structured outputs
        all_urls = [r.url for r in all_search_results]
        sources = [
            ResearchSource(url=r.url, title=r.title)
            for r in all_search_results
        ]
        images = [img for p in pages for img in p.images]

        return context_text, all_urls, sources, images, total_input, total_output, total_requests


def _find_tier(report_type: str, depth: int, breadth: int) -> DepthTier | None:
    """Find a matching DepthTier by its parameters, or return None."""
    for tier in DEPTH_TIERS.values():
        if tier.report_type == report_type and tier.depth == depth and tier.breadth == breadth:
            return tier
    return None
