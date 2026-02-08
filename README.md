# Research Service

A simple HTTP service that performs autonomous multi-step web research using a custom [PydanticAI](https://ai.pydantic.dev/)-based research engine with [Tavily](https://tavily.com/) for web search and [Firecrawl](https://www.firecrawl.dev/) for web scraping. Built with FastAPI — runs anywhere you can run a Python process.

## Architecture

```
  Client ──────────►  FastAPI + Uvicorn  ──────────►  Redis
  (API Key in header)     │                          (result cache, 1hr TTL)
                          │
                     PydanticAI Engine
                     (Tavily + Firecrawl + Embeddings)
```

The service is a single process that listens on a port. The research pipeline plans sub-questions, searches the web via Tavily, scrapes pages with Firecrawl, compresses context using OpenAI embeddings with cosine similarity, and writes a final report — all orchestrated by PydanticAI. Point it at a Redis instance, set your API keys, and you're running. No special infrastructure required.

### Request Flow

**Streaming Mode (SSE):**
```
Client ──POST /research (stream=true)──► Service
  ◄── SSE stream: status updates, intermediate findings, final report
  (if callback_url provided: Service also POSTs callback on completion)
```

Both modes always cache results in Redis, so even if the stream disconnects the result can be retrieved via `GET /research/{task_id}` or the callback. (Note: streaming mode currently does not cancel research on client disconnect — the task runs to completion and the result is always cached.)

**Background Mode (Webhook Callback):**
```
Client ──POST /research (callback_url=...)──► Service
  ◄── 202 Accepted { task_id }

Service runs research ──► stores result in Redis (1hr TTL)
                       ──► POST callback_url with { task_id, status }

Client ──GET /research/{task_id}──► Service ──► Redis ──► result
```

## Core Components

| Component | Technology | Purpose |
|---|---|---|
| Web Framework | [FastAPI](https://fastapi.tiangolo.com/) | HTTP API, SSE streaming, request validation |
| ASGI Server | [Uvicorn](https://www.uvicorn.org/) | Production ASGI server |
| Research Engine | Custom [PydanticAI](https://ai.pydantic.dev/) pipeline | plan → search → scrape → compress → write |
| Web Search | [Tavily](https://tavily.com/) | Async web search API |
| Web Scraping | [Firecrawl](https://www.firecrawl.dev/) | Website scraping (self-hosted or cloud) |
| Context Compression | OpenAI Embeddings + cosine similarity | Relevant context extraction via vector similarity |
| Result Cache | [Redis](https://redis.io/) | Temporary result storage with 1hr TTL |

### Why a Custom Engine?

The service originally used GPT Researcher but was replaced with a custom PydanticAI-based pipeline for several reasons:

- **Structured LLM outputs with real token tracking** — PydanticAI validates outputs against Pydantic models and exposes actual token usage via `result.usage`, enabling accurate cost tracking
- **Lighter dependency footprint** — ~10 dependencies vs ~25+ pulled in by LangChain/gpt-researcher, reducing image size and attack surface
- **Full control over the research pipeline** — each stage (plan, search, scrape, compress, write) is a discrete, testable unit rather than an opaque library call
- **Provider-agnostic LLM support** — PydanticAI natively supports OpenAI, Anthropic, Google, Ollama, and other providers without requiring a separate compatibility layer like LiteLLM

## Project Structure

```
research-service/
├── .github/
│   └── workflows/
│       └── ci.yml                  # Build, test, push image to GHCR
├── README.md
├── Dockerfile
├── docker-compose.yml              # Local dev: app + Redis + Firecrawl
├── pyproject.toml                  # Dependencies & project config (uv)
├── uv.lock                         # Lockfile
├── .env.example                    # Required environment variables
│
├── src/
│   ├── __init__.py
│   ├── main.py                     # FastAPI app entrypoint
│   ├── config.py                   # Pydantic Settings (env vars)
│   │
│   ├── auth/
│   │   ├── __init__.py
│   │   └── dependencies.py         # API key validation (FastAPI dependency)
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes.py               # POST /research, GET /research/{id}
│   │   └── schemas.py              # Request/response Pydantic models
│   │
│   ├── research/
│   │   ├── __init__.py
│   │   ├── engine.py               # PydanticAI pipeline orchestrator
│   │   ├── prompts.py              # Prompt templates with format helpers
│   │   ├── search.py               # Tavily async wrapper
│   │   ├── scrape.py               # Firecrawl async wrapper
│   │   ├── compress.py             # OpenAI embeddings + numpy cosine similarity
│   │   └── tasks.py                # Background task runner + callback logic
│   │
│   └── cache/
│       ├── __init__.py
│       └── redis.py                # Redis client, get/set with TTL
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py                 # Fixtures (test client, mock Redis)
│   ├── test_auth.py                # API key validation tests
│   ├── test_routes.py              # Endpoint tests (stream + background)
│   ├── test_engine.py              # Research engine wrapper tests
│   ├── test_tasks.py               # Background task + callback tests
│   └── test_cache.py               # Redis cache tests
│
└── scripts/
    └── dev.sh                      # docker-compose up for local dev
```

## API

### Authentication

All endpoints require an `X-API-Key` header. The key is validated against the `API_KEY` environment variable.

```
X-API-Key: your-secret-key
```

### Endpoints

#### `POST /research`

Start a new research task.

**Request Body:**
```json
{
  "query": "What are the latest advances in quantum computing?",
  "mode": "stream",
  "depth": "standard",
  "callback_url": null
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `query` | string | yes | The research question |
| `mode` | enum | yes | `"stream"` or `"background"` |
| `depth` | enum | no | `"quick"`, `"standard"` (default), or `"deep"` — see below |
| `research_depth` | int | no | Override recursive depth (levels of sub-questions). Ignored if `depth` is set |
| `research_breadth` | int | no | Override parallel breadth (paths per level). Ignored if `depth` is set |
| `report_type` | string | no | GPT Researcher report type override (default: per tier). Ignored if `depth` is set |
| `callback_url` | string | no | Required when `mode=background`, optional for `mode=stream`. Must match `ALLOWED_CALLBACK_HOSTS` |

Use `depth` for presets, or set `research_depth`/`research_breadth`/`report_type` directly for full control. When `depth` is set, the individual fields are ignored.

**Depth tiers:**

| Tier | Report Type | Depth | Breadth | Use Case |
|---|---|---|---|---|
| `quick` | `research_report` | 1 | 2 | Fast factual lookups, simple questions |
| `standard` | `research_report` | 2 | 4 | General research, most queries |
| `deep` | `detailed_report` | 3 | 6 | Thorough multi-source analysis, complex topics |

**Custom example** — wide but shallow research:
```json
{
  "query": "Compare all major cloud providers' GPU pricing",
  "mode": "background",
  "research_depth": 1,
  "research_breadth": 8,
  "report_type": "research_report",
  "callback_url": "https://hooks.internal/research-done"
}
```

**Response — Streaming Mode (`mode=stream`):**

Returns an SSE stream (`text/event-stream`). The first event includes the `task_id` so the client can recover via `GET /research/{task_id}` if the stream drops:

```
event: started
data: {"task_id": "abc123"}

event: status
data: {"step": "planning", "message": "Generating research questions..."}

event: status
data: {"step": "researching", "message": "Searching: quantum computing breakthroughs 2025"}

event: finding
data: {"source": "https://...", "summary": "..."}

event: status
data: {"step": "writing", "message": "Generating final report..."}

event: result
data: {"task_id": "abc123", "report": "# Quantum Computing Advances\n...", "sources": [...]}

event: done
data: {}
```

If `callback_url` was provided, the service also POSTs the completion callback (same payload as background mode). This means research is never lost — if the client disconnects mid-stream, it still gets notified and can fetch the result from cache.

**Response — Background Mode (`mode=background`):**

Returns `202 Accepted`:
```json
{
  "task_id": "abc123",
  "status": "accepted",
  "message": "Research started. Results will be sent to callback URL."
}
```

When complete, the service sends a POST to the `callback_url`:
```json
{
  "task_id": "abc123",
  "status": "completed",
  "result_url": "/research/abc123"
}
```

#### `GET /research/{task_id}`

Retrieve a completed research result from cache.

**Response — `200 OK`:**
```json
{
  "task_id": "abc123",
  "status": "completed",
  "report": "# Quantum Computing Advances\n...",
  "sources": [
    {"url": "https://...", "title": "..."}
  ],
  "created_at": "2026-02-07T12:00:00Z",
  "expires_at": "2026-02-07T13:00:00Z"
}
```

**Response — `404 Not Found`:** Result expired or task ID unknown.

#### `GET /health`

Health check endpoint (no auth required).

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `API_KEY` | yes | Secret key for API authentication |
| `OPENAI_API_KEY` | varies | OpenAI API key (required if `LLM_PROVIDER=openai`, the default) |
| `ANTHROPIC_API_KEY` | varies | Anthropic API key (required if `LLM_PROVIDER=anthropic`) |
| `TAVILY_API_KEY` | yes | API key for [Tavily](https://tavily.com/) web search |
| `FIRECRAWL_API_KEY` | yes* | Firecrawl API key (*not needed if self-hosted without auth) |
| `FIRECRAWL_API_URL` | no | Self-hosted Firecrawl URL (default: Firecrawl cloud) |
| `REDIS_URL` | yes | Redis connection string (e.g. `redis://localhost:6379`) |
| `ALLOWED_CALLBACK_HOSTS` | yes | Comma-separated list of allowed callback URL hosts |
| `RESULT_TTL_SECONDS` | no | How long results are cached (default: `3600` = 1 hour) |
| `LLM_PROVIDER` | no | LLM provider for PydanticAI (default: `openai`). Supports any provider available in [PydanticAI](https://ai.pydantic.dev/): `openai`, `anthropic`, `google`, `ollama`, etc. |
| `FAST_LLM` | no | Model for fast operations (default: `gpt-4o-mini`) |
| `SMART_LLM` | no | Model for deep reasoning (default: `gpt-4o`) |
| `EMBEDDING_MODEL` | no | Model for context compression embeddings (default: `openai:text-embedding-3-small`) |
| `MAX_DEPTH_TIER` | no | Highest depth tier callers can use: `quick`, `standard`, or `deep` (default: `deep`) |
| `LOG_LEVEL` | no | Logging level (default: `INFO`) |

## Local Development

```bash
# Copy env file and fill in values
cp .env.example .env

# Start services (app + Redis + optional self-hosted Firecrawl)
docker-compose up

# Run tests
docker-compose exec app uv run pytest

# The API is available at http://localhost:8000
curl -H "X-API-Key: your-key" http://localhost:8000/health
```

## CI/CD

A GitHub Actions workflow builds and pushes the Docker image to GitHub Container Registry (GHCR) on every push to `main`.

**Image:** `ghcr.io/<owner>/research-service:latest`

Tags produced per build:
- `latest` (from `main`)
- `sha-<commit>` (immutable, for pinning in deployment)

## Running

### Directly

```bash
uv sync
uv run uvicorn src.main:app --host 0.0.0.0 --port 8000
```

### With Docker

```bash
docker build -t research-service .
docker run -p 8000:8000 --env-file .env research-service
```

### Suggested Production Setup: Docker behind ALB

For production on AWS, run the container on ECS Fargate behind an Application Load Balancer:

```
Client ──► ALB ──► ECS Fargate (Docker) ──► ElastiCache Redis
```

This works well because:
- **ALB supports long-lived HTTP connections** needed for SSE streaming (API Gateway has a 30-second timeout)
- **ECS Fargate has no execution time limit** — deep research can run for 15+ minutes (Lambda caps at 15 minutes)
- **ALB health checks** integrate natively with ECS service discovery

```bash
# Deploy / update
aws ecs update-service --cluster research --service research-service --force-new-deployment
```

Infrastructure (ECS, ALB, Redis, VPC) can be managed via Terraform in a separate repository, referencing the GHCR image.

But this is a plain HTTP server — it runs equally well behind nginx, on a VM, in Kubernetes, on Railway/Fly.io, or on bare metal. The only hard dependency is a reachable Redis instance.

## Design Decisions

### Callback URL Validation
Background mode callback URLs are validated against `ALLOWED_CALLBACK_HOSTS` to prevent SSRF. Only hostnames explicitly listed in this environment variable are allowed as callback targets.

### Redis for Result Storage
Results are stored in Redis with a 1-hour TTL rather than a database because:
- Results are ephemeral (only needed for pickup after background completion)
- No persistence requirements — results can be regenerated
- Redis TTL handles automatic cleanup
- Low latency for frequent polling if needed
