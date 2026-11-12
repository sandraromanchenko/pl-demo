#!/usr/bin/env python3
"""Prometheus exporter for everything a normal monitoring setup watches, except recall.

The recall probes answer "are the results right?". This one answers the questions an on-call
person asks first: is every service up, is the hardware fine, is the embedding model answering,
are there errors, is anything slow?

  osmc_service_up / osmc_service_probe_seconds{service}
      One HTTP or TCP check per service: mongod, mongot, OpenSearch, Ollama, backend, frontend.

  osmc_container_*{service}
      State, restarts, uptime, CPU, memory, network and disk of every container in the stack.
      Read from the Docker API (the socket is mounted read-only).

  ollama_* and embedding_service_* / embedding_requests_total
      The embedding model: is it loaded, does it answer, how long does an embedding take, does the
      answer have the size the index expects. It says nothing about whether the vectors are the
      right ones. That is the recall probe's job.

  opensearch_* (node stats)
      JVM heap and GC, CPU, disk, thread pools and rejections, circuit breakers, k-NN graph memory,
      search rate, latency and failures, shards.

Standard library only. Anything that is down only drops its own series.
"""

import http.client
import json
import os
import socket
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, HTTPServer

ADDR = os.environ.get("EXPORTER_ADDR", ":9953")
INTERVAL = float(os.environ.get("PROBE_INTERVAL", "10"))
OPENSEARCH = os.environ.get("OPENSEARCH_URL", "http://opensearch:9200").rstrip("/")
OLLAMA = os.environ.get("OLLAMA_URL", "http://ollama:11434").rstrip("/")
BACKEND = os.environ.get("BACKEND_URL", "http://backend:8000").rstrip("/")
FRONTEND = os.environ.get("FRONTEND_URL", "http://frontend:80").rstrip("/")
MONGOT_HEALTH = os.environ.get("MONGOT_HEALTH_URL", "http://mongot:8080/health")
MONGOD = os.environ.get("MONGOD_ADDR", "mongod:27017")
DOCKER_SOCK = os.environ.get("DOCKER_SOCK", "/var/run/docker.sock")
PROJECT = os.environ.get("COMPOSE_PROJECT", "pl-demo")
QUERY_MODEL_FILE = os.environ.get("QUERY_MODEL_FILE", "/golden/query_model")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "bge-small")
# Services that are allowed to be stopped (the optional assistant). They are left out until they run.
OPTIONAL = set(filter(None, os.environ.get("OPTIONAL_SERVICES", "vllm").split(",")))
INDEX_DIMENSIONS = int(os.environ.get("INDEX_DIMENSIONS", "384"))

lock = threading.Lock()
snapshot = {}
counters = {"embed_ok": 0, "embed_error": 0}


# ---------------------------------------------------------------------------- helpers

def http_json(url, body=None, timeout=5):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def timed(fn):
    started = time.perf_counter()
    try:
        fn()
        return 1, time.perf_counter() - started
    except Exception:
        return 0, time.perf_counter() - started


def probe_http(url):
    def go():
        with urllib.request.urlopen(url, timeout=5) as resp:
            if resp.status >= 400:
                raise RuntimeError(resp.status)
    return timed(go)


def probe_tcp(addr):
    host, _, port = addr.rpartition(":")

    def go():
        with socket.create_connection((host, int(port)), timeout=5):
            pass
    return timed(go)


class DockerSocket(http.client.HTTPConnection):
    def __init__(self):
        super().__init__("localhost", timeout=20)

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(20)
        self.sock.connect(DOCKER_SOCK)


def docker_get(path):
    conn = DockerSocket()
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read()
        if resp.status >= 400:
            raise RuntimeError(f"docker {resp.status}")
        return json.loads(body)
    finally:
        conn.close()


def live_model():
    try:
        with open(QUERY_MODEL_FILE, encoding="utf-8") as fh:
            name = fh.read().strip()
            if name:
                return name
    except OSError:
        pass
    return EMBED_MODEL


# ---------------------------------------------------------------------------- collectors

def collect_services():
    checks = {
        "mongod": lambda: probe_tcp(MONGOD),
        "mongot": lambda: probe_http(MONGOT_HEALTH),
        "opensearch": lambda: probe_http(OPENSEARCH + "/_cluster/health"),
        "ollama": lambda: probe_http(OLLAMA + "/api/tags"),
        "backend": lambda: probe_http(BACKEND + "/health"),
        "frontend": lambda: probe_http(FRONTEND + "/"),
    }
    with ThreadPoolExecutor(max_workers=len(checks)) as pool:
        futures = {name: pool.submit(fn) for name, fn in checks.items()}
        return {name: f.result() for name, f in futures.items()}


