"""Context compression — embeddings + cosine similarity."""

from __future__ import annotations

import logging

import numpy as np
from google import genai
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

# Type for embedding usage statistics returned alongside compressed passages.
EmbeddingUsage = dict[str, int]


def _parse_embedding_model(model: str) -> tuple[str, str]:
    """Parse a 'provider:model_name' string into (provider, model_name).

    If no provider prefix is present, defaults to 'openai'.
    """
    if ":" in model:
        provider, model_name = model.split(":", 1)
        return provider, model_name
    return "openai", model


async def _get_embeddings_openai(
    texts: list[str],
    model_name: str,
    api_key: str,
) -> tuple[list[list[float]], EmbeddingUsage]:
    """Get embeddings via the OpenAI API.

    Returns (embeddings_list, usage_dict).
    """
    client = AsyncOpenAI(api_key=api_key)
    response = await client.embeddings.create(model=model_name, input=texts)
    embeddings = [e.embedding for e in response.data]
    usage: EmbeddingUsage = {
        "input_tokens": response.usage.total_tokens,
        "requests": 1,
    }
    return embeddings, usage


async def _get_embeddings_google(
    texts: list[str],
    model_name: str,
    api_key: str,
) -> tuple[list[list[float]], EmbeddingUsage]:
    """Get embeddings via the Google Gemini API.

    Returns (embeddings_list, usage_dict).
    """
    client = genai.Client(api_key=api_key)
    response = await client.aio.models.embed_content(
        model=model_name,
        contents=texts,
    )
    embeddings = [e.values for e in response.embeddings]
    usage: EmbeddingUsage = {
        "input_tokens": response.metadata.billable_character_count or 0,
        "requests": 1,
    }
    return embeddings, usage


async def compress_context(
    query: str,
    passages: list[str],
    api_key: str,
    model: str = "openai:text-embedding-3-small",
    top_k: int = 10,
) -> tuple[list[str], EmbeddingUsage]:
    """Rank *passages* by cosine similarity to *query*, return top-K.

    Uses an embeddings API determined by the *model* prefix (e.g. ``openai:``,
    ``google:``).  Returns a tuple of (selected_passages, usage_dict) where
    usage_dict contains ``input_tokens`` and ``requests`` counts.
    """
    empty_usage: EmbeddingUsage = {"input_tokens": 0, "requests": 0}

    if not passages:
        return [], empty_usage
    if len(passages) <= top_k:
        return passages, empty_usage

    provider, model_name = _parse_embedding_model(model)

    try:
        all_texts = [query] + passages

        if provider == "openai":
            raw_embeddings, usage = await _get_embeddings_openai(all_texts, model_name, api_key)
        elif provider == "google":
            raw_embeddings, usage = await _get_embeddings_google(all_texts, model_name, api_key)
        else:
            raise ValueError(f"Unsupported embedding provider: {provider!r}")

        embeddings = np.array(raw_embeddings)

        query_vec = embeddings[0]
        doc_vecs = embeddings[1:]

        # Cosine similarity
        query_norm = query_vec / np.linalg.norm(query_vec)
        doc_norms = doc_vecs / np.linalg.norm(doc_vecs, axis=1, keepdims=True)
        similarities = doc_norms @ query_norm

        top_indices = np.argsort(similarities)[::-1][:top_k]
        return [passages[i] for i in top_indices], usage
    except Exception:
        logger.warning("context compression failed, returning all passages", exc_info=True)
        return passages, empty_usage
