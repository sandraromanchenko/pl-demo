#!/usr/bin/env python3
"""Build the OSMC corpus, vector index, and golden recall set.

Stable documents are real board-game passages, embedded with Ollama, so the
RAG app has something true to say. Churn documents are random unit vectors in
the same index: they give HNSW a large graph to damage, and they are rejected
if brute force would put them in any query's top-k. Ground truth is therefore
still valid after those documents are deleted.

The index is created only after every document is inserted, so the first
graph is a bulk build. The demo failure (make degrade-both) is what breaks it afterwards.
"""
import json
import os
import re
import time
import urllib.error
import urllib.request

import numpy as np
from pymongo import MongoClient
from pymongo.errors import AutoReconnect, OperationFailure, PyMongoError

MONGO_URI = os.environ.get(
    "MONGO_URI",
    "mongodb://root:root@mongod:27017/?authSource=admin&directConnection=true",
)
MONGO_DB = os.environ.get("MONGO_DB", "boardgames")
MONGO_COLLECTION = os.environ.get("MONGO_COLLECTION", "catalog")
INDEX_NAME = os.environ.get("VECTOR_INDEX", "vec_osmc")
DATA_FILE = os.environ.get("DATA_FILE", "/work/data/easy_boardgames.ndjson")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434").rstrip("/")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "bge-small")
GOLDEN_PATH = os.environ.get("GOLDEN_PATH", "/golden/golden.json")
INDEX_PATH = os.environ.get("INDEX_PATH", "/golden/index.json")
CHURN_DOCS = int(os.environ.get("CHURN_DOCS", "20000"))
GOLDEN_QUERIES = int(os.environ.get("GOLDEN_QUERIES", "500"))
K = int(os.environ.get("RECALL_K", "10"))
EMBED_BATCH = int(os.environ.get("EMBED_BATCH", "16"))

# Smallest beam is tried first. The chosen beam is the tightest one whose
# recall still sits near 0.95, so minute 1 is green and tombstones have room
# to pull the number down.
CANDIDATE_LADDER = (16, 24, 32, 48, 64, 96)

SEARCH_NOT_ENABLED = 31082

# Questions the talk asks live. They are part of the golden set, so the recall probes cover
# them and the degrade step knows which documents are their closest neighbours.
DEMO_QUESTIONS = (
    "urban apocalypse",
    "fast cars and racing",
    "We loved Zombicide with its miniatures, zombie hordes and survivors that level up. What else is like it?",
)


def log(*args):
    print("[osmc-seed]", *args, flush=True)


def load_games(path):
    games = []
    with open(path, encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                games.append(json.loads(line))
            except json.JSONDecodeError as exc:
                log(f"WARN skipping line {line_no}: {exc}")
    if not games:
        raise SystemExit(f"no games in {path}")
    log(f"loaded {len(games)} games from {path}")
    return games


def sentences(text):
    text = re.sub(r"\s+", " ", text or "").strip()
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if len(p.strip()) >= 40]


def passages_for(game):
    """One passage per game: its plain-English description.

    One passage per game means ten results are ten different games, which is what an
    audience can judge at a glance.
    """
    name = str(game.get("name") or "Unknown")
    text = re.sub(r"\s+", " ", game.get("description") or "").strip()
    if len(text) < 40:
        return []
    return [{"title": name, "text": text[:1200]}]


QUESTION_TEMPLATES = (
    "Which board game is this describing? {text}",
    "I want a {category} game. {text}",
    "What should our group play? {text}",
    "Find a game that uses {mechanic}. {text}",
    "A friend likes {title}. What else fits this? {text}",
)


