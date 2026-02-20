"""Request/response Pydantic models."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class ResearchRequest(BaseModel):
    query: str
    mode: Literal["stream", "background"]
    depth: Literal["quick", "standard", "deep"] | None = None
    research_depth: int | None = None
    research_breadth: int | None = None
    report_type: str | None = None
    callback_url: str | None = None


class ResearchSource(BaseModel):
    url: str
    title: str


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ResearchMetadata(BaseModel):
    requests: int = 0
    agent: str = ""
    llm_provider: str = ""
    fast_llm: str = ""
    smart_llm: str = ""


class ResearchResult(BaseModel):
    task_id: str
    status: str = "completed"
    report: str = ""
    sources: list[ResearchSource] = []
    source_urls: list[str] = []
    images: list[str] = []
    usage: Usage = Usage()
    metadata: ResearchMetadata = ResearchMetadata()
    created_at: datetime
    expires_at: datetime | None = None
