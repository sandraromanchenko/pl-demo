#!/usr/bin/env python3
"""Idempotent seed loader, in two phases (SEED_PHASE):

  data     documents + plain mongod indexes (rank, classic $text). Needs only
           mongod, so it runs as soon as the database starts.
  indexes  mongot full-text + per-model autoEmbed vector indexes, waiting for
           READY. Needs mongot and a reachable embedding backend.
  all      both (default).

Reads DATA_FILE (default: sample_boardgames.ndjson) and builds a search_text field
(name + description) for autoEmbed. Safe to re-run; vector index creation is
best-effort (needs a mongot with the OPENAI_COMPATIBLE provider)."""
import json
import os
import sys
import time

from pymongo import MongoClient, ASCENDING
from pymongo.errors import (
    AutoReconnect,
    NotPrimaryError,
    OperationFailure,
    PyMongoError,
)

# Retryable replset errors (shutdown / step-down / not-primary).
TRANSIENT_CODES = {11600, 11602, 189, 91, 10107, 13435, 13436}

# mongod without a mongotHost setting: search index commands do not exist. Its
# own error is a wall of Atlas advice, so say what to do here instead.
SEARCH_NOT_ENABLED = 31082
SEARCH_NOT_ENABLED_HELP = (
    "[seed] search is not enabled on this mongod (no mongotHost setting), so "
    "search indexes cannot be created.\n"
    "[seed] Start Percona Search and restart mongod with config/mongod.conf "
    "first (demo/live.sh, or make demo-add-search)."
)


def _search_not_enabled(exc: PyMongoError) -> bool:
    return getattr(exc, "code", None) == SEARCH_NOT_ENABLED


def _is_transient(exc: PyMongoError) -> bool:
    if isinstance(exc, (AutoReconnect, NotPrimaryError)):
        return True
    return getattr(exc, "code", None) in TRANSIENT_CODES

MONGO_URI = os.environ.get(
    "MONGO_URI",
    "mongodb://root:root@mongod:27017/?authSource=admin&directConnection=true",
)
MONGO_DB = os.environ.get("MONGO_DB", "boardgames")
MONGO_COLLECTION = os.environ.get("MONGO_COLLECTION", "games")
TEXT_INDEX = os.environ.get("TEXT_INDEX", "text_index")

# Model -> vector index. bge-small=TEI, others=Ollama.
MODEL_INDEXES = {
    "bge-small": "vec_bge_small",
    "nomic-embed-text": "vec_nomic",
    "bge-m3": "vec_bge_m3",
}
# Models to enable (must match what Ollama pulls, else index FAILED).
EMBED_MODELS = [
    m.strip()
    for m in os.environ.get("EMBED_MODELS", "bge-small").split(",")
    if m.strip() in MODEL_INDEXES
]
VECTOR_INDEXES = {m: MODEL_INDEXES[m] for m in EMBED_MODELS}

DATA_FILE = os.environ.get("DATA_FILE", "/work/data/sample_boardgames.ndjson")
SEED_DATA = os.environ.get("SEED_DATA", "true").lower() == "true"
WAIT_INDEX_READY = os.environ.get("WAIT_INDEX_READY", "true").lower() == "true"
# data = documents only (mongod), indexes = search indexes only (mongot), all = both.
SEED_PHASES = ("all", "data", "indexes")
SEED_PHASE = os.environ.get("SEED_PHASE", "all").lower()

# Full-text index fields (explicit, not dynamic, for focused scoring).
TEXT_FIELDS = ["name", "description", "categories", "mechanics"]

# mongot's index-management service can be unreachable for a few seconds after
# mongod is writable; index creation fails transiently until it connects.
SEARCH_INDEX_RETRIES = 15
SEARCH_INDEX_DELAY = 4


def log(*args):
    print("[seed]", *args, flush=True)


def _index_mgmt_unavailable(exc: OperationFailure) -> bool:
    return "search index management" in str(exc).lower() or getattr(exc, "code", None) == 125


