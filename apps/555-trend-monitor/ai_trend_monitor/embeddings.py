"""Sentence-transformer embeddings for semantic similarity."""

import logging
import time

import numpy as np
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

_model: SentenceTransformer | None = None


def get_model() -> SentenceTransformer:
    """Lazy-load and cache the sentence-transformer model."""
    global _model
    if _model is None:
        t0 = time.monotonic()
        _model = SentenceTransformer("all-MiniLM-L6-v2")
        elapsed = time.monotonic() - t0
        logger.info("Loaded all-MiniLM-L6-v2 in %.2fs", elapsed)
    return _model


def compute_similarity(text_a: str, text_b: str) -> float:
    """Return cosine similarity between two texts."""
    model = get_model()
    embeddings = model.encode([text_a, text_b], normalize_embeddings=True)
    return float(np.dot(embeddings[0], embeddings[1]))


def find_matching_topics(
    new_titles: list[str],
    existing_titles: list[str],
    threshold: float = 0.75,
) -> dict[int, int]:
    """Find semantic matches between new titles and existing titles.

    Returns:
        Dict mapping new_idx -> existing_idx for matches above threshold.
    """
    if not new_titles or not existing_titles:
        return {}

    model = get_model()
    logger.info(
        "Encoding %d new titles against %d existing titles",
        len(new_titles),
        len(existing_titles),
    )

    new_emb = model.encode(new_titles, normalize_embeddings=True)
    existing_emb = model.encode(existing_titles, normalize_embeddings=True)

    # Similarity matrix: (len(new), len(existing))
    sim_matrix = np.dot(new_emb, existing_emb.T)

    matches: dict[int, int] = {}
    for i in range(len(new_titles)):
        best_idx = int(np.argmax(sim_matrix[i]))
        best_score = float(sim_matrix[i, best_idx])
        if best_score >= threshold:
            matches[i] = best_idx

    return matches
