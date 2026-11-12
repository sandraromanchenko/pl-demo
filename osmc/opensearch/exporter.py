#!/usr/bin/env python3
"""Prometheus exporter for the OpenSearch alternative.

Publishes what a normal dashboard would show (cluster health, latency, doc
counts) next to the one number that moves when deletes pile up: recall@k
against an exact scan of the live documents.

Metric names are prefixed opensearch_ on purpose, so they never collide with
the mongot probe's vector_search_recall_at_10.
"""

import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import os_lab

ADDR = os.environ.get("EXPORTER_ADDR", ":9951")
INTERVAL = float(os.environ.get("PROBE_INTERVAL", "10"))
SAMPLE = int(os.environ.get("PROBE_SAMPLE", "200"))

lock = threading.Lock()
snapshot = {}


def rebuilding():
    settings = os_lab.call("GET", f"/{os_lab.INDEX}/_settings/index.refresh_interval", ok404=True, timeout=10) or {}
    refresh = next(iter(settings.values()), {}).get("settings", {}).get("index", {}).get("refresh_interval")
    tasks = os_lab.call("GET", "/_tasks?actions=*forcemerge*", timeout=10) or {}
    merging = any(node.get("tasks") for node in tasks.get("nodes", {}).values())
    return refresh == "-1" or merging


def collect():
    out = {"up": 0, "present": 0}
    try:
        health = os_lab.call("GET", "/_cluster/health", timeout=10)
    except (SystemExit, Exception):
        return out
    out["up"] = 1
    out["color"] = health.get("status", "red")
    try:
        knn = os_lab.call("GET", "/_plugins/_knn/stats/graph_memory_usage", timeout=10)
        out["graph_bytes"] = sum(int(n.get("graph_memory_usage", 0)) for n in knn.get("nodes", {}).values()) * 1024
    except (SystemExit, Exception):
        pass
    if os_lab.call("GET", f"/{os_lab.INDEX}/_count", ok404=True, timeout=10) is None:
        return out
    # `os_lab load` rebuilds the index: refresh off while loading, then the first refresh builds
    # the graph (live docs stay 0 for ~half a minute), then a force merge. A probe in any of
    # those phases reports a recall of 0, which is the reload, not the engine. Say nothing then;
    # the last value stays.
    if rebuilding():
        out["loading"] = 1
        return out
    rows = os_lab.segments()
    out["present"] = 1
    out["live"] = sum(int(r["docs.count"]) for r in rows)
    # Soft-delete tombstones live in segments that hold no live documents and
    # never go away; only deleted documents inside searchable segments are graph waste.
    out["deleted"] = sum(int(r["docs.deleted"]) for r in rows if int(r["docs.count"]) > 0)
    out["segments"] = len(rows)
    if out["live"] == 0:
        out["loading"] = 1
        return out
    try:
        golden = os_lab.load_golden()
        probe = os_lab.measure(golden, sample=SAMPLE)
        out.update(
            recall=probe["recall"], hits=probe["hits"], latency=probe["latency"],
            latency_p99=probe["latency_p99"], k=probe["k"]
        )
        out["probed_at"] = time.time()
        if rebuilding():  # the index was rebuilt while we were probing: drop this result
            for key in ("recall", "hits", "latency", "latency_p99", "k", "probed_at"):
                out.pop(key, None)
            out["loading"] = 1
    except (SystemExit, Exception) as exc:  # keep serving health even if the probe fails
        print(f"probe failed: {exc}", flush=True)
    return out


def loop():
    last = {}
    while True:
        cur = collect()
        # Keep the previous recall if this probe failed; staleness shows in the timestamp.
        for key in ("recall", "hits", "latency", "latency_p99", "k", "probed_at"):
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

    def metric(name, help_text, value, labels="", kind="gauge"):
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} {kind}")
        lines.append(f"{name}{labels} {value}")

    metric("opensearch_up", "1 if the cluster answers.", s.get("up", 0))
    if s.get("up"):
        lines.append("# HELP opensearch_cluster_status Cluster health colour, 1 for the current one.")
        lines.append("# TYPE opensearch_cluster_status gauge")
        for color in ("green", "yellow", "red"):
            lines.append(
                f'opensearch_cluster_status{{color="{color}"}} {1 if s.get("color") == color else 0}'
            )
    if "graph_bytes" in s:
        metric(
            "opensearch_knn_graph_memory_bytes",
            "Memory the k-NN plugin holds for the HNSW graphs (off-heap).",
            s["graph_bytes"],
        )
    metric("opensearch_index_present", "1 if the demo index exists.", s.get("present", 0))
    if s.get("present"):
        lines.append("# HELP opensearch_index_docs Documents in the demo index.")
        lines.append("# TYPE opensearch_index_docs gauge")
        lines.append(f'opensearch_index_docs{{state="live"}} {s["live"]}')
        lines.append(f'opensearch_index_docs{{state="deleted"}} {s["deleted"]}')
        total = s["live"] + s["deleted"]
        metric(
            "opensearch_index_deleted_ratio",
            "Deleted documents still in segments, as a fraction of all documents.",
            f'{(s["deleted"] / total) if total else 0:.6f}',
        )
        metric("opensearch_index_segments", "Segments in the demo index.", s["segments"])
    if "recall" in s:
        k = s["k"]
        metric(
            f"opensearch_vector_search_recall_at_{k}",
            "Overlap of the HNSW top-k with an exact scan of the live documents.",
            f'{s["recall"]:.6f}',
        )
        metric(
            "opensearch_vector_search_hits_returned",
            "Average number of hits the HNSW search returns per query.",
            f'{s["hits"]:.4f}',
        )
        metric(
            "opensearch_vector_search_latency_seconds",
            "Average latency of one k-NN query during the probe.",
            f'{s["latency"]:.6f}',
        )
        metric(
            "opensearch_vector_search_latency_p99_seconds",
            "99th percentile latency of the k-NN queries in the last probe.",
            f'{s["latency_p99"]:.6f}',
        )
        metric(
            "opensearch_probe_last_success_timestamp_seconds",
            "When the recall probe last finished.",
            f'{s["probed_at"]:.0f}',
        )
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
    print(f"opensearch exporter on {ADDR}, probing every {INTERVAL}s with {SAMPLE} queries", flush=True)
    HTTPServer((host, int(port)), Handler).serve_forever()
