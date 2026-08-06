#!/usr/bin/env python3
"""Idempotent seed loader. Reads DATA_FILE (falls back to SAMPLE_FILE), builds a
search_text field (name + description) for autoEmbed, inserts into an empty
collection, then creates the full-text + per-model autoEmbed vector indexes and
waits for READY. Safe to re-run; vector index creation is best-effort (needs a
mongot with the OPENAI_COMPATIBLE provider)."""
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

DATA_FILE = os.environ.get("DATA_FILE", "/work/data/boardgames.ndjson")
SAMPLE_FILE = os.environ.get("SAMPLE_FILE", "/work/data/sample_boardgames.ndjson")
# full = data/boardgames.ndjson (fallback sample); sample = the 20-game sample.
DATASET = os.environ.get("DATASET", "sample").lower()
SEED_DATA = os.environ.get("SEED_DATA", "true").lower() == "true"
WAIT_INDEX_READY = os.environ.get("WAIT_INDEX_READY", "true").lower() == "true"

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
    if DATASET == "sample":
        path = SAMPLE_FILE
    elif os.path.exists(DATA_FILE):
        path = DATA_FILE
    else:
        log(f"DATASET=full but {DATA_FILE} missing; falling back to {SAMPLE_FILE}")
        path = SAMPLE_FILE
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
    # Batch inserts to bound memory on the 20k dataset.
    batch = 1000
    for i in range(0, len(docs), batch):
        coll.insert_many(docs[i : i + batch], ordered=False)
    log(f"inserted {len(docs)} docs into {coll.full_name}")


def existing_search_indexes(coll):
    try:
        return {idx["name"]: idx for idx in coll.list_search_indexes()}
    except OperationFailure as exc:
        log(f"WARN could not list search indexes: {exc}")
        return {}


def ensure_text_index(coll, existing):
    if TEXT_INDEX in existing:
        log(f"text index '{TEXT_INDEX}' already exists; skipping")
        return
    # lucene.english stems
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
    create_search_index_retry(
        coll,
        {"name": TEXT_INDEX, "definition": definition},
        f"full-text index '{TEXT_INDEX}' on {', '.join(TEXT_FIELDS)}",
    )


def ensure_vector_index(coll, existing, model, index_name):
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
            log(f"vector index '{index_name}' (model {model}) already exists ({status}); skipping")
            return
    definition = {
        "fields": [
            {
                "type": "autoEmbed",
                "path": "search_text",
                "model": model,
                "modality": "text",
            }
        ]
    }
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


def seed_once():
    client = connect()
    coll = client[MONGO_DB][MONGO_COLLECTION]

    # No-op if data + all indexes already present (fresh volume re-seeds).
    has_data = coll.estimated_document_count() > 0
    existing = existing_search_indexes(coll)
    indexes_ok = all(
        name in existing and existing[name].get("status") != "FAILED"
        for name in expected_indexes()
    )
    if has_data and indexes_ok:
        log("already seeded (data + indexes present); nothing to do")
        wait_ready(coll, expected_indexes())
        return

    # Parse the dataset only when inserting.
    docs = load_docs() if not has_data else []
    insert_if_empty(coll, docs)
    # btree index on rank for fast sort-by-rank.
    coll.create_index([("rank", ASCENDING)], name="rank_idx")

    ensure_text_index(coll, existing)
    for model, index_name in VECTOR_INDEXES.items():
        ensure_vector_index(coll, existing, model, index_name)

    wait_ready(coll, expected_indexes())
    log("done")


def main(attempts=10, delay=3):
    if not SEED_DATA:
        log("SEED_DATA=false; skipping seeding")
        return
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