def collect_ollama():
    out = {}
    model = live_model()
    out["model"] = model
    try:
        tags = http_json(OLLAMA + "/api/tags")
        out["available"] = len(tags.get("models", []))
        ps = http_json(OLLAMA + "/api/ps")
        out["loaded"] = {
            m.get("name", "?"): {"size": m.get("size", 0), "vram": m.get("size_vram", 0)}
            for m in ps.get("models", [])
        }
    except Exception:
        out["available"] = None
    # One real embedding, the way the application asks for it.
    started = time.perf_counter()
    try:
        res = http_json(OLLAMA + "/api/embed", {"model": model, "input": "health check"}, timeout=30)
        out["embed_seconds"] = time.perf_counter() - started
        out["dimensions"] = len(res["embeddings"][0])
        out["embed_ok"] = 1
        counters["embed_ok"] += 1
    except Exception:
        out["embed_seconds"] = time.perf_counter() - started
        out["embed_ok"] = 0
        counters["embed_error"] += 1
    return out


def collect_opensearch():
    out = {}
    try:
        health = http_json(OPENSEARCH + "/_cluster/health", timeout=10)
        out["health"] = health
        node = next(iter(http_json(
            OPENSEARCH + "/_nodes/stats/jvm,process,os,fs,thread_pool,indices,breaker,http",
            timeout=10)["nodes"].values()))
        out["node"] = node
    except Exception:
        return out
    try:
        out["knn"] = next(iter(http_json(OPENSEARCH + "/_plugins/_knn/stats", timeout=10)["nodes"].values()))
        out["knn_cluster"] = http_json(OPENSEARCH + "/_plugins/_knn/stats", timeout=10)
    except Exception:
        pass
    return out


def container_stats(container):
    cid = container["Id"]
    try:
        info = docker_get(f"/containers/{cid}/json")
        stats = docker_get(f"/containers/{cid}/stats?stream=false")
    except Exception:
        return None
    labels = container.get("Labels", {})
    service = labels.get("com.docker.compose.service", container["Names"][0].lstrip("/"))
    state = info.get("State", {})
    started = state.get("StartedAt", "")
    uptime = 0.0
    if state.get("Running") and started and not started.startswith("0001"):
        try:
            import datetime
            ts = datetime.datetime.strptime(started[:19], "%Y-%m-%dT%H:%M:%S").replace(
                tzinfo=datetime.timezone.utc)
            uptime = max(0.0, time.time() - ts.timestamp())
        except ValueError:
            pass
    cpu = stats.get("cpu_stats", {})
    pre = stats.get("precpu_stats", {})
    cpu_delta = cpu.get("cpu_usage", {}).get("total_usage", 0) - pre.get("cpu_usage", {}).get("total_usage", 0)
    sys_delta = cpu.get("system_cpu_usage", 0) - pre.get("system_cpu_usage", 0)
    cpus = cpu.get("online_cpus") or len(cpu.get("cpu_usage", {}).get("percpu_usage", []) or []) or 1
    cpu_percent = (cpu_delta / sys_delta * cpus * 100.0) if sys_delta > 0 and cpu_delta >= 0 else 0.0
    mem = stats.get("memory_stats", {})
    mem_stats = mem.get("stats", {})
    # Same figure `docker stats` prints: usage without the page cache that can be given back.
    mem_used = mem.get("usage", 0) - mem_stats.get("inactive_file", mem_stats.get("total_inactive_file", 0))
    nets = stats.get("networks", {}) or {}
    blk = (stats.get("blkio_stats", {}) or {}).get("io_service_bytes_recursive") or []
    return {
        "service": service,
        "running": 1 if state.get("Running") else 0,
        "restarts": info.get("RestartCount", 0),
        "uptime": uptime,
        "oom": 1 if state.get("OOMKilled") else 0,
        "cpu_percent": max(cpu_percent, 0.0),
        "mem_used": max(mem_used, 0),
        "mem_limit": mem.get("limit", 0),
        "rx": sum(n.get("rx_bytes", 0) for n in nets.values()),
        "tx": sum(n.get("tx_bytes", 0) for n in nets.values()),
        "blk_read": sum(b.get("value", 0) for b in blk if str(b.get("op", "")).lower() == "read"),
        "blk_write": sum(b.get("value", 0) for b in blk if str(b.get("op", "")).lower() == "write"),
    }


def collect_containers():
    try:
        containers = docker_get(
            "/containers/json?all=1&filters="
            + urllib.request.quote(json.dumps({"label": [f"com.docker.compose.project={PROJECT}"]})))
    except Exception:
        return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = [r for r in pool.map(container_stats, containers) if r]
    return [r for r in rows if r["running"] or r["service"] not in OPTIONAL]


