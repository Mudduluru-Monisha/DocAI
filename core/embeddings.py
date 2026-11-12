"""Local sentence-transformer embeddings (free, no API quota)."""
from __future__ import annotations

from functools import lru_cache

from . import config


@lru_cache(maxsize=1)
def _model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(config.EMBED_MODEL)


def embed(texts: list[str], batch_size: int = 64) -> list[list[float]]:
    vecs = _model().encode(texts, batch_size=batch_size, normalize_embeddings=True, show_progress_bar=False)
    return vecs.tolist()
