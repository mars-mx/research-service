"""Context compression — embeddings + cosine similarity."""

from __future__ import annotations

import logging

import numpy as np
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


async def compress_context(
    query: str,
    passages: list[str],
    openai_api_key: str,
    model: str = "text-embedding-3-small",
    top_k: int = 10,
) -> list[str]:
    """Rank *passages* by cosine similarity to *query*, return top-K.

    Uses the OpenAI embeddings API directly for minimal overhead.
    Returns at most *top_k* passages, or all passages if fewer exist.
    """
    if not passages:
        return []
    if len(passages) <= top_k:
        return passages

    client = AsyncOpenAI(api_key=openai_api_key)
    try:
        all_texts = [query] + passages
        response = await client.embeddings.create(model=model, input=all_texts)
        embeddings = np.array([e.embedding for e in response.data])

        query_vec = embeddings[0]
        doc_vecs = embeddings[1:]

        # Cosine similarity
        query_norm = query_vec / np.linalg.norm(query_vec)
        doc_norms = doc_vecs / np.linalg.norm(doc_vecs, axis=1, keepdims=True)
        similarities = doc_norms @ query_norm

        top_indices = np.argsort(similarities)[::-1][:top_k]
        return [passages[i] for i in top_indices]
    except Exception:
        logger.warning("context compression failed, returning all passages", exc_info=True)
        return passages[:top_k]
