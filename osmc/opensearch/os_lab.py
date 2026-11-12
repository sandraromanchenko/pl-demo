#!/usr/bin/env python3
"""OpenSearch (Faiss HNSW) alternative for the recall demo.

Same vectors as the mongot demo, copied from MongoDB. Commands:

  load      create the index, bulk-load every vector, merge to one clean segment
  recall    recall@k against an exact scan of the live documents
  ask [q]   one question: what the app gets next to what an exact scan returns
  degrade   delete documents that are in the questions' true top-k
  degrade-both  the same deletes in MongoDB (mongot) and OpenSearch
  restore   undo degrade-both and reload OpenSearch
  merge     expunge deleted documents (the "reindex" moment)
  swap-model [name]  embed questions with another model of the same size (default snowflake-arctic-embed:22m)
  restore-model      go back to the model the catalog was built with
  quantize [scalar|binary]  move Percona Search (mongot) to a quantized vector index: less memory, lower recall
  unquantize                go back to the full-precision vector index
  watch     recall every few seconds
  status    segments and live document count

Why this can fail where mongot does not: the Faiss engine searches the graph
first and drops deleted documents afterwards, so a deleted neighbour uses up a
result slot. Lucene (mongot) skips deleted documents while it walks the graph.
"""

import json
import os
import random
import sys
import time
import urllib.error
import urllib.request

import numpy as np

OS_URL = os.environ.get("OPENSEARCH_URL", "http://opensearch:9200").rstrip("/")
INDEX = os.environ.get("OS_INDEX", "catalog_os")
MONGO_URI = os.environ.get(
    "MONGO_URI",
    "mongodb://root:root@mongod:27017/?authSource=admin&directConnection=true",
)
MONGO_DB = os.environ.get("MONGO_DB", "boardgames")
MONGO_COLLECTION = os.environ.get("MONGO_COLLECTION", "catalog")
GOLDEN = os.environ.get("GOLDEN_PATH", "/golden/golden.json")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434").rstrip("/")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "bge-small")
# The model the catalog vectors were built with. The reference for "the right answer".
INDEX_MODEL = os.environ.get("INDEX_EMBED_MODEL", "bge-small")
# The model the application embeds questions with. `swap-model` writes it here so every
# service that answers questions (search app, assistant, probes) switches at once.
QUERY_MODEL_FILE = os.environ.get("QUERY_MODEL_FILE", "/golden/query_model")
EF_SEARCH = int(os.environ.get("EF_SEARCH", "100"))
DELETE_FRACTION = float(os.environ.get("DELETE_FRACTION", "0.3"))
WATCH_SECONDS = int(os.environ.get("WATCH_SECONDS", "10"))
# Where "the right answer" comes from. builtin: OpenSearch's exact k-NN (script_score).
# numpy: pull every vector out and score them here, as an independent cross-check.
TRUTH = os.environ.get("OS_TRUTH", "builtin")
DEFAULT_QUESTION = (
    "We loved Zombicide with its miniatures, zombie hordes and survivors that level up. What else is like it?"
)


def log(msg):
    print(msg, flush=True)


