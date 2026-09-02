"""FastAPI backend: /health, /models, /games, /search (text | fulltext | vector
| hybrid)."""
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pymongo.errors import OperationFailure, PyMongoError

from . import search as search_mod
from .config import get_settings
from .db import ping

app = FastAPI(title="Board Games Search", version="1.0.0")

# Frontend is a different origin; open CORS for the demo (tighten in prod)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

SearchType = Literal["text", "fulltext", "vector", "hybrid"]

TYPE_LABELS = {
    "text": "Text search",
    "fulltext": "Full-text search",
    "vector": "Vector search",
    "hybrid": "Hybrid search",
}

# mongod raises this when it was started without mongotHost: $search and
# $vectorSearch do not exist until Percona Search is wired in.
SEARCH_NOT_ENABLED = 31082
INDEX_NOT_FOUND = 27


def _unavailable_detail(type: str, model: str, exc: OperationFailure) -> str:
    """Turn a Mongo/mongot failure into something a human can act on."""
    label = TYPE_LABELS.get(type, "Search")
    settings = get_settings()

    if exc.code == SEARCH_NOT_ENABLED:
        return (
            f"{label} is not enabled on this deployment. It needs Percona Search "
            "(mongot) running and mongod started with the mongotHost setting. "
            "Classic Text search works without it."
        )

    if exc.code == INDEX_NOT_FOUND:
        if type == "text":
            return (
                f"{label} has no text index yet. Load the data (which creates it) "
                "and try again."
            )
        index = (
            settings.vector_indexes.get(model, "the vector index")
            if type in ("vector", "hybrid")
            else settings.text_index
        )
        return (
            f"{label} has no index yet ({index}). Create the search indexes and "
            "wait for them to report READY."
        )

    return f"{label} failed: {exc}"


@app.get("/health")
def health():
    try:
        ping()
        return {"status": "ok", "mongo": "up"}
    except PyMongoError as exc:
        raise HTTPException(status_code=503, detail=f"mongo unavailable: {exc}")


@app.get("/models")
def models():
    """Models/indexes for the UI dropdown (one autoEmbed index per model)."""
    settings = get_settings()
    return {
        "default": settings.default_model,
        "textIndex": settings.text_index,
        "models": [
            {"model": model, "index": index}
            for model, index in settings.vector_indexes.items()
        ],
    }


@app.get("/games")
def list_games(limit: int = Query(100, ge=1, le=500)):
    """Whole collection for the UI's landing state, so the audience sees the
    corpus and its size before any query narrows it."""
    try:
        results, total = search_mod.browse(limit)
    except PyMongoError as exc:
        raise HTTPException(status_code=502, detail=f"listing games failed: {exc}")

    return {"total": total, "count": len(results), "results": results}


@app.get("/search")
def do_search(
    q: str = Query(..., min_length=1, description="Search query text."),
    type: SearchType = Query("fulltext", description="Search mode: text ($text), fulltext ($search), vector, hybrid."),
    model: str | None = Query(None, description="Embedding model / vector index for vector & hybrid."),
    limit: int = Query(5, ge=1, le=100),
):
    settings = get_settings()
    model = model or settings.default_model

    if type in ("vector", "hybrid") and model not in settings.vector_indexes:
        raise HTTPException(
            status_code=400,
            detail=f"unknown model '{model}'; available: {list(settings.vector_indexes)}",
        )

    try:
        results = search_mod.search(q, type, model, limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except OperationFailure as exc:
        # Search missing or not indexed yet is a state, not a crash: say so.
        raise HTTPException(
            status_code=503, detail=_unavailable_detail(type, model, exc)
        )
    except PyMongoError as exc:
        raise HTTPException(status_code=502, detail=f"search failed: {exc}")

    return {
        "query": q,
        "type": type,
        "model": model if type in ("vector", "hybrid") else None,
        "count": len(results),
        "results": results,
    }