def create_search_index_retry(coll, spec, desc) -> bool:
    """Create a search index, retrying while mongot's mgmt service is unreachable."""
    for attempt in range(1, SEARCH_INDEX_RETRIES + 1):
        try:
            coll.create_search_index(spec)
            log(f"created {desc}")
            return True
        except OperationFailure as exc:
            if _search_not_enabled(exc):
                raise SystemExit(SEARCH_NOT_ENABLED_HELP)
            if _index_mgmt_unavailable(exc) and attempt < SEARCH_INDEX_RETRIES:
                log(f"WARN {desc}: mongot not ready ({attempt}/{SEARCH_INDEX_RETRIES}): {exc}")
                time.sleep(SEARCH_INDEX_DELAY)
                continue
            log(f"WARN could not create {desc}: {exc}")
            return False
    return False


def build_search_text(doc):
    """autoEmbed path: name + description."""
    parts = [str(doc.get("name", "")), str(doc.get("description", ""))]
    return "\n".join(p for p in parts if p).strip()


def load_docs():
    path = DATA_FILE
    log(f"loading dataset from {path}")
    docs = []
    with open(path, "r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                doc = json.loads(line)
            except json.JSONDecodeError as exc:
                log(f"WARN skipping malformed line {line_no}: {exc}")
                continue
            doc["search_text"] = build_search_text(doc)
            docs.append(doc)
    log(f"parsed {len(docs)} board-game documents")
    return docs


def connect(retries=60, delay=2):
    last = None
    for attempt in range(1, retries + 1):
        try:
            client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
            # Wait for a writable primary (init runs a temp instance that's killed).
            if not client.admin.command("hello").get("isWritablePrimary"):
                raise AutoReconnect("mongod not yet a writable primary")
            log("connected to mongod (writable primary)")
            return client
        except PyMongoError as exc:
            last = exc
            log(f"waiting for writable mongod ({attempt}/{retries}): {exc}")
            time.sleep(delay)
    raise SystemExit(f"could not connect to mongod: {last}")


def insert_if_empty(coll, docs):
    existing = coll.estimated_document_count()
    if existing > 0:
        log(f"{coll.full_name} already has data ({existing} docs); skipping insert")
        return
    if not docs:
        log("no documents to insert")
        return
    # Batch inserts to bound memory.
    batch = 1000
    for i in range(0, len(docs), batch):
        coll.insert_many(docs[i : i + batch], ordered=False)
    log(f"inserted {len(docs)} docs into {coll.full_name}")


def existing_search_indexes(coll):
    try:
        return {idx["name"]: idx for idx in coll.list_search_indexes()}
    except OperationFailure as exc:
        if _search_not_enabled(exc):
            raise SystemExit(SEARCH_NOT_ENABLED_HELP)
        log(f"WARN could not list search indexes: {exc}")
        return {}


def ensure_classic_text_index(coll):
    """MongoDB's built-in text index ($text). One per collection."""
    name = "text_idx"
    existing = {idx["name"] for idx in coll.list_indexes()}
    if name in existing:
        log(f"classic text index '{name}' already exists; skipping")
        return
    coll.create_index(
        [(field, "text") for field in TEXT_FIELDS],
        name=name,
        default_language="english",
        weights={"name": 10, "description": 5, "categories": 3, "mechanics": 3},
    )
    log(f"created classic MongoDB text index '{name}' on {', '.join(TEXT_FIELDS)}")


def ensure_text_index(coll, existing):
    # lucene.english stems, so $search matches word variants (and fuzzy typos).
    definition = {
        "analyzer": "lucene.english",
        "searchAnalyzer": "lucene.english",
        "mappings": {
            "dynamic": False,
            "fields": {
                "name": {"type": "string"},
                "description": {"type": "string"},
                "categories": {"type": "string"},
                "mechanics": {"type": "string"},
            },
        },
    }
    if TEXT_INDEX in existing:
        log(f"text index '{TEXT_INDEX}' already exists; skipping")
        return
    create_search_index_retry(
        coll,
        {"name": TEXT_INDEX, "definition": definition},
        f"full-text index '{TEXT_INDEX}' on {', '.join(TEXT_FIELDS)}",
    )


def ensure_vector_index(coll, existing, model, index_name):
    definition = {
        "fields": [
            {
                "type": "autoEmbed",
                "path": "search_text",
                "model": model,
                "modality": "text",
            },
        ]
    }
    if index_name in existing:
        status = existing[index_name].get("status")
        # FAILED usually means the model wasn't reachable at first seed; drop and
        # rebuild (re-running seed is the recovery path).
        if status == "FAILED":
            log(f"vector index '{index_name}' (model {model}) is FAILED; dropping to rebuild")
            try:
                coll.drop_search_index(index_name)
                time.sleep(3)  # let mongot process the drop
            except OperationFailure as exc:
                log(f"WARN could not drop failed index '{index_name}': {exc}")
                return
        else:
            log(
                f"vector index '{index_name}' (model {model}) already exists ({status}); skipping"
            )
            return
    create_search_index_retry(
        coll,
        {"name": index_name, "type": "vectorSearch", "definition": definition},
        f"autoEmbed vector index '{index_name}' (model {model})",
    )


def wait_ready(coll, names, timeout=600):
    if not WAIT_INDEX_READY:
        return
    log(f"waiting for indexes to become READY: {', '.join(names)}")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            status = {i["name"]: i.get("status") for i in coll.list_search_indexes()}
        except OperationFailure as exc:
            if _search_not_enabled(exc):
                raise SystemExit(SEARCH_NOT_ENABLED_HELP)
            log(f"WARN could not poll index status: {exc}")
            return
        # Every expected index must be present AND READY (a missing one means
        # creation failed, e.g. mongot was unreachable — don't declare success).
        wanted = {n: status.get(n) for n in names}
        if all(s == "READY" for s in wanted.values()):
            log(f"indexes READY: {wanted}")
            return
        log(f"index status: {wanted}")
        time.sleep(5)
    log("WARN timed out waiting for indexes to become READY")


def expected_indexes():
    return [TEXT_INDEX, *VECTOR_INDEXES.values()]


def seed_documents(coll):
    """Phase `data`: what a plain MongoDB deployment would already hold."""
    # Parse the dataset only when inserting.
    docs = load_docs() if coll.estimated_document_count() == 0 else []
    insert_if_empty(coll, docs)
    # btree index on rank for fast sort-by-rank.
    coll.create_index([("rank", ASCENDING)], name="rank_idx")
    ensure_classic_text_index(coll)


def seed_search_indexes(coll):
    """Phase `indexes`: everything that needs mongot (full-text + autoEmbed)."""
    if coll.estimated_document_count() == 0:
        log("WARN collection is empty; search indexes will have nothing to embed")
    existing = existing_search_indexes(coll)
    ensure_text_index(coll, existing)
    for model, index_name in VECTOR_INDEXES.items():
        ensure_vector_index(coll, existing, model, index_name)
    wait_ready(coll, expected_indexes())


def seed_once():
    client = connect()
    coll = client[MONGO_DB][MONGO_COLLECTION]

    if SEED_PHASE in ("all", "data"):
        seed_documents(coll)
    if SEED_PHASE in ("all", "indexes"):
        seed_search_indexes(coll)
    log(f"done (phase: {SEED_PHASE})")


def main(attempts=10, delay=3):
    if SEED_PHASE not in SEED_PHASES:
        raise SystemExit(
            f"SEED_PHASE='{SEED_PHASE}' invalid; use one of {', '.join(SEED_PHASES)}"
        )
    if not SEED_DATA:
        log("SEED_DATA=false; skipping seeding")
        return
    log(f"phase: {SEED_PHASE}")
    # Retry the idempotent seed on transient replset errors.
    for attempt in range(1, attempts + 1):
        try:
            seed_once()
            return
        except PyMongoError as exc:
            if _is_transient(exc) and attempt < attempts:
                log(f"transient error, retrying seed ({attempt}/{attempts}): {exc}")
                time.sleep(delay)
                continue
            raise


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