def call(method, path, body=None, raw=None, ok404=False, timeout=300):
    data = None
    headers = {}
    if raw is not None:
        data = raw.encode("utf-8")
        headers["Content-Type"] = "application/x-ndjson"
    elif body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(OS_URL + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        if ok404 and exc.code == 404:
            return None
        raise SystemExit(f"{method} {path} -> {exc.code}: {exc.read().decode('utf-8')[:500]}")
    return json.loads(text) if text else {}


def wait_up():
    for attempt in range(1, 61):
        try:
            health = call("GET", "/_cluster/health")
            if health.get("status") in ("green", "yellow"):
                return
        except (SystemExit, urllib.error.URLError, ConnectionError, TimeoutError, OSError):
            pass
        log(f"waiting for opensearch ({attempt}/60)")
        time.sleep(3)
    raise SystemExit("opensearch never became healthy")


def unit(mat):
    mat = np.asarray(mat, dtype=np.float32)
    norm = np.linalg.norm(mat, axis=1, keepdims=True)
    norm[norm == 0] = 1
    return mat / norm


def load_golden():
    with open(GOLDEN, encoding="utf-8") as fh:
        return json.load(fh)


def segments():
    rows = call("GET", f"/_cat/segments/{INDEX}?format=json&h=segment,docs.count,docs.deleted,size")
    return rows or []


def print_status():
    count = call("GET", f"/{INDEX}/_count")["count"]
    rows = segments()
    deleted = sum(int(r["docs.deleted"]) for r in rows)
    log(f"live docs {count}, segments {len(rows)}, deleted docs still in segments {deleted}")
    for r in rows:
        log(f"  {r['segment']}: {r['docs.count']} docs, {r['docs.deleted']} deleted, {r['size']}")


def cmd_load():
    from pymongo import MongoClient

    wait_up()
    coll = MongoClient(MONGO_URI)[MONGO_DB][MONGO_COLLECTION]
    first = coll.find_one({"embedding": {"$exists": True}}, {"embedding": 1})
    if not first:
        raise SystemExit(f"{MONGO_DB}.{MONGO_COLLECTION} has no vectors; run the osmc seed first")
    dims = len(first["embedding"])
    # One node cannot hold a replica next to its primary. Without this, a system index such as
    # .opensearch-knn-models keeps one shard unassigned and the cluster shows yellow for no reason.
    call("PUT", "/_index_template/demo_no_replicas", {
        "index_patterns": ["*"], "priority": 1,
        "template": {"settings": {"index": {"number_of_replicas": 0}}},
    })
    call("PUT", "/_all/_settings", {"index": {"number_of_replicas": 0}})
    call("DELETE", f"/{INDEX}", ok404=True)
    call(
        "PUT",
        f"/{INDEX}",
        {
            "settings": {
                "index.knn": True,
                "index.number_of_shards": 1,
                "index.number_of_replicas": 0,
                "index.refresh_interval": "-1",
                # Default is 15000. Below that the segment is scanned exactly and
                # no HNSW graph exists, which would hide everything we want to see.
                "index.knn.advanced.approximate_threshold": 0,
                # Highest value the policy allows, so a small delete is never merged away.
                "index.merge.policy.deletes_pct_allowed": 50,
            },
            "mappings": {
                "properties": {
                    "embedding": {
                        "type": "knn_vector",
                        "dimension": dims,
                        "method": {
                            "name": "hnsw",
                            "engine": "faiss",
                            "space_type": "l2",
                            "parameters": {"m": 16, "ef_construction": 100},
                        },
                    },
                    "title": {"type": "text"},
                    "text": {"type": "text"},
                    "role": {"type": "keyword"},
                }
            },
        },
    )
    batch = []
    total = 0

    def flush():
        nonlocal batch, total
        if not batch:
            return
        lines = []
        for doc in batch:
            lines.append(json.dumps({"index": {"_id": doc["_id"]}}))
            lines.append(
                json.dumps(
                    {
                        "title": doc.get("title", ""),
                        "text": doc.get("text", ""),
                        "role": doc.get("role", ""),
                        "embedding": doc["embedding"],
                    }
                )
            )
        result = call("POST", f"/{INDEX}/_bulk", raw="\n".join(lines) + "\n")
        if result.get("errors"):
            bad = [i for i in result["items"] if i["index"].get("error")][:2]
            raise SystemExit(f"bulk errors: {bad}")
        total += len(batch)
        log(f"loaded {total}")
        batch = []

    for doc in coll.find({"embedding": {"$exists": True}}):
        batch.append(doc)
        if len(batch) >= 1000:
            flush()
    flush()
    call("PUT", f"/{INDEX}/_settings", {"index": {"refresh_interval": "1s"}})
    call("POST", f"/{INDEX}/_refresh")
    log("merging to one segment so the baseline graph is a clean bulk build")
    call("POST", f"/{INDEX}/_forcemerge?max_num_segments=1&wait_for_completion=true")
    call("POST", f"/{INDEX}/_refresh")
    print_status()


def live_matrix():
    ids, vecs = [], []
    res = call(
        "POST",
        f"/{INDEX}/_search?scroll=2m",
        {"size": 1000, "_source": ["embedding"], "query": {"match_all": {}}},
    )
    sid = res.get("_scroll_id")
    while True:
        hits = res["hits"]["hits"]
        if not hits:
            break
        for h in hits:
            ids.append(h["_id"])
            vecs.append(h["_source"]["embedding"])
        res = call("POST", "/_search/scroll", {"scroll": "2m", "scroll_id": sid})
        sid = res.get("_scroll_id", sid)
    if sid:
        call("DELETE", "/_search/scroll", {"scroll_id": [sid]}, ok404=True)
    return ids, unit(np.array(vecs, dtype=np.float32))


def ann_search(vector, k):
    """What the application gets: the Faiss HNSW answer."""
    res = call(
        "POST",
        f"/{INDEX}/_search",
        {
            "size": k,
            "_source": False,
            "query": {
                "knn": {
                    "embedding": {
                        "vector": vector,
                        "k": k,
                        "method_parameters": {"ef_search": EF_SEARCH},
                    }
                }
            },
        },
    )
    return [h["_id"] for h in res["hits"]["hits"]]


def exact_search(vector, k):
    """OpenSearch's own exact k-NN: score every live document, return the best k.

    A script_score query with the knn_score script is a brute-force scan. It only
    visits live documents, so deleted ones can never take a slot.
    """
    res = call(
        "POST",
        f"/{INDEX}/_search",
        {
            "size": k,
            "_source": False,
            "query": {
                "script_score": {
                    "query": {"match_all": {}},
                    "script": {
                        "source": "knn_score",
                        "lang": "knn",
                        "params": {
                            "field": "embedding",
                            "query_value": vector,
                            "space_type": "l2",
                        },
                    },
                }
            },
        },
    )
    return [h["_id"] for h in res["hits"]["hits"]]


def cmd_check():
    """Does OpenSearch's built-in exact search agree with an exact scan done in numpy?"""
    wait_up()
    golden = load_golden()
    k = int(golden["k"])
    ids, mat = live_matrix()
    queries = golden["queries"][:: max(1, len(golden["queries"]) // 100)][:100]
    qmat = unit(np.array([q["vector"] for q in queries], dtype=np.float32))
    truth = np.argsort(-(qmat @ mat.T), axis=1)[:, :k]
    same, builtin_ms = 0, []
    for qi, q in enumerate(queries):
        started = time.perf_counter()
        builtin = set(exact_search(q["vector"], k))
        builtin_ms.append((time.perf_counter() - started) * 1000)
        same += builtin == {ids[j] for j in truth[qi]}
    log(
        f"built-in exact kNN vs numpy: identical top-{k} for {same} of {len(queries)} questions; "
        f"built-in exact search takes {np.mean(builtin_ms):.0f} ms per question"
    )


def measure(golden, sample=None):
    """Recall@k against an exact scan of the live documents.

    Returns a dict: recall, hits (avg returned per query), live, latency (avg seconds).
    """
    k = int(golden["k"])
    queries = golden["queries"]
    if sample and sample < len(queries):
        step = len(queries) / sample
        queries = [queries[int(i * step)] for i in range(sample)]
    truth_ids = None
    if TRUTH == "numpy":  # cross-check: exact scan done outside OpenSearch
        ids, mat = live_matrix()
        qmat = unit(np.array([q["vector"] for q in queries], dtype=np.float32))
        truth_ids = np.argsort(-(qmat @ mat.T), axis=1)[:, :k]
    scores, returned, latency = [], [], []
    for qi, q in enumerate(queries):
        started = time.perf_counter()
        got = set(ann_search(q["vector"], k))
        latency.append(time.perf_counter() - started)
        if truth_ids is not None:
            want = {ids[j] for j in truth_ids[qi]}
        else:
            want = set(exact_search(q["vector"], k))  # OpenSearch's own exact k-NN
        scores.append(len(got & want) / k)
        returned.append(len(got))
    return {
        "recall": float(np.mean(scores)),
        "hits": float(np.mean(returned)),
        "live": call("GET", f"/{INDEX}/_count")["count"],
        "latency": float(np.mean(latency)),
        "latency_p99": float(np.percentile(latency, 99)),
        "k": k,
    }


def cmd_recall():
    wait_up()
    m = measure(load_golden())
    log(f"recall@{m['k']} = {m['recall']:.3f}  (avg hits returned {m['hits']:.2f}, live docs {m['live']})")


def query_model():
    """The model the application currently embeds questions with."""
    try:
        with open(QUERY_MODEL_FILE, encoding="utf-8") as fh:
            name = fh.read().strip()
        if name:
            return name
    except OSError:
        pass
    return EMBED_MODEL


def embed(text, model=None):
    """Embed one text. Default: the model the application uses for questions right now."""
    req = urllib.request.Request(
        OLLAMA_URL + "/api/embed",
        data=json.dumps({"model": model or query_model(), "input": [text]}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())["embeddings"][0]


def titles(doc_ids):
    if not doc_ids:
        return {}
    res = call("POST", f"/{INDEX}/_mget?_source_includes=title", {"ids": list(doc_ids)})
    return {d["_id"]: d.get("_source", {}).get("title", d["_id"]) for d in res["docs"]}


def cmd_ask():
    wait_up()
    question = " ".join(sys.argv[2:]).strip() or DEFAULT_QUESTION
    k = int(load_golden()["k"])
    vector = embed(question)  # what the app does: the model it uses today
    # The right answer is an exact scan with the model the catalog was built with.
    reference = vector if query_model() == INDEX_MODEL else embed(question, INDEX_MODEL)
    ids, mat = live_matrix()
    order = np.argsort(-(unit([reference]) @ mat.T)[0])
    exact = [ids[j] for j in order[:k]]
    near_ids = [ids[j] for j in order[: 2 * k]]
    got = ann_search(vector, k)
    names = titles(set(exact) | set(got) | set(near_ids))
    # A game has several passages: judge the game, not the passage. Ranks 11-20 count too,
    # an index may swap rank 10 for 11.
    near = {d for d in set(got) if names[d] in {names[i] for i in near_ids}}
    log(f"question: {question}\n")
    log(f"question embedded with: {query_model()}   (catalog built with: {INDEX_MODEL})\n")
    log(f"what the app gets (OpenSearch HNSW, asked for {k}): {len(got)} results")
    for rank, doc_id in enumerate(got, 1):
        mark = "" if doc_id in near else "   <-- this game is not in the exact answer"
        log(f"  {rank:>2}. {names[doc_id]}{mark}")
    missing = [d for d in exact if d not in set(got)]
    log(f"\nwhat an exact scan of the live documents returns: {len(exact)} results")
    wrong = [d for d in got if d not in near]
    if wrong:
        log(f"results whose game is not in the exact answer: {len(wrong)} of {len(got)}")
    if missing:
        log(f"missing from the app's answer ({len(missing)}):")
        for doc_id in missing:
            log(f"   - {names[doc_id]}")
    if not wrong and not missing:
        log("nothing missing: the app's answer matches the exact answer")


def cmd_swap_model():
    """Change the model the application embeds questions with. The catalog is not touched.

    The new model has the same number of dimensions, so nothing errors: every search
    still runs and returns ten results.
    """
    name = (sys.argv[2] if len(sys.argv) > 2 else "snowflake-arctic-embed:22m").strip()
    if name == INDEX_MODEL:
        raise SystemExit(
            f"{name} is the model the catalog was built with, so nothing would change. "
            "Use another model with the same size, for example snowflake-arctic-embed:22m."
        )
    tags = json.loads(urllib.request.urlopen(OLLAMA_URL + "/api/tags", timeout=10).read())
    have = {m["name"] for m in tags.get("models", [])}
    have |= {n[: -len(":latest")] for n in have if n.endswith(":latest")}
    if name not in have:
        log(f"pulling {name} into Ollama (do this before the talk; it needs the internet)")
        req = urllib.request.Request(
            OLLAMA_URL + "/api/pull",
            data=json.dumps({"model": name, "stream": False}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=900).read()
    dims_new = len(embed("dimension check", name))
    dims_old = len(embed("dimension check", INDEX_MODEL))
    if dims_new != dims_old:
        raise SystemExit(
            f"{name} has {dims_new} dimensions, the catalog has {dims_old}. "
            "That would fail loudly, which is not the demo. Pick a model with the same size."
        )
    with open(QUERY_MODEL_FILE, "w", encoding="utf-8") as fh:
        fh.write(name + "\n")
    log(f"questions are now embedded with {name} ({dims_new} dimensions, same as {INDEX_MODEL})")
    log("the catalog and both indexes are unchanged")


def cmd_restore_model():
    try:
        os.remove(QUERY_MODEL_FILE)
    except FileNotFoundError:
        pass
    log(f"questions are embedded with {query_model()} again")


def pick_victims(golden):
    """The documents that sit in some question's top-k. The same ones for both engines.

    The questions the talk asks live (golden entries with demo=true) lose a fixed share of
    their closest neighbours, so the cold open does not depend on a lucky shuffle.
    """
    wanted = []
    seen = set()
    for q in golden["queries"]:
        for nid in q["neighbors"]:
            if nid not in seen:
                seen.add(nid)
                wanted.append(nid)
    rng = random.Random(1)
    rng.shuffle(wanted)
    victims = wanted[: int(len(wanted) * DELETE_FRACTION)]
    chosen = set(victims)
    for q in golden["queries"]:
        if q.get("demo"):
            # Ranks 2, 3, 5 and 7: the engine is left with the rest of the top 10.
            for rank in (1, 2, 4, 6):
                if rank < len(q["neighbors"]) and q["neighbors"][rank] not in chosen:
                    chosen.add(q["neighbors"][rank])
                    victims.append(q["neighbors"][rank])
    return wanted, victims


def mongo_catalog():
    from pymongo import MongoClient

    db = MongoClient(MONGO_URI)[MONGO_DB]
    return db[MONGO_COLLECTION], db[MONGO_COLLECTION + "_backup"]


def cmd_degrade_both():
    """Delete the same documents from MongoDB (mongot) and from OpenSearch.

    The documents are copied to <collection>_backup first so `restore` can put them back.
    """
    golden = load_golden()
    _, victims = pick_victims(golden)
    coll, backup = mongo_catalog()
    docs = list(coll.find({"_id": {"$in": victims}}))
    # Only add what is still there. A second run must not wipe the first run's backup
    # of documents that are already gone.
    for doc in docs:
        backup.replace_one({"_id": doc["_id"]}, doc, upsert=True)
    result = coll.delete_many({"_id": {"$in": victims}})
    log(f"MongoDB (mongot): deleted {result.deleted_count} of {len(victims)} documents, backup in {backup.name}")
    cmd_degrade()


def cmd_restore():
    """Undo degrade-both: put the documents back into MongoDB and reload OpenSearch."""
    coll, backup = mongo_catalog()
    docs = list(backup.find({}))
    for doc in docs:
        coll.replace_one({"_id": doc["_id"]}, doc, upsert=True)
    backup.drop()
    log(f"MongoDB (mongot): restored {len(docs)} documents; mongot re-indexes them from the change stream")
    cmd_load()
    cmd_restore_model()
    cmd_unquantize()


# ---- quantization (Percona Search / mongot only) ------------------------------------------------
BASE_INDEX = os.environ.get("VECTOR_INDEX", "vec_osmc")
INDEX_SPEC = os.environ.get("INDEX_PATH", "/golden/index.json")
QUANT_MODES = ("scalar", "binary")


def write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(data, fh)
    os.replace(tmp, path)


def build_vector_index(coll, name, definition):
    """Create a vector index next to the running one and wait until it is READY."""
    existing = [r["name"] for r in coll.aggregate([{"$listSearchIndexes": {}}])]
    if name in existing:
        coll.drop_search_index(name)
        time.sleep(3)
    started = time.time()
    coll.create_search_index({"name": name, "type": "vectorSearch", "definition": definition})
    while True:
        rows = list(coll.aggregate([{"$listSearchIndexes": {"name": name}}]))
        status = rows[0]["status"] if rows else "MISSING"
        if status == "READY":
            log(f"index {name} is READY after {round(time.time() - started)} s")
            return
        if status == "FAILED" or time.time() - started > 900:
            raise SystemExit(f"index {name}: {status}")
        time.sleep(2)


def switch_vector_index(coll, name, definition, num_candidates=None):
    """Point the app, the probes and the canaries at `name`, then drop every other vector index
    of this demo. The new index is built first, so searches never see a gap."""
    golden = json.load(open(GOLDEN))
    old = golden["index"]
    # Keep the calibrated numCandidates, so unquantize can go back to it.
    golden.setdefault("baselineNumCandidates", golden["numCandidates"])
    if num_candidates:
        golden["numCandidates"] = int(num_candidates)
    golden["index"] = name
    write_json(GOLDEN, golden)
    spec = json.load(open(INDEX_SPEC))
    spec["name"], spec["definition"] = name, definition
    write_json(INDEX_SPEC, spec)
    for row in coll.aggregate([{"$listSearchIndexes": {}}]):
        other = row["name"]
        if other != name and (other == BASE_INDEX or other.startswith(BASE_INDEX + "_")):
            coll.drop_search_index(other)
            log(f"dropped index {other}")
    log(f"searches, probes and canaries now use {name} (numCandidates {golden['numCandidates']})")
    return old


def cmd_quantize():
    """Store the vectors of the Percona Search index as 8-bit numbers (scalar) or single bits (binary).

    Same documents, same model, same engine. The index needs a fraction of the memory, and
    some of the nearest neighbours are lost. ANN recall shows the loss; status panels do not.
    A second index is built next to the first, the app is switched over, then the old one is dropped.
    CANDIDATES=<n> sets numCandidates (binary recovers with a higher value, scalar does not).
    """
    mode = (sys.argv[2] if len(sys.argv) > 2 else os.environ.get("QUANT_MODE", "scalar")).lower()
    if mode not in QUANT_MODES:
        raise SystemExit("usage: quantize " + "|".join(QUANT_MODES))
    coll, _ = mongo_catalog()
    spec = json.load(open(INDEX_SPEC))
    field = dict(spec["definition"]["fields"][0])
    field["quantization"] = mode
    definition = {"fields": [field]}
    log(f"building a {mode}-quantized index next to the current one")
    name = f"{BASE_INDEX}_{mode}"
    build_vector_index(coll, name, definition)
    switch_vector_index(coll, name, definition, os.environ.get("CANDIDATES"))


def cmd_unquantize():
    """Back to full-precision vectors (float32), with the numCandidates the catalog was seeded with."""
    coll, _ = mongo_catalog()
    golden = json.load(open(GOLDEN))
    spec = json.load(open(INDEX_SPEC))
    quantized = golden["index"] != BASE_INDEX or "quantization" in spec["definition"]["fields"][0]
    if not quantized and "baselineNumCandidates" not in golden:
        log("the index is already full precision")
        return
    field = {k: v for k, v in spec["definition"]["fields"][0].items() if k != "quantization"}
    definition = {"fields": [field]}
    if golden["index"] != BASE_INDEX or quantized:
        log("building the full-precision index next to the quantized one")
        build_vector_index(coll, BASE_INDEX, definition)
    switch_vector_index(coll, BASE_INDEX, definition, golden.get("baselineNumCandidates"))
    golden = json.load(open(GOLDEN))
    golden.pop("baselineNumCandidates", None)
    write_json(GOLDEN, golden)



def cmd_degrade():
    wait_up()
    golden = load_golden()
    wanted, victims = pick_victims(golden)
    log(f"deleting {len(victims)} of {len(wanted)} documents that are in some question's top-{golden['k']}")
    removed = 0
    for start in range(0, len(victims), 500):
        chunk = victims[start : start + 500]
        raw = "\n".join(json.dumps({"delete": {"_id": i}}) for i in chunk) + "\n"
        result = call("POST", f"/{INDEX}/_bulk", raw=raw)
        removed += sum(1 for item in result["items"] if item["delete"].get("result") == "deleted")
    call("POST", f"/{INDEX}/_refresh")
    if removed < len(victims):
        log(
            f"WARN only {removed} of {len(victims)} were still present. "
            "They were deleted by an earlier run; reset with: make os-load"
        )
    print_status()


def cmd_merge():
    wait_up()
    call(
        "PUT",
        f"/{INDEX}/_settings",
        {"index": {"merge.policy.expunge_deletes_allowed": 0}},
    )
    log("expunging deleted documents (forces the graph to be rebuilt)")
    call("POST", f"/{INDEX}/_forcemerge?only_expunge_deletes=true&wait_for_completion=true")
    call("POST", f"/{INDEX}/_refresh")
    print_status()


def cmd_status():
    wait_up()
    print_status()


def cmd_watch():
    wait_up()
    golden = load_golden()
    while True:
        m = measure(golden)
        log(
            f"{time.strftime('%H:%M:%S')} recall@{m['k']} = {m['recall']:.3f}  "
            f"hits {m['hits']:.2f}  live {m['live']}"
        )
        time.sleep(WATCH_SECONDS)


COMMANDS = {
    "load": cmd_load,
    "recall": cmd_recall,
    "ask": cmd_ask,
    "degrade": cmd_degrade,
    "degrade-both": cmd_degrade_both,
    "restore": cmd_restore,
    "merge": cmd_merge,
    "swap-model": cmd_swap_model,
    "restore-model": cmd_restore_model,
    "quantize": cmd_quantize,
    "unquantize": cmd_unquantize,
    "check": cmd_check,
    "status": cmd_status,
    "watch": cmd_watch,
}


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        raise SystemExit("usage: os_lab.py " + "|".join(COMMANDS))
    COMMANDS[sys.argv[1]]()
