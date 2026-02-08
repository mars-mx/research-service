"""Pydantic Settings — loads configuration from environment variables."""

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "extra": "ignore"}

    api_key: str

    openai_api_key: str = ""
    anthropic_api_key: str = ""
    firecrawl_api_key: str = ""
    firecrawl_api_url: str = ""
    tavily_api_key: str = ""

    redis_url: str = "redis://localhost:6379"
    allowed_callback_hosts: str = ""
    result_ttl_seconds: int = 3600

    llm_provider: str = "openai"
    fast_llm: str = "gpt-4o-mini"
    smart_llm: str = "gpt-4o"
    embedding_model: str = "openai:text-embedding-3-small"
    max_depth_tier: str = "deep"
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