def build_questions(passages, n):
    # Every (passage, template) pair is one distinct question. Asking for more would repeat them.
    n = min(n, len(passages) * len(QUESTION_TEMPLATES))
    questions = []
    i = 0
    while len(questions) < n:
        passage = passages[i % len(passages)]
        template = QUESTION_TEMPLATES[(i // len(passages)) % len(QUESTION_TEMPLATES)]
        category = "board"
        mechanic = "its core mechanic"
        # The first sentence of a catalog card carries the category list.
        text = passage["text"]
        questions.append(
            {
                "id": f"q-{len(questions):04d}",
                "text": template.format(
                    text=text[:280],
                    title=passage["title"],
                    category=category,
                    mechanic=mechanic,
                ),
            }
        )
        i += 1
        if i > n * len(QUESTION_TEMPLATES) * 2:
            break
    return questions


def embed_batch(texts):
    payload = json.dumps({"model": EMBED_MODEL, "input": texts}).encode()
    req = urllib.request.Request(
        OLLAMA_URL + "/api/embed",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        body = json.load(resp)
    vectors = body.get("embeddings") or []
    if len(vectors) != len(texts):
        raise RuntimeError(f"ollama returned {len(vectors)} vectors for {len(texts)} texts")
    return vectors


def embed_all(texts, label):
    out = []
    for start in range(0, len(texts), EMBED_BATCH):
        chunk = texts[start : start + EMBED_BATCH]
        for attempt in range(1, 6):
            try:
                out.extend(embed_batch(chunk))
                break
            except (urllib.error.URLError, TimeoutError, RuntimeError) as exc:
                if attempt == 5:
                    raise SystemExit(f"embedding {label} failed: {exc}") from exc
                log(f"WARN embed {label} batch {start} attempt {attempt}: {exc}")
                time.sleep(2 * attempt)
        if start % (EMBED_BATCH * 10) == 0:
            log(f"embedded {min(start + len(chunk), len(texts))}/{len(texts)} {label}")
    return out


def as_matrix(vectors):
    mat = np.asarray(vectors, dtype=np.float64)
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1
    mat = mat / norms
    return np.round(mat, 6)


def topk_ids(query_mat, doc_ids, doc_mat, k):
    # Both sides are already L2-normalised, so the dot product is cosine.
    scores = query_mat @ doc_mat.T
    k = min(k, doc_mat.shape[0])
    # argpartition then sort the short head, per query.
    idx = np.argpartition(-scores, kth=k - 1, axis=1)[:, :k]
    row = np.arange(scores.shape[0])[:, None]
    order = np.argsort(-scores[row, idx], axis=1)
    idx = idx[row, order]
    return [[doc_ids[j] for j in row_idx] for row_idx in idx]


def drop_invaders(doc_ids, doc_mat, neighbors):
    """Remove churn docs that brute force ranked inside any top-k."""
    invaded = set()
    for ids in neighbors:
        for doc_id in ids:
            if doc_id.startswith("churn-"):
                invaded.add(doc_id)
    if not invaded:
        return doc_ids, doc_mat, neighbors, 0
    keep = [i for i, doc_id in enumerate(doc_ids) if doc_id not in invaded]
    doc_ids = [doc_ids[i] for i in keep]
    doc_mat = doc_mat[keep]
    return doc_ids, doc_mat, None, len(invaded)


def connect():
    last = None
    for attempt in range(1, 61):
        try:
            client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
            if not client.admin.command("hello").get("isWritablePrimary"):
                raise AutoReconnect("mongod is not a writable primary yet")
            log("connected to mongod")
            return client
        except PyMongoError as exc:
            last = exc
            log(f"waiting for mongod ({attempt}/60): {exc}")
            time.sleep(2)
    raise SystemExit(f"could not connect to mongod: {last}")


def wait_ollama():
    """Block until the embedding model is listed, not merely until the server answers."""
    for attempt in range(1, 90):
        try:
            with urllib.request.urlopen(OLLAMA_URL + "/api/tags", timeout=3) as resp:
                body = json.load(resp)
            names = []
            for model in body.get("models") or []:
                name = str(model.get("name") or "")
                names.append(name.split(":", 1)[0])
            if EMBED_MODEL in names:
                log(f"ollama model {EMBED_MODEL} is ready")
                return
            log(f"waiting for ollama model {EMBED_MODEL} ({attempt}/90); have {names or 'none yet'}")
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            log(f"waiting for ollama ({attempt}/90): {exc}")
        time.sleep(2)
    raise SystemExit(
        f"ollama never listed {EMBED_MODEL}. Start the models profile and let it finish pulling."
    )


def create_index(coll, dims):
    definition = {
        "fields": [
            {
                "type": "vector",
                "path": "embedding",
                "numDimensions": int(dims),
                "similarity": "cosine",
            }
        ]
    }
    spec = {"name": INDEX_NAME, "type": "vectorSearch", "definition": definition}
    for attempt in range(1, 16):
        try:
            coll.create_search_index(spec)
            log(f"created vector index {INDEX_NAME} ({dims} dims)")
            return definition
        except OperationFailure as exc:
            if getattr(exc, "code", None) == SEARCH_NOT_ENABLED:
                raise SystemExit(
                    "search is not enabled on this mongod. Start mongot and use config/mongod.conf."
                ) from exc
            message = str(exc).lower()
            if "search index management" in message or getattr(exc, "code", None) == 125:
                log(f"WARN mongot not ready ({attempt}/15): {exc}")
                time.sleep(4)
                continue
            if "already exists" in message:
                log(f"index {INDEX_NAME} already exists")
                return definition
            raise
    raise SystemExit("could not create the vector index")


def wait_ready(coll):
    deadline = time.time() + 600
    while time.time() < deadline:
        try:
            status = {idx["name"]: idx.get("status") for idx in coll.list_search_indexes()}
        except PyMongoError as exc:
            log(f"WARN polling index status: {exc}")
            time.sleep(2)
            continue
        log(f"index status: {status.get(INDEX_NAME)}")
        if status.get(INDEX_NAME) == "READY":
            return
        time.sleep(2)
    raise SystemExit("timed out waiting for the vector index to become READY")


def ann_ids(coll, vector, num_candidates):
    docs = coll.aggregate(
        [
            {
                "$vectorSearch": {
                    "index": INDEX_NAME,
                    "path": "embedding",
                    "queryVector": vector,
                    "numCandidates": int(num_candidates),
                    "limit": K,
                }
            },
            {"$project": {"_id": 1}},
        ]
    )
    return [doc["_id"] for doc in docs]


def recall_of(got, truth):
    return len(set(got) & set(truth)) / K


def calibrate(coll, queries):
    best = None
    for num_candidates in CANDIDATE_LADDER:
        scores = []
        for i, query in enumerate(queries):
            got = ann_ids(coll, query["vector"], num_candidates)
            scores.append(recall_of(got, query["neighbors"]))
            if i and i % 100 == 0:
                log(f"calibrate numCandidates={num_candidates} {i}/{len(queries)}")
        measured = float(np.mean(scores))
        log(f"numCandidates={num_candidates} recall@{K}={measured:.3f}")
        if best is None:
            best = (num_candidates, measured)
            continue
        # Prefer the tightest beam that is still a green ~0.95.
        in_band = 0.93 <= measured <= 0.97
        best_in_band = 0.93 <= best[1] <= 0.97
        if in_band and not best_in_band:
            best = (num_candidates, measured)
        elif in_band and best_in_band and num_candidates < best[0]:
            best = (num_candidates, measured)
        elif not best_in_band and abs(measured - 0.95) < abs(best[1] - 0.95):
            best = (num_candidates, measured)
    if best[1] > 0.98:
        log(
            "WARN recall stayed above 0.98 even at the tightest beam. "
            "Raise CHURN_DOCS or DELETE_FRACTION if the live drop is too small."
        )
    return best


def write_json(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    os.replace(tmp, path)


def rows(ids, titles, texts, roles, mat):
    docs = []
    for i, doc_id in enumerate(ids):
        docs.append(
            {
                "_id": doc_id,
                "role": roles[i],
                "title": titles[i],
                "text": texts[i],
                "embedding": mat[i].tolist(),
            }
        )
    return docs


def insert_batches(coll, docs):
    for start in range(0, len(docs), 500):
        coll.insert_many(docs[start : start + 500], ordered=False)
        log(f"inserted {min(start + 500, len(docs))}/{len(docs)}")


def main():
    wait_ollama()
    games = load_games(DATA_FILE)
    passages = []
    for game in games:
        passages.extend(passages_for(game))
    if len(passages) < K:
        raise SystemExit(f"only {len(passages)} passages; need at least {K}")
    log(f"{len(passages)} stable passages")
    questions = build_questions(passages, GOLDEN_QUERIES)
    for i, text in enumerate(DEMO_QUESTIONS):
        questions.append({"id": f"demo-{i}", "text": text})
    log(f"{len(questions)} golden questions")

    passage_mat = as_matrix(embed_all([p["text"] for p in passages], "passages"))
    question_mat = as_matrix(embed_all([q["text"] for q in questions], "questions"))
    dims = int(passage_mat.shape[1])
    log(f"embedding dimension {dims}")

    rng = np.random.default_rng(2026)
    churn_mat = rng.normal(size=(CHURN_DOCS, dims))
    churn_mat = as_matrix(churn_mat)
    stable_ids = [f"stable-{i:06d}" for i in range(len(passages))]
    churn_ids = [f"churn-{i:06d}" for i in range(CHURN_DOCS)]
    doc_ids = stable_ids + churn_ids
    doc_mat = np.vstack([passage_mat, churn_mat])

    neighbors = topk_ids(question_mat, doc_ids, doc_mat, K)
    for _ in range(5):
        doc_ids, doc_mat, neighbors, removed = drop_invaders(doc_ids, doc_mat, neighbors)
        if removed == 0:
            break
        log(f"removed {removed} churn vectors that entered a top-{K}")
        neighbors = topk_ids(question_mat, doc_ids, doc_mat, K)
    invaders = sum(1 for ids in neighbors for doc_id in ids if doc_id.startswith("churn-"))
    if invaders:
        raise SystemExit(f"{invaders} churn ids remain inside the golden top-{K}")

    kept_churn = [doc_id for doc_id in doc_ids if doc_id.startswith("churn-")]
    log(f"keeping {len(kept_churn)} churn vectors outside every golden top-{K}")

    client = connect()
    coll = client[MONGO_DB][MONGO_COLLECTION]
    coll.drop()
    log(f"dropped {MONGO_DB}.{MONGO_COLLECTION}")

    id_to_row = {doc_id: i for i, doc_id in enumerate(doc_ids)}
    stable_rows = rows(
        stable_ids,
        [p["title"] for p in passages],
        [p["text"] for p in passages],
        ["stable"] * len(passages),
        passage_mat,
    )
    churn_rows = []
    if kept_churn:
        churn_rows = rows(
            kept_churn,
            ["Catalog note"] * len(kept_churn),
            [
                "Catalog filler used to bulk the vector index. Not a published board game."
            ]
            * len(kept_churn),
            ["churn"] * len(kept_churn),
            np.vstack([doc_mat[id_to_row[doc_id]] for doc_id in kept_churn]),
        )
    insert_batches(coll, stable_rows)
    if churn_rows:
        insert_batches(coll, churn_rows)

    definition = create_index(coll, dims)
    wait_ready(coll)

    golden_queries = []
    for query, vector, ids in zip(questions, question_mat, neighbors):
        golden_queries.append(
            {
                "id": query["id"],
                "demo": query["id"].startswith("demo-"),
                "text": query["text"],
                "vector": vector.tolist(),
                "neighbors": ids,
            }
        )
    num_candidates, measured = calibrate(coll, golden_queries)
    log(f"using numCandidates={num_candidates} (measured recall@{K}={measured:.3f})")

    write_json(
        GOLDEN_PATH,
        {
            "db": MONGO_DB,
            "collection": MONGO_COLLECTION,
            "index": INDEX_NAME,
            "k": K,
            "numCandidates": num_candidates,
            "dims": dims,
            "measuredRecall": round(measured, 4),
            "queries": golden_queries,
        },
    )
    write_json(
        INDEX_PATH,
        {
            "db": MONGO_DB,
            "collection": MONGO_COLLECTION,
            "name": INDEX_NAME,
            "definition": definition,
        },
    )
    log(f"wrote {GOLDEN_PATH} and {INDEX_PATH}")


if __name__ == "__main__":
    main()
