#!/usr/bin/env python3
"""Recall@k and latency at several numCandidates values, against the live index.

Uses the golden queries directly, so the running recall service is not touched.
"""

import json
import os
import statistics
import time

from pymongo import MongoClient

URI = os.environ.get(
    "MONGO_URI",
    "mongodb://root:root@mongod:27017/?authSource=admin&directConnection=true",
)
GOLDEN = os.environ.get("GOLDEN_PATH", "/golden/golden.json")
LADDER = [int(x) for x in os.environ.get("LADDER", "16,50,100,200,400,1000").split(",")]
SAMPLE = int(os.environ.get("SAMPLE", "200"))

with open(GOLDEN, encoding="utf-8") as fh:
    g = json.load(fh)
coll = MongoClient(URI)[g["db"]][g["collection"]]
k = g["k"]
queries = g["queries"][:SAMPLE]

print(f"index {g['index']}, k={k}, {len(queries)} queries")
print(f"{'numCandidates':>14} {'recall@k':>9} {'ms/query':>9}")
for nc in LADDER:
    scores = []
    times = []
    for q in queries:
        t0 = time.time()
        rows = list(
            coll.aggregate(
                [
                    {
                        "$vectorSearch": {
                            "index": g["index"],
                            "path": "embedding",
                            "queryVector": q["vector"],
                            "numCandidates": nc,
                            "limit": k,
                        }
                    },
                    {"$project": {"_id": 1}},
                ]
            )
        )
        times.append((time.time() - t0) * 1000)
        got = {r["_id"] for r in rows}
        scores.append(len(got & set(q["neighbors"])) / k)
    print(f"{nc:>14} {statistics.mean(scores):>9.3f} {statistics.mean(times):>9.1f}")
