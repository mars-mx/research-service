"""Research engine — PydanticAI-based pipeline orchestrator."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from pydantic_ai import Agent

from src.api.schemas import (
    ModelUsage,
    ResearchMetadata,
    ResearchResult,
    ResearchSource,
    Usage,
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
from src.research.scrape import ScrapedPage, build_default_registry, scrape
from src.research.search import SearchResult, search

logger = logging.getLogger(__name__)


def _reasoning_tokens(usage: Any) -> int:
    """Extract reasoning tokens from PydanticAI usage details, if present."""
    details = getattr(usage, "details", None) or {}
    return details.get("reasoning_tokens", 0)


@dataclass
class _TokenBucket:
    """Accumulates token usage for a single model/role."""

    model: str
    role: str
    input_tokens: int = 0
    output_tokens: int = 0
    requests: int = 0

    def add(self, inp: int, out: int, reqs: int) -> None:
        self.input_tokens += inp
        self.output_tokens += out
        self.requests += reqs

    def to_model_usage(self) -> ModelUsage:
        return ModelUsage(
            model=self.model,
            role=self.role,
            prompt_tokens=self.input_tokens,
            completion_tokens=self.output_tokens,
            total_tokens=self.input_tokens + self.output_tokens,
            requests=self.requests,
        )


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

    _EMBEDDING_API_KEY_MAP = {
        "openai": "openai_api_key",
        "google": "gemini_api_key",
    }

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._model = f"{settings.llm_provider}:{settings.fast_llm}"
        self._smart_model = f"{settings.llm_provider}:{settings.smart_llm}"
        self._registry = build_default_registry(settings)
        self._embedding_api_key = self._resolve_embedding_api_key()

    def _resolve_embedding_api_key(self) -> str:
        """Pick the correct API key for the configured embedding provider."""
        provider = self._settings.embedding_model.split(":")[0] if ":" in self._settings.embedding_model else "openai"
        attr = self._EMBEDDING_API_KEY_MAP.get(provider, "openai_api_key")
        return getattr(self._settings, attr)

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
        planner_bucket = _TokenBucket(model=self._model, role="planner")
        writer_bucket = _TokenBucket(model=self._smart_model, role="writer")
        embed_bucket = _TokenBucket(model=self._settings.embedding_model, role="embedding")

        logger.info(
            "research pipeline started",
            extra={
                "task_id": task_id,
                "query": query[:100],
                "report_type": report_type,
                "depth": depth,
                "breadth": breadth,
                "model_fast": self._model,
                "model_smart": self._smart_model,
            },
        )
        await emit_event(on_event, "started", {"task_id": task_id})

        # --- Stage 1: Plan sub-queries ---
        await emit_event(on_event, "status", {"step": "planning", "message": "Generating research questions..."})
        all_context: list[str] = []
        all_urls: set[str] = set()
        all_sources: list[ResearchSource] = []
        all_images: list[str] = []

        context_text, urls, sources, images, p_inp, p_out, p_reqs, e_usage = await self._research_level(
            query=query,
            breadth=breadth,
            prior_context="",
            on_event=on_event,
        )
        all_context.append(context_text)
        all_urls.update(urls)
        all_sources.extend(sources)
        all_images.extend(images)
        planner_bucket.add(p_inp, p_out, p_reqs)
        embed_bucket.add(e_usage.get("input_tokens", 0), 0, e_usage.get("requests", 0))
        logger.info(
            "research level completed",
            extra={
                "task_id": task_id,
                "level": 1,
                "total_levels": depth,
                "urls_found": len(urls),
                "sources_count": len(sources),
            },
        )

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
            context_text, urls, sources, images, p_inp, p_out, p_reqs, e_usage = await self._research_level(
                query=query,
                breadth=next_breadth,
                prior_context="\n\n".join(all_context),
                on_event=on_event,
            )
            all_context.append(context_text)
            all_urls.update(urls)
            all_sources.extend(sources)
            all_images.extend(images)
            planner_bucket.add(p_inp, p_out, p_reqs)
            embed_bucket.add(e_usage.get("input_tokens", 0), 0, e_usage.get("requests", 0))
            logger.info(
                "research level completed",
                extra={
                    "task_id": task_id,
                    "level": level + 1,
                    "total_levels": depth,
                    "breadth": next_breadth,
                    "urls_found": len(urls),
                    "sources_count": len(sources),
                },
            )

        # --- Stage 5: Write report ---
        await emit_event(on_event, "status", {"step": "writing", "message": "Generating final report..."})
        combined_context = "\n\n---\n\n".join(all_context)

        # Compress context via embeddings instead of naive word trimming
        words = combined_context.split()
        if len(words) > 25000:
            logger.info(
                "compressing combined context",
                extra={"task_id": task_id, "word_count": len(words)},
            )
            passages = combined_context.split("\n\n---\n\n")
            passages, embed_usage = await compress_context(
                query=query,
                passages=passages,
                api_key=self._embedding_api_key,
                model=self._settings.embedding_model,
                top_k=len(passages),
            )
            embed_bucket.add(embed_usage.get("input_tokens", 0), 0, embed_usage.get("requests", 0))
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
        logger.info(
            "writing report",
            extra={
                "task_id": task_id,
                "context_words": len(combined_context.split()),
                "total_urls": len(all_urls),
                "total_sources": len(all_sources),
                "min_words": min_words,
            },
        )

        writer = Agent(self._smart_model)
        write_result = await writer.run(prompt)
        report = write_result.output
        write_usage = write_result.usage()
        writer_bucket.add(
            write_usage.input_tokens or 0,
            (write_usage.output_tokens or 0) + _reasoning_tokens(write_usage),
            write_usage.requests or 0,
        )

        # Deduplicate sources by URL
        seen_urls: set[str] = set()
        unique_sources: list[ResearchSource] = []
        for src in all_sources:
            if src.url not in seen_urls:
                seen_urls.add(src.url)
                unique_sources.append(src)

        # Build per-model usage (omit buckets with zero requests)
        usage_by_model = [
            b.to_model_usage()
            for b in (planner_bucket, writer_bucket, embed_bucket)
            if b.requests > 0
        ]

        # Aggregate totals
        total_input = planner_bucket.input_tokens + writer_bucket.input_tokens + embed_bucket.input_tokens
        total_output = planner_bucket.output_tokens + writer_bucket.output_tokens + embed_bucket.output_tokens
        total_requests = planner_bucket.requests + writer_bucket.requests + embed_bucket.requests

        now = datetime.now(timezone.utc)
        usage = Usage(
            prompt_tokens=total_input,
            completion_tokens=total_output,
            total_tokens=total_input + total_output,
        )
        result = ResearchResult(
            task_id=task_id,
            status="completed",
            report=report,
            sources=unique_sources,
            source_urls=sorted(all_urls),
            images=all_images,
            usage=usage,
            usage_by_model=usage_by_model,
            metadata=ResearchMetadata(
                requests=total_requests,
                llm_provider=self._settings.llm_provider,
                fast_llm=self._settings.fast_llm,
                smart_llm=self._settings.smart_llm,
            ),
            created_at=now,
        )

        logger.info(
            "research pipeline completed",
            extra={
                "task_id": task_id,
                "sources": len(unique_sources),
                "total_tokens": total_input + total_output,
                "total_requests": total_requests,
                "report_words": len(report.split()),
            },
        )

        await emit_event(on_event, "result", {
            "task_id": task_id,
            "report": report,
            "sources": [s.model_dump() for s in unique_sources],
            "usage": usage.model_dump(),
            "usage_by_model": [u.model_dump() for u in usage_by_model],
        })
        await emit_event(on_event, "done", {})

        return result

    async def _research_level(
        self,
        query: str,
        breadth: int,
        prior_context: str,
        on_event: EventCallback | None,
    ) -> tuple[str, list[str], list[ResearchSource], list[str], int, int, int, dict[str, int]]:
        """Run one level of plan -> search -> scrape -> compress.

        Returns (context_text, urls, sources, images,
                 planner_input, planner_output, planner_requests, embed_usage).
        """
        planner_input = 0
        planner_output = 0
        planner_requests = 0
        embed_usage: dict[str, int] = {"input_tokens": 0, "requests": 0}

        # Plan sub-queries
        if prior_context:
            prompt = format_follow_up_prompt(query, breadth, prior_context)
        else:
            prompt = format_plan_prompt(query, breadth)

        planner = Agent(self._model, output_type=list[str])
        plan_result = await planner.run(prompt)
        sub_queries = plan_result.output[:breadth]
        plan_usage = plan_result.usage()
        planner_input += plan_usage.input_tokens or 0
        planner_output += (plan_usage.output_tokens or 0) + _reasoning_tokens(plan_usage)
        planner_requests += plan_usage.requests or 0
        logger.debug(
            "sub-queries planned",
            extra={
                "query": query[:100],
                "sub_queries": sub_queries,
                "has_prior_context": bool(prior_context),
            },
        )

        # Search all sub-queries in parallel
        await emit_event(on_event, "status", {"step": "researching", "message": f"Searching {len(sub_queries)} queries..."})
        search_tasks = [
            search(q, api_key=self._settings.tavily_api_key)
            for q in sub_queries
        ]
        search_results_list: list[list[SearchResult]] = await asyncio.gather(*search_tasks)
        total_results = sum(len(r) for r in search_results_list)
        logger.info(
            "search completed",
            extra={
                "query": query[:100],
                "queries_searched": len(sub_queries),
                "total_results": total_results,
            },
        )

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
            registry=self._registry,
        )
        logger.info(
            "scrape completed",
            extra={
                "urls_attempted": len(urls_to_scrape),
                "pages_returned": len(pages),
            },
        )

        # Build passages from scraped content
        passages = [f"Source: {p.url}\nTitle: {p.title}\n\n{p.content}" for p in pages]

        # Compress context via embeddings
        passage_count_before = len(passages)
        if passages:
            await emit_event(on_event, "status", {"step": "researching", "message": "Compressing context..."})
            passages, embed_usage = await compress_context(
                query=query,
                passages=passages,
                api_key=self._embedding_api_key,
                model=self._settings.embedding_model,
                top_k=10,
            )
            logger.info(
                "context compressed",
                extra={
                    "passages_in": passage_count_before,
                    "passages_out": len(passages),
                    "embed_tokens": embed_usage.get("input_tokens", 0),
                },
            )

        context_text = "\n\n---\n\n".join(passages)

        # Collect structured outputs
        all_urls = [r.url for r in all_search_results]
        sources = [
            ResearchSource(url=r.url, title=r.title)
            for r in all_search_results
        ]
        images = [img for p in pages for img in p.images]

        return context_text, all_urls, sources, images, planner_input, planner_output, planner_requests, embed_usage


def _find_tier(report_type: str, depth: int, breadth: int) -> DepthTier | None:
    """Find a matching DepthTier by its parameters, or return None."""
    for tier in DEPTH_TIERS.values():
        if tier.report_type == report_type and tier.depth == depth and tier.breadth == breadth:
            return tier
    return None
