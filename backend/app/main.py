"""FastAPI backend: /health, /models, /search (fulltext | vector | hybrid)."""
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from pymongo.errors import PyMongoError

from . import search as search_mod
from .config import get_settings
from .db import ping

app = FastAPI(title="Board Games Search", version="1.0.0")

# Frontend is a different origin; open CORS for the demo (tighten in prod).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=400)

SearchType = Literal["fulltext", "vector", "hybrid"]


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


@app.get("/search")
def do_search(
    q: str = Query(..., min_length=1, description="Search query text."),
    type: SearchType = Query("fulltext", description="Search mode."),
    model: str | None = Query(
        None, description="Embedding model / vector index for vector & hybrid."
    ),
    limit: int = Query(5, ge=1, le=100),
):
    q = " ".join(q.split())
    if not q:
        raise HTTPException(status_code=400, detail="q must not be empty")

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
    except PyMongoError as exc:
        raise HTTPException(status_code=502, detail=f"search failed: {exc}")

    return {
        "query": q,
        "type": type,
        "model": model if type in ("vector", "hybrid") else None,
        "count": len(results),
        "results": results,
    }
