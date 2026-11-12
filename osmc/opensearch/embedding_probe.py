#!/usr/bin/env python3
"""Prometheus exporter for the layer the recall probe cannot see: the embedding model.

The recall probes replay frozen question vectors and compare the engine with an exact scan
of the same vectors. They never call the embedding model, so a model swap does not move them.
This probe goes through the same path as the application: it sends text to the model the
application uses *right now* and looks at what comes back.

  embedding_canary_cosine_mean / _min
      Embed the text of stored passages with the live model and compare with the vector that
      was stored for that passage. Same model: 1.0. Another model, even with the same number
      of dimensions: far below.

  embedding_end_to_end_recall_at_10{engine}
      Embed a golden question with the live model, search the engine, and compare with an
      exact scan using the vector the question had when the catalog was built.
      Index recall is about the engine. This is about the whole path.

  embedding_model_match
      1 if the model the application embeds questions with is the one the catalog was built with.

Needs MongoDB (stored passages, mongot) and OpenSearch. Either one being down only drops its series.
"""

import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import numpy as np
from pymongo import MongoClient

import os_lab

ADDR = os.environ.get("EXPORTER_ADDR", ":9952")
INTERVAL = float(os.environ.get("PROBE_INTERVAL", "15"))
CANARY = int(os.environ.get("CANARY_PASSAGES", "20"))
QUESTIONS = int(os.environ.get("E2E_QUESTIONS", "20"))

lock = threading.Lock()
snapshot = {}
_canary = None
_mongo = None


def mongo_coll():
    global _mongo
    if _mongo is None:
        _mongo = MongoClient(os_lab.MONGO_URI, serverSelectionTimeoutMS=5000)
    return _mongo[os_lab.MONGO_DB][os_lab.MONGO_COLLECTION]


def canary_set():
    """A fixed handful of stored passages: their text and the vector stored for them right now.

    The games are the same every time; the stored vector is read again on every probe, so a
    re-embedded game (a migration under way) is compared with the vector it has today.
    """
    global _canary
    if _canary is None:
        docs = list(mongo_coll().find({"role": "stable"}, {"_id": 1}).sort("_id", 1))
        if not docs:
            raise RuntimeError("no stable passages in the catalog")
        step = max(1, len(docs) // CANARY)
        _canary = [d["_id"] for d in docs[::step][:CANARY]]
    rows = {d["_id"]: d for d in mongo_coll().find({"_id": {"$in": _canary}}, {"text": 1, "embedding": 1})}
    return [(rows[i]["text"], np.asarray(rows[i]["embedding"], dtype=np.float64)) for i in _canary if i in rows]


def canary_cosine():
    sims = []
    for text, stored in canary_set():
        live = np.asarray(os_lab.embed(text), dtype=np.float64)
        sims.append(float(live @ stored / (np.linalg.norm(live) * np.linalg.norm(stored))))
    return float(np.mean(sims)), float(np.min(sims))


def sample_questions(golden):
    queries = golden["queries"]
    step = max(1, len(queries) // QUESTIONS)
    return queries[::step][:QUESTIONS]


def mongot_ids(vector, golden, k, exact):
    stage = {
        "index": golden["index"],
        "path": "embedding",
        "queryVector": vector,
        "limit": k,
    }
    if exact:
        stage["exact"] = True
    else:
        stage["numCandidates"] = max(int(golden.get("numCandidates", k)), k)
    rows = mongo_coll().aggregate([{"$vectorSearch": stage}, {"$project": {"_id": 1}}])
    return {r["_id"] for r in rows}


def end_to_end(golden):
    """Per engine: mean overlap of (live-model question -> engine) with (build-time vector -> exact)."""
    k = int(golden["k"])
    scores = {"mongot": [], "opensearch": []}
    for q in sample_questions(golden):
        live = os_lab.embed(q["text"])
        try:
            want = mongot_ids(q["vector"], golden, k, exact=True)
            scores["mongot"].append(len(mongot_ids(live, golden, k, exact=False) & want) / k)
        except Exception as exc:
            print(f"mongot probe failed: {str(exc)[:200]}", flush=True)
        try:
            want = set(os_lab.exact_search(q["vector"], k))
            scores["opensearch"].append(len(set(os_lab.ann_search(live, k)) & want) / k)
        except (SystemExit, Exception) as exc:
            print(f"opensearch probe failed: {str(exc)[:200]}", flush=True)
    return k, {name: float(np.mean(v)) for name, v in scores.items() if v}


def collect():
    out = {"up": 0, "query_model": os_lab.query_model(), "index_model": os_lab.INDEX_MODEL}
    try:
        out["cos_mean"], out["cos_min"] = canary_cosine()
        golden = os_lab.load_golden()
        out["k"], out["e2e"] = end_to_end(golden)
        out["up"] = 1
        out["probed_at"] = time.time()
    except (SystemExit, Exception) as exc:  # keep serving the model names even if a probe fails
        print(f"probe failed: {str(exc)[:300]}", flush=True)
    return out


def loop():
    last = {}
    while True:
        cur = collect()
        for key in ("cos_mean", "cos_min", "k", "e2e", "probed_at"):
            if key not in cur and key in last:
                cur[key] = last[key]
        last = cur
        with lock:
            snapshot.clear()
            snapshot.update(cur)
        time.sleep(INTERVAL)


def render():
    with lock:
        s = dict(snapshot)
    lines = []

    def metric(name, help_text, value, labels=""):
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} gauge")
        if isinstance(value, dict):
            for label, v in value.items():
                lines.append(f'{name}{{engine="{label}"}} {v:.6f}')
        else:
            lines.append(f"{name}{labels} {value}")

    metric("embedding_probe_up", "1 if the last embedding probe completed.", s.get("up", 0))
    if s.get("query_model"):
        metric("embedding_model_match",
               "1 if questions are embedded with the model the catalog was built with.",
               1 if s["query_model"] == s["index_model"] else 0)
        metric("embedding_query_model_info", "Model the application embeds questions with.",
               1, f'{{model="{s["query_model"]}"}}')
        metric("embedding_index_model_info", "Model the catalog vectors were built with.",
               1, f'{{model="{s["index_model"]}"}}')
    if "cos_mean" in s:
        metric("embedding_canary_cosine_mean",
               "Cosine between a stored passage vector and the same text embedded now (mean).",
               f'{s["cos_mean"]:.6f}')
        metric("embedding_canary_cosine_min",
               "Cosine between a stored passage vector and the same text embedded now (lowest).",
               f'{s["cos_min"]:.6f}')
    if s.get("e2e"):
        metric(f'embedding_end_to_end_recall_at_{s["k"]}',
               "Overlap of the engine's answer for a live-embedded question with the exact answer "
               "for the question's build-time vector.",
               s["e2e"])
    if "probed_at" in s:
        metric("embedding_probe_last_success_timestamp_seconds", "When the probe last finished.",
               f'{s["probed_at"]:.0f}')
    return "\n".join(lines) + "\n"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/metrics"):
            body = render().encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
        else:
            body = b"ok\n"
            self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


if __name__ == "__main__":
    host, _, port = ADDR.rpartition(":")
    threading.Thread(target=loop, daemon=True).start()
    print(f"embedding probe on {ADDR}, every {INTERVAL}s: {CANARY} passages, {QUESTIONS} questions", flush=True)
    HTTPServer((host, int(port)), Handler).serve_forever()
