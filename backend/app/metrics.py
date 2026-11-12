"""Request metrics for the search API, in Prometheus text format. No dependencies.

Rate, errors and duration of /search, split by engine and search type, so a normal dashboard
can show what the application itself sees. A request that returns ten wrong games is a success
here, which is the point.
"""
import threading
import time

BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)

_lock = threading.Lock()
_started = time.time()
_requests: dict[tuple, int] = {}
_duration_sum: dict[tuple, float] = {}
_buckets: dict[tuple, list[int]] = {}
_inflight = 0
_embeddings = {"ok": 0, "error": 0}


def start() -> float:
    global _inflight
    with _lock:
        _inflight += 1
    return time.perf_counter()


def finish(t0: float, engine: str, type_: str, status: int) -> None:
    global _inflight
    elapsed = time.perf_counter() - t0
    code = "5xx" if status >= 500 else "4xx" if status >= 400 else "2xx"
    key = (engine, type_, code)
    with _lock:
        _inflight -= 1
        _requests[key] = _requests.get(key, 0) + 1
        _duration_sum[key] = _duration_sum.get(key, 0.0) + elapsed
        counts = _buckets.setdefault(key, [0] * (len(BUCKETS) + 1))
        for i, bound in enumerate(BUCKETS):
            if elapsed <= bound:
                counts[i] += 1
        counts[-1] += 1


def embedding_done(ok: bool) -> None:
    """One call from the app to the embedding model (one per search)."""
    with _lock:
        _embeddings["ok" if ok else "error"] += 1


def render() -> str:
    out = []
    with _lock:
        out += ["# HELP app_uptime_seconds Time since the API started.",
                "# TYPE app_uptime_seconds gauge",
                f"app_uptime_seconds {time.time() - _started:.0f}",
                "# HELP app_search_requests_in_flight Searches running now.",
                "# TYPE app_search_requests_in_flight gauge",
                f"app_search_requests_in_flight {_inflight}",
                "# HELP app_search_requests_total Searches by engine, type and status class.",
                "# TYPE app_search_requests_total counter"]
        for (engine, type_, code), n in sorted(_requests.items()):
            out.append(f'app_search_requests_total{{engine="{engine}",type="{type_}",code="{code}"}} {n}')
        out += ["# HELP app_embedding_requests_total Calls from the app to the embedding model, by result.",
                "# TYPE app_embedding_requests_total counter"]
        for result, n in _embeddings.items():
            out.append(f'app_embedding_requests_total{{result="{result}"}} {n}')
        out += ["# HELP app_search_duration_seconds Time to answer a search.",
                "# TYPE app_search_duration_seconds histogram"]
        for key, counts in sorted(_buckets.items()):
            engine, type_, code = key
            lab = f'engine="{engine}",type="{type_}",code="{code}"'
            for bound, n in zip(BUCKETS, counts):
                out.append(f'app_search_duration_seconds_bucket{{{lab},le="{bound}"}} {n}')
            out.append(f'app_search_duration_seconds_bucket{{{lab},le="+Inf"}} {counts[-1]}')
            out.append(f'app_search_duration_seconds_sum{{{lab}}} {_duration_sum[key]:.6f}')
            out.append(f'app_search_duration_seconds_count{{{lab}}} {counts[-1]}')
    return "\n".join(out) + "\n"
