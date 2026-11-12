"""Vector search over the catalog on either engine: mongot (Lucene HNSW) or OpenSearch (Faiss HNSW).

Both engines hold the same passages and the same vectors (seeded by osmc/seed.py, loaded into
OpenSearch by `make os-load`). The question is embedded here, by Ollama, with the model the
application uses *right now*: `make swap-model` writes its name to a file on the shared
golden volume, and every question after that is embedded with it. The catalog is not touched.

Results are shaped like the rest of the API (name, description, ...) and enriched with the
game's metadata from the `games` collection, so one card renders everything.
"""
import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

from . import metrics
from .complexity import band_for
from .db import get_client
from .config import get_settings

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434").rstrip("/")
OPENSEARCH_URL = os.environ.get("OPENSEARCH_URL", "http://opensearch:9200").rstrip("/")
OS_INDEX = os.environ.get("OS_INDEX", "catalog_os")
EF_SEARCH = int(os.environ.get("EF_SEARCH", "100"))
CATALOG_COLLECTION = os.environ.get("OSMC_COLLECTION", "catalog")
GOLDEN_PATH = os.environ.get("GOLDEN_PATH", "/golden/golden.json")
QUERY_MODEL_FILE = os.environ.get("QUERY_MODEL_FILE", "/golden/query_model")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "bge-small")

CARD_FIELDS = [
    "name", "yearPublished", "minPlayers", "maxPlayers", "playingTime", "minAge",
    "categories", "mechanics", "designers", "averageRating", "rank", "complexity", "thumbnail",
]

_golden = {"mtime": None, "meta": None}


class EngineUnavailable(Exception):
    """The engine or the embedding model cannot be reached. Shown on the page, not a crash."""


def catalog_ready() -> bool:
    """True when the OSMC catalog was seeded (the golden file is written by osmc-seed)."""
    return os.path.exists(GOLDEN_PATH)


def golden_meta() -> dict[str, Any]:
    """Index name and numCandidates for mongot. Re-read only when the file changes."""
    try:
        mtime = os.path.getmtime(GOLDEN_PATH)
    except OSError:
        raise EngineUnavailable("The catalog has not been seeded yet (make osmc-seed).")
    if _golden["mtime"] != mtime:
        with open(GOLDEN_PATH) as fh:
            data = json.load(fh)
        _golden["meta"] = {
            "index": data["index"],
            "numCandidates": int(data.get("numCandidates", data["k"])),
        }
        _golden["mtime"] = mtime
    return _golden["meta"]


def query_model() -> str:
    try:
        with open(QUERY_MODEL_FILE) as fh:
            name = fh.read().strip()
            if name:
                return name
    except OSError:
        pass
    return EMBED_MODEL


def embed(text: str) -> list[float]:
    req = urllib.request.Request(
        OLLAMA_URL + "/api/embed",
        data=json.dumps({"model": query_model(), "input": [text]}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            vector = json.loads(resp.read())["embeddings"][0]
        metrics.embedding_done(True)
        return vector
    except (urllib.error.URLError, OSError) as exc:
        metrics.embedding_done(False)
        raise EngineUnavailable(f"The embedding model is not reachable: {exc}")


def _enrich(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Cards: the passage text plus the game's own details, when the games collection has it."""
    settings = get_settings()
    names = sorted({h["title"] for h in hits if h.get("title")})
    games = {}
    if names:
        coll = get_client()[settings.mongo_db][settings.mongo_collection]
        for g in coll.find({"name": {"$in": names}}, {f: 1 for f in CARD_FIELDS}):
            games[g["name"]] = g
    out = []
    for h in hits:
        g = games.get(h["title"], {})
        card = {f: g.get(f) for f in CARD_FIELDS}
        card["name"] = h["title"]
        card["description"] = h["text"]
        card["_id"] = h["_id"]
        card["score"] = None  # the two engines score differently; a number would mislead
        card["complexityBand"] = band_for(g.get("complexity"))
        out.append(card)
    return out


def mongot_search(vector: list[float], limit: int) -> list[dict[str, Any]]:
    meta = golden_meta()
    coll = get_client()[get_settings().mongo_db][CATALOG_COLLECTION]
    rows = coll.aggregate([
        {"$vectorSearch": {
            "index": meta["index"],
            "path": "embedding",
            "queryVector": vector,
            "numCandidates": max(meta["numCandidates"], limit),
            "limit": limit,
        }},
        {"$project": {"title": 1, "text": 1}},
    ])
    return [{"_id": str(r["_id"]), "title": r.get("title", ""), "text": r.get("text", "")} for r in rows]


def opensearch_search(vector: list[float], limit: int) -> list[dict[str, Any]]:
    body = {
        "size": limit,
        "_source": ["title", "text"],
        "query": {"knn": {"embedding": {
            "vector": vector,
            "k": limit,
            "method_parameters": {"ef_search": EF_SEARCH},
        }}},
    }
    req = urllib.request.Request(
        f"{OPENSEARCH_URL}/{OS_INDEX}/_search",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            res = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raise EngineUnavailable(f"OpenSearch answered {exc.code}: {exc.read()[:200].decode(errors='replace')}")
    except (urllib.error.URLError, OSError) as exc:
        raise EngineUnavailable(f"OpenSearch is not reachable: {exc}")
    return [
        {"_id": h["_id"], "title": h["_source"].get("title", ""), "text": h["_source"].get("text", "")}
        for h in res["hits"]["hits"]
    ]


def search(engine: str, q: str, limit: int) -> tuple[list[dict[str, Any]], float]:
    """Vector search on one engine. Returns cards and the engine's own latency in ms."""
    vector = embed(q)
    started = time.perf_counter()
    if engine == "opensearch":
        hits = opensearch_search(vector, limit)
    else:
        hits = mongot_search(vector, limit)
    ms = (time.perf_counter() - started) * 1000
    return _enrich(hits), round(ms, 1)