def collect():
    out = {"at": time.time()}
    out["services"] = collect_services()
    out["ollama"] = collect_ollama()
    out["opensearch"] = collect_opensearch()
    out["containers"] = collect_containers()
    return out


def loop():
    while True:
        try:
            cur = collect()
        except Exception as exc:  # never die: a broken probe must not hide the others
            print(f"collect failed: {str(exc)[:300]}", flush=True)
            time.sleep(INTERVAL)
            continue
        with lock:
            snapshot.clear()
            snapshot.update(cur)
        time.sleep(INTERVAL)


# ---------------------------------------------------------------------------- rendering

def render():
    with lock:
        s = dict(snapshot)
        c = dict(counters)
    families = {}  # one block per metric name: the text format wants a family's samples together

    def metric(name, help_text, value, labels=None, kind="gauge"):
        if name not in families:
            families[name] = [f"# HELP {name} {help_text}", f"# TYPE {name} {kind}"]
        label = ""
        if labels:
            label = "{" + ",".join(f'{k}="{v}"' for k, v in labels.items()) + "}"
        families[name].append(f"{name}{label} {value}")

    if not s:
        return "# no data yet\n"

    for name, (up, seconds) in sorted(s["services"].items()):
        metric("osmc_service_up", "1 if the service answers its health check.", up, {"service": name})
        metric("osmc_service_probe_seconds", "Time the health check took.", f"{seconds:.6f}",
               {"service": name})

    o = s["ollama"]
    metric("embedding_service_up", "1 if the embedding model answered the last request.", o["embed_ok"])
    metric("embedding_service_request_seconds", "Time the last embedding request took.",
           f'{o["embed_seconds"]:.6f}')
    metric("embedding_requests_total", "Embedding health requests by result.", c["embed_ok"],
           {"result": "ok"}, "counter")
    metric("embedding_requests_total", "Embedding health requests by result.", c["embed_error"],
           {"result": "error"}, "counter")
    if "dimensions" in o:
        metric("embedding_service_dimensions", "Size of the vector the model returned.", o["dimensions"])
        metric("embedding_service_dimensions_expected", "Size of the vectors in the index.", INDEX_DIMENSIONS)
    metric("embedding_service_model_info", "Model the application asks for.", 1, {"model": o["model"]})
    if o.get("available") is not None:
        metric("ollama_models_available", "Models Ollama has on disk.", o["available"])
        metric("ollama_models_loaded", "Models Ollama holds in memory.", len(o["loaded"]))
        for name, m in o["loaded"].items():
            metric("ollama_model_loaded_bytes", "Memory a loaded model uses.", m["size"], {"model": name})
        metric("ollama_live_model_loaded", "1 if the model the application asks for is in memory.",
               1 if any(n.split(":")[0] == o["model"].split(":")[0] for n in o["loaded"]) else 0)

    os_ = s["opensearch"]
    if os_.get("node"):
        h, n = os_["health"], os_["node"]
        metric("opensearch_cluster_nodes", "Nodes in the cluster.", h["number_of_nodes"])
        metric("opensearch_cluster_data_nodes", "Data nodes in the cluster.", h["number_of_data_nodes"])
        for state, key in (("active", "active_shards"), ("unassigned", "unassigned_shards"),
                           ("initializing", "initializing_shards"), ("relocating", "relocating_shards")):
            metric("opensearch_shards", "Shards by state.", h[key], {"state": state})
        metric("opensearch_pending_tasks", "Cluster tasks waiting.", h["number_of_pending_tasks"])
        jvm = n["jvm"]
        metric("opensearch_jvm_heap_used_bytes", "JVM heap in use.", jvm["mem"]["heap_used_in_bytes"])
        metric("opensearch_jvm_heap_max_bytes", "JVM heap limit.", jvm["mem"]["heap_max_in_bytes"])
        for gen, gc in jvm["gc"]["collectors"].items():
            metric("opensearch_jvm_gc_collections_total", "GC runs.", gc["collection_count"],
                   {"collector": gen}, "counter")
            metric("opensearch_jvm_gc_seconds_total", "Time spent in GC.",
                   f'{gc["collection_time_in_millis"] / 1000:.3f}', {"collector": gen}, "counter")
        metric("opensearch_process_cpu_percent", "CPU used by the OpenSearch process.",
               n["process"]["cpu"]["percent"])
        metric("opensearch_process_open_files", "Open file descriptors.", n["process"]["open_file_descriptors"])
        metric("opensearch_process_max_files", "File descriptor limit.", n["process"]["max_file_descriptors"])
        metric("opensearch_fs_total_bytes", "Disk size under the data path.", n["fs"]["total"]["total_in_bytes"])
        metric("opensearch_fs_available_bytes", "Disk space left under the data path.",
               n["fs"]["total"]["available_in_bytes"])
        for pool in ("search", "write", "get"):
            tp = n["thread_pool"].get(pool)
            if tp:
                metric("opensearch_thread_pool_queue", "Tasks waiting in the pool.", tp["queue"], {"pool": pool})
                metric("opensearch_thread_pool_active", "Tasks running in the pool.", tp["active"], {"pool": pool})
                metric("opensearch_thread_pool_rejected_total", "Tasks the pool turned away.",
                       tp["rejected"], {"pool": pool}, "counter")
        search = n["indices"]["search"]
        metric("opensearch_search_query_total", "Search queries served.", search["query_total"], kind="counter")
        metric("opensearch_search_query_seconds_total", "Time spent in search queries.",
               f'{search["query_time_in_millis"] / 1000:.3f}', kind="counter")
        metric("opensearch_search_query_current", "Search queries running now.", search["query_current"])
        metric("opensearch_search_query_failed_total", "Search queries that failed.",
               search.get("query_failed", 0), kind="counter")
        indexing = n["indices"]["indexing"]
        metric("opensearch_indexing_index_total", "Documents indexed.", indexing["index_total"], kind="counter")
        metric("opensearch_indexing_index_failed_total", "Document index requests that failed.",
               indexing.get("index_failed", 0), kind="counter")
        for name, br in n["breakers"].items():
            metric("opensearch_breaker_tripped_total", "Requests a memory breaker turned away.",
                   br["tripped"], {"breaker": name}, "counter")
        metric("opensearch_http_open_connections", "Open client connections.", n["http"]["current_open"])
    knn = os_.get("knn")
    if knn:
        metric("opensearch_knn_graph_memory_bytes", "Memory the k-NN graphs use.",
               knn.get("graph_memory_usage", 0) * 1024)
        metric("opensearch_knn_graph_memory_percent", "Share of the k-NN graph memory limit in use.",
               f'{knn.get("graph_memory_usage_percentage", 0) / 100:.6f}')
        metric("opensearch_knn_cache_hits_total", "Graph cache hits.", knn.get("hit_count", 0), kind="counter")
        metric("opensearch_knn_cache_misses_total", "Graph cache misses.", knn.get("miss_count", 0), kind="counter")
        metric("opensearch_knn_graph_query_errors_total", "k-NN graph query errors.",
               knn.get("graph_query_errors", 0), kind="counter")
        metric("opensearch_knn_graph_query_requests_total", "k-NN graph queries.",
               knn.get("graph_query_requests", 0), kind="counter")
        metric("opensearch_knn_load_exceptions_total", "Graph loads that failed.",
               knn.get("load_exception_count", 0), kind="counter")
        metric("opensearch_knn_evictions_total", "Graphs evicted from the cache.",
               knn.get("eviction_count", 0), kind="counter")
        metric("opensearch_knn_circuit_breaker_triggered", "1 if the k-NN memory breaker is open.",
               1 if os_.get("knn_cluster", {}).get("circuit_breaker_triggered") else 0)

    for r in s.get("containers") or []:
        lab = {"service": r["service"]}
        metric("osmc_container_up", "1 if the container is running.", r["running"], lab)
        metric("osmc_container_restarts", "Times Docker restarted the container.", r["restarts"], lab)
        metric("osmc_container_oom_killed", "1 if the kernel killed the container for memory.", r["oom"], lab)
        metric("osmc_container_uptime_seconds", "Time since the container started.", f'{r["uptime"]:.0f}', lab)
        metric("osmc_container_cpu_percent", "CPU in percent of one core.", f'{r["cpu_percent"]:.2f}', lab)
        metric("osmc_container_memory_bytes", "Memory in use, without reclaimable cache.", r["mem_used"], lab)
        metric("osmc_container_memory_limit_bytes", "Memory limit (host memory if none is set).",
               r["mem_limit"], lab)
        metric("osmc_container_network_receive_bytes_total", "Bytes received.", r["rx"], lab, "counter")
        metric("osmc_container_network_transmit_bytes_total", "Bytes sent.", r["tx"], lab, "counter")
        metric("osmc_container_disk_read_bytes_total", "Bytes read from disk.", r["blk_read"], lab, "counter")
        metric("osmc_container_disk_write_bytes_total", "Bytes written to disk.", r["blk_write"], lab, "counter")

    metric("osmc_health_last_success_timestamp_seconds", "When the health exporter last finished.",
           f'{s["at"]:.0f}')
    return "\n".join(line for block in families.values() for line in block) + "\n"


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
    print(f"health exporter on {ADDR}, every {INTERVAL}s", flush=True)
    HTTPServer((host, int(port)), Handler).serve_forever()
