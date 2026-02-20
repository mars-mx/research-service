"""Research engine unit tests."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api.schemas import ResearchResult
from src.research.engine import ResearchEngine, resolve_params


# --- resolve_params tests (synchronous) ---


def test_resolve_params_quick():
    assert resolve_params("quick", None, None, None) == ("research_report", 1, 2)


def test_resolve_params_standard():
    assert resolve_params("standard", None, None, None) == ("research_report", 2, 4)


def test_resolve_params_deep():
    assert resolve_params("deep", None, None, None) == ("detailed_report", 3, 6)


def test_resolve_params_custom_overrides():
    assert resolve_params(None, 5, 8, "custom_report") == ("custom_report", 5, 8)


def test_resolve_params_defaults_when_none():
    assert resolve_params(None, None, None, None) == ("research_report", 2, 4)


def test_resolve_params_depth_takes_precedence():
    """When depth tier is set, custom overrides are ignored."""
    assert resolve_params("quick", 10, 20, "custom") == ("research_report", 1, 2)


# --- ResearchEngine tests with mocked dependencies ---


def _mock_settings(**overrides):
    defaults = dict(
        llm_provider="openai",
        fast_llm="gpt-4o-mini",
        smart_llm="gpt-4o",
        openai_api_key="test-key",
        tavily_api_key="test-tavily",
        firecrawl_api_key="test-firecrawl",
        firecrawl_api_url="",
        gemini_api_key="test-gemini",
        embedding_model="openai:text-embedding-3-small",
    )
    defaults.update(overrides)
    settings = MagicMock()
    for k, v in defaults.items():
        setattr(settings, k, v)
    return settings


def _mock_usage(input_tokens=10, output_tokens=20, details=None):
    usage = MagicMock()
    usage.input_tokens = input_tokens
    usage.output_tokens = output_tokens
    usage.requests = 1
    usage.details = details or {}
    return usage


def _mock_agent_result(output, input_tokens=10, output_tokens=20):
    result = MagicMock()
    result.output = output
    result.usage = MagicMock(return_value=_mock_usage(input_tokens, output_tokens))
    return result


@pytest.mark.asyncio
@patch("src.research.engine.compress_context", new_callable=AsyncMock)
@patch("src.research.engine.scrape", new_callable=AsyncMock)
@patch("src.research.engine.search", new_callable=AsyncMock)
@patch("src.research.engine.Agent")
@patch("src.research.engine.build_default_registry")
async def test_engine_run_single_depth(mock_build_registry, mock_agent_cls, mock_search, mock_scrape, mock_compress):
    """Test a depth=1 research run with mocked external calls."""
    settings = _mock_settings()
    engine = ResearchEngine(settings)

    # Mock planner agent (returns sub-queries)
    plan_result = _mock_agent_result(["query about AI", "query about ML"])
    # Mock writer agent (returns report)
    write_result = _mock_agent_result("# Report\n\nSome content", input_tokens=100, output_tokens=500)

    mock_agent_instance = AsyncMock()
    mock_agent_instance.run = AsyncMock(side_effect=[plan_result, write_result])
    mock_agent_cls.return_value = mock_agent_instance

    # Mock search results
    search_result = MagicMock()
    search_result.url = "https://example.com/article"
    search_result.title = "Example Article"
    search_result.snippet = "An article about AI"
    mock_search.return_value = [search_result]

    # Mock scrape results
    scraped_page = MagicMock()
    scraped_page.url = "https://example.com/article"
    scraped_page.title = "Example Article"
    scraped_page.content = "Full article content about AI advances..."
    scraped_page.images = []
    mock_scrape.return_value = [scraped_page]

    # Mock compress (pass-through, returns tuple of passages + usage)
    mock_compress.side_effect = lambda **kwargs: (kwargs["passages"], {"input_tokens": 0, "requests": 0})

    result = await engine.run(query="advances in AI", depth=1, breadth=2)

    assert isinstance(result, ResearchResult)
    assert result.status == "completed"
    assert result.report == "# Report\n\nSome content"
    assert len(result.sources) >= 1
    assert result.usage.prompt_tokens > 0
    assert result.usage.completion_tokens > 0
    assert result.usage.total_tokens == result.usage.prompt_tokens + result.usage.completion_tokens
    assert result.metadata.llm_provider == "openai"
    assert result.metadata.fast_llm == "gpt-4o-mini"
    assert result.metadata.smart_llm == "gpt-4o"


@pytest.mark.asyncio
@patch("src.research.engine.compress_context", new_callable=AsyncMock)
@patch("src.research.engine.scrape", new_callable=AsyncMock)
@patch("src.research.engine.search", new_callable=AsyncMock)
@patch("src.research.engine.Agent")
@patch("src.research.engine.build_default_registry")
async def test_engine_emits_events(mock_build_registry, mock_agent_cls, mock_search, mock_scrape, mock_compress):
    """Test that the engine emits SSE events via the callback."""
    settings = _mock_settings()
    engine = ResearchEngine(settings)

    plan_result = _mock_agent_result(["query 1"])
    write_result = _mock_agent_result("Report content")

    mock_agent_instance = AsyncMock()
    mock_agent_instance.run = AsyncMock(side_effect=[plan_result, write_result])
    mock_agent_cls.return_value = mock_agent_instance

    mock_search.return_value = []
    mock_scrape.return_value = []
    mock_compress.side_effect = lambda **kwargs: (kwargs["passages"], {"input_tokens": 0, "requests": 0})

    events: list[tuple[str, dict]] = []

    async def capture_event(event: str, data: dict) -> None:
        events.append((event, data))

    await engine.run(query="test", depth=1, breadth=1, on_event=capture_event)

    event_types = [e[0] for e in events]
    assert "started" in event_types
    assert "status" in event_types
    assert "result" in event_types
    assert "done" in event_types

    # Verify the result event includes usage data
    result_event = next(data for etype, data in events if etype == "result")
    assert "usage" in result_event
    assert "prompt_tokens" in result_event["usage"]
    assert "completion_tokens" in result_event["usage"]
    assert "total_tokens" in result_event["usage"]


@pytest.mark.asyncio
@patch("src.research.engine.compress_context", new_callable=AsyncMock)
@patch("src.research.engine.scrape", new_callable=AsyncMock)
@patch("src.research.engine.search", new_callable=AsyncMock)
@patch("src.research.engine.Agent")
@patch("src.research.engine.build_default_registry")
async def test_engine_recursive_depth(mock_build_registry, mock_agent_cls, mock_search, mock_scrape, mock_compress):
    """Test that depth=2 makes two research levels."""
    settings = _mock_settings()
    engine = ResearchEngine(settings)

    # 2 planner calls (depth=2) + 1 writer call = 3 total
    plan_result_1 = _mock_agent_result(["initial query"])
    plan_result_2 = _mock_agent_result(["follow-up query"])
    write_result = _mock_agent_result("Deep report")

    mock_agent_instance = AsyncMock()
    mock_agent_instance.run = AsyncMock(side_effect=[plan_result_1, plan_result_2, write_result])
    mock_agent_cls.return_value = mock_agent_instance

    mock_search.return_value = []
    mock_scrape.return_value = []
    mock_compress.side_effect = lambda **kwargs: (kwargs["passages"], {"input_tokens": 0, "requests": 0})

    result = await engine.run(query="test", depth=2, breadth=2)

    assert result.status == "completed"
    # Planner called twice (once per depth level) + writer once = 3
    assert mock_agent_instance.run.call_count == 3
