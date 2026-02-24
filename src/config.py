"""Pydantic Settings — loads configuration from environment variables."""

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "extra": "ignore"}

    api_key: str

    openai_api_key: str = ""
    anthropic_api_key: str = ""
    gemini_api_key: str = ""
    firecrawl_api_key: str = ""
    firecrawl_api_url: str = ""
    tavily_api_key: str = ""

    vercel_ai_gateway_api_key: str = ""

    redis_url: str = "redis://localhost:6379"
    allowed_callback_hosts: str = ""
    result_ttl_seconds: int = 3600

    llm_provider: str = "openai"
    fast_llm: str = "gpt-4o-mini"
    smart_llm: str = "gpt-4o"
    embedding_model: str = "openai:text-embedding-3-small"
    max_depth_tier: str = "deep"
    log_level: str = "INFO"

    reddit_max_comments: int = 10
    reddit_max_comment_depth: int = 3
    reddit_min_comment_score: int = 2
    reddit_max_content_length: int = 15000
    reddit_request_delay: float = 0.5
    reddit_user_agent: str = "research-service/0.1.0"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
