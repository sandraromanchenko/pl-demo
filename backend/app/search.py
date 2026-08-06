"""Search modes: full-text ($search), vector ($vectorSearch auto-embed) and
hybrid (RRF of the two). Results share one shape so the UI renders one card."""
from typing import Any

from .config import get_settings
from .db import get_collection

# Fields returned to the UI (search_text is an index-only derived field).
PROJECT_FIELDS = [
    "name",
    "yearPublished",
    "description",
    "minPlayers",
    "maxPlayers",
    "playingTime",
    "minAge",
    "categories",
    "mechanics",
    "designers",
    "averageRating",
    "rank",
    "complexity",
    "thumbnail",
]

# $project stage: projected fields + _id + score.
PROJECTION = {f: 1 for f in PROJECT_FIELDS} | {"_id": 1, "score": 1}

# RRF constant (Cormack et al.); larger K flattens top-rank contribution.
RRF_K = 60


def _clean(doc: dict[str, Any]) -> dict[str, Any]:
    out = {k: doc.get(k) for k in PROJECT_FIELDS}
    out["_id"] = doc.get("_id")
    out["score"] = doc.get("score")
    return out


def _run(pipeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_clean(doc) for doc in get_collection().aggregate(pipeline)]


def fulltext_search(q: str, limit: int) -> list[dict[str, Any]]:
    settings = get_settings()
    return _run([
        {"$search": {"index": settings.text_index, "text": {"query": q, "path": settings.text_fields}}},
        {"$limit": limit},
        {"$addFields": {"score": {"$meta": "searchScore"}}},
        {"$project": PROJECTION},
    ])


def vector_search(q: str, model: str, limit: int) -> list[dict[str, Any]]:
    settings = get_settings()
    index_name = settings.vector_indexes.get(model)
    if not index_name:
        raise ValueError(f"unknown model '{model}'")
    # Auto-embed: pass `query` text (not queryVector); numCandidates oversamples for recall.
    return _run([
        {
            "$vectorSearch": {
                "index": index_name,
                "path": "search_text",
                "query": q,
                "numCandidates": max(limit * 10, 100),
                "limit": limit,
            }
        },
        {"$addFields": {"score": {"$meta": "vectorSearchScore"}}},
        {"$project": PROJECTION},
    ])


def _rrf_merge(
    rankings: list[list[dict[str, Any]]], limit: int, k: int = RRF_K
) -> list[dict[str, Any]]:
    """Reciprocal Rank Fusion: score = sum of 1/(k + rank) across lists."""
    fused: dict[Any, dict[str, Any]] = {}
    for ranking in rankings:
        for rank, doc in enumerate(ranking, start=1):
            entry = fused.setdefault(doc.get("_id"), {"doc": doc, "score": 0.0})
            entry["score"] += 1.0 / (k + rank)
    merged = []
    for entry in fused.values():
        doc = dict(entry["doc"])
        doc["score"] = entry["score"]
        merged.append(doc)
    merged.sort(key=lambda d: d["score"], reverse=True)
    return merged[:limit]


def hybrid_search(q: str, model: str, limit: int) -> list[dict[str, Any]]:
    # Oversample each leg so fusion has more candidates. ($rankFusion is a future
    # native alternative; RRF here keeps the demo portable.)
    leg_limit = max(limit * 2, limit)
    fulltext = fulltext_search(q, leg_limit)
    vector = vector_search(q, model, leg_limit)
    return _rrf_merge([fulltext, vector], limit)


def search(q: str, search_type: str, model: str, limit: int) -> list[dict[str, Any]]:
    if search_type == "fulltext":
        return fulltext_search(q, limit)
    if search_type == "vector":
        return vector_search(q, model, limit)
    if search_type == "hybrid":
        return hybrid_search(q, model, limit)
    raise ValueError(f"unknown search type '{search_type}'")
