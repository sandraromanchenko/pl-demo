"""The talk's two dashboards. Same top half; the second adds recall.

  osmc-basic         The most important things to watch without recall: is everything up, are
                     the indexes ready, are there errors, is anything slow, is there room left.
  osmc-side-by-side  The same, plus recall@10 and the two reasons it can drop.

The first one stays green through both failures in the talk (model swap, deleted documents).
Metrics come from PMM's own exporters (host, MongoDB), mongot, and the demo's exporters:
osmc-health (services, containers, Ollama, OpenSearch node stats), osmc-app (the search API),
osmc-opensearch and osmc-embedding (cluster and recall).
"""
from render_dashboards import (
    DS, MONGOT_LATENCY, cosine_thresholds, green_red, hits_thresholds, match_map,
    not_green_map, ratio_thresholds, ready_map, recall_thresholds, stat, timeseries, ts_min,
    up_map, value_map, write,
)

HOST = 'node_name="pmm-client"'
DISK = f'{HOST},fstype=~"ext4|xfs|btrfs"'
RATE = "$__rate_interval"

TAG = "osmc-health"

# ----------------------------------------------------------------------------
# Thresholds and value maps
# ----------------------------------------------------------------------------


def climb(yellow, red):
    """Green at the bottom, then yellow, then red."""
    return {"mode": "absolute", "steps": [
        {"color": "green"}, {"color": "yellow", "value": yellow}, {"color": "red", "value": red}]}


def zero_ok(red=1):
    """0 is fine. Anything from `red` up is not."""
    return {"mode": "absolute", "steps": [{"color": "green"}, {"color": "red", "value": red}]}


PCT = climb(75, 90)
LATENCY = climb(0.05, 0.25)
SLOW_EMBED = climb(0.5, 2)
LAG = climb(5000, 30000)
running_map = value_map(**{"0": ("red", "DOWN"), "1": ("green", "RUNNING")})
loaded_map = value_map(**{"0": ("red", "NOT LOADED"), "1": ("green", "LOADED")})
serving_map = value_map(**{"0": ("red", "NOT SERVING"), "1": ("green", "SERVING")})
ERR = dict(decimals=0, thresholds=zero_ok())

# ----------------------------------------------------------------------------
# Expressions used on more than one dashboard
# ----------------------------------------------------------------------------

E = {
    # services
    "psmdb_up": "max(mongodb_up)",
    "mongot_up": 'min(osmc_service_up{service="mongot"})',
    "mongot_ready": "max(mongot_readiness_lifecycleInitialized)",
    "os_up": 'min(osmc_service_up{service="opensearch"})',
    "ollama_up": 'min(osmc_service_up{service="ollama"})',
    "embed_up": "max(embedding_service_up)",
    "api_up": 'min(osmc_service_up{service="backend"})',
    "web_up": 'min(osmc_service_up{service="frontend"})',
    # max: a second index is built next to the first during a migration (quantization); one READY index is enough.
    "index_ready": 'max(search_index_status{status="READY",collection="catalog"})',
    "mongot_index_mem": "sum(mongot_index_stats_requiredMemoryBytes)",
    "os_index_mem": "max(opensearch_knn_graph_memory_bytes)",
    "os_green": 'max(opensearch_cluster_status{color="green"})',
    # latency
    "mongot_p99": 'max(mongot_command_vectorSearchCommandTotalLatency_seconds{quantile="0.99"})',
    "mongot_p50": 'max(mongot_command_vectorSearchCommandTotalLatency_seconds{quantile="0.5"})',
    "os_latency": "max(opensearch_vector_search_latency_p99_seconds)",
    "embed_latency": "max(embedding_service_request_seconds)",
    "lag": "max(mongot_index_stats_indexing_replicationLagMs)",
    # errors, per minute
    "mongot_failed": "sum(increase(mongot_command_vectorSearchCommandFailure_total[1m])) + sum(increase(mongot_command_searchCommandFailure_total[1m]))",
    "mongot_rejected": "sum(increase(mongot_rejectedConcurrentSearchExecutionCount_total[1m]))",
    "psmdb_asserts": 'sum(increase(mongodb_ss_asserts{assert_type=~"regular|rollovers"}[1m]))',
    "os_failed": "sum(increase(opensearch_search_query_failed_total[1m])) + sum(increase(opensearch_knn_graph_query_errors_total[1m])) + sum(increase(opensearch_thread_pool_rejected_total[1m]))",
    "embed_errors": 'sum(increase(embedding_requests_total{result="error"}[1m]))',
    "api_5xx": 'sum(increase(app_search_requests_total{code="5xx"}[1m])) or vector(0)',
    "psmdb_read": f'sum(rate(mongodb_ss_opLatencies_latency{{op_type="reads"}}[{RATE}])) / clamp_min(sum(rate(mongodb_ss_opLatencies_ops{{op_type="reads"}}[{RATE}])), 1) / 1000000',
    # hardware
    "cpu": f'100 - avg(rate(node_cpu_seconds_total{{{HOST},mode="idle"}}[{RATE}])) * 100',
    "mem": f"100 * (1 - max(node_memory_MemAvailable_bytes{{{HOST}}}) / max(node_memory_MemTotal_bytes{{{HOST}}}))",
    "disk": f"100 * (1 - max(node_filesystem_avail_bytes{{{DISK}}}) / max(node_filesystem_size_bytes{{{DISK}}}))",
    "mongot_heap": '100 * sum(mongot_jvm_memory_used_bytes{area="heap"}) / sum(mongot_jvm_memory_max_bytes{area="heap"})',
    "os_heap": "100 * max(opensearch_jvm_heap_used_bytes) / max(opensearch_jvm_heap_max_bytes)",
}

# ----------------------------------------------------------------------------
# Layout: fills each row left to right and keeps ids and y positions
# ----------------------------------------------------------------------------


def widths(n):
    """Split the 24 columns of a row between n panels with no gap."""
    base, extra = divmod(24, n)
    return [base + (1 if i < extra else 0) for i in range(n)]


class Board:
    def __init__(self):
        self.panels = []
        self.y = 0
        self.pid = 0

    def _id(self):
        self.pid += 1
        return self.pid

    def row(self, title):
        self.panels.append({
            "collapsed": False, "gridPos": {"h": 1, "w": 24, "x": 0, "y": self.y},
            "id": self._id(), "panels": [], "title": title, "type": "row"})
        self.y += 1

    def stats(self, specs, h=4):
        """specs: (title, expr, options). Evenly spread across 24 columns."""
        x = 0
        for (title, expr, opts), w in zip(specs, widths(len(specs))):
            self.panels.append(stat(self._id(), title, expr, x, self.y, w=w, h=h, name_inside=True, **opts))
            x += w
        self.y += h

    def charts(self, specs, h=8, kind=ts_min):
        """specs: (title, [(expr, legend)], unit, description, options)."""
        x = 0
        for (title, targets, unit, desc, *rest), w in zip(specs, widths(len(specs))):
            opts = rest[0] if rest else {}
            self.panels.append(kind(self._id(), title, targets, x, self.y, w, h, unit, desc, **opts))
            x += w
        self.y += h

    def add_row_panels(self, panels):
        self.panels.extend(panels)


def links(current):
    return [{
        "asDropdown": False, "icon": "dashboard", "includeVars": False, "keepTime": True,
        "tags": [TAG], "targetBlank": False, "title": "Health dashboards", "tooltip": "",
        "type": "dashboards", "url": "",
    }]


def emit(filename, uid, title, board, extra_tags=()):
    write(filename, uid, title, board.panels, ["osmc", "vector-search", "demo", TAG, *extra_tags],
          links=links(uid), refresh="5s", time_from="now-30m")


# ----------------------------------------------------------------------------
# The top half, shared by both dashboards
# ----------------------------------------------------------------------------

def overview_rows(b):
    b.row("Services state")
    b.stats([
        ("PSMDB (mongod)", E["psmdb_up"], dict(mappings=up_map, thresholds=green_red,
         description="MongoDB exporter can talk to mongod.")),
        ("Percona Search (mongot)", E["mongot_up"], dict(mappings=up_map, thresholds=green_red,
         description="mongot answers its health endpoint.")),
        ("OpenSearch", E["os_up"], dict(mappings=up_map, thresholds=green_red)),
        ("Embedding model", E["embed_up"], dict(mappings=serving_map, thresholds=green_red,
         description="A real embedding request to Ollama every 10 seconds, with the model the "
                     "application uses. It says the model is serving. It does not say the vectors are right.")),
        ("Search app", E["api_up"], dict(mappings=up_map, thresholds=green_red,
         description="The backend the web page talks to. It turns the question into a vector "
                     "and asks mongot or OpenSearch.")),
    ])
    b.row("Indexes state")
    b.stats([
        ("Percona Search index", E["index_ready"], dict(mappings=ready_map, thresholds=green_red,
         description="Status mongod reports for the catalog vector index.")),
        ("Percona Search replication lag", E["lag"], dict(unit="ms", thresholds=LAG,
         description="How far mongot is behind MongoDB's change stream.")),
        ("OpenSearch index", E["os_green"], dict(mappings=ready_map, thresholds=green_red,
         description="READY when the OpenSearch cluster status is green.")),
    ])
    b.row("Errors (per minute)")
    b.charts([
        ("Percona Search errors", [(f'{E["mongot_failed"]} + {E["mongot_rejected"]}', "errors")],
         "short", "Failed or rejected searches in mongot.", ERR),
        ("PSMDB errors", [(E["psmdb_asserts"], "asserts")], "short", "MongoDB asserts. 0 is what you want.", ERR),
        ("OpenSearch errors", [(E["os_failed"], "errors")], "short",
         "Failed searches, k-NN graph errors and rejected tasks.", ERR),
        ("Embedding errors", [(E["embed_errors"], "errors")], "short",
         "Failed requests to the embedding model.", ERR),
        ("Search app 5xx", [(E["api_5xx"], "5xx")], "short",
         "A request that returns ten wrong games is a 200.", ERR),
    ], h=6, kind=timeseries)
    b.row("Latency")
    b.charts([
        ("Percona Search p99", [(E["mongot_p99"], "p99")], "s", "", dict(thresholds=LATENCY, decimals=3)),
        ("OpenSearch p99", [(E["os_latency"], "p99")], "s",
         "99 out of 100 k-NN searches are faster than this. Measured by the probe, which sends 500 searches every 10 seconds.",
         dict(thresholds=LATENCY, decimals=4)),
        ("Embedding request latency", [(E["embed_latency"], "request")], "s", "One embedding request to the model.",
         dict(thresholds=SLOW_EMBED, decimals=3)),
        ("PSMDB read latency", [(E["psmdb_read"], "reads")], "s", "", dict(thresholds=LATENCY, decimals=4)),
    ], h=6, kind=timeseries)
    b.row("Traffic")
    b.charts([
        ("Query throughput", [
            ("sum(rate(mongot_command_vectorSearchCommandTotalLatency_seconds_count[$__rate_interval]))", "Percona Search"),
            ("sum(rate(opensearch_search_query_total[$__rate_interval]))", "OpenSearch")], "reqps",
         "Searches per second that each engine answers. Includes the probe's own searches."),
        ("Embedding requests", [
            ('sum(increase(app_embedding_requests_total{result="ok"}[1m])) or vector(0)', "searches (ok)"),
            ('sum(increase(app_embedding_requests_total{result="error"}[1m])) or vector(0)', "searches (failed)"),
            ('sum(increase(embedding_requests_total{result="ok"}[1m]))', "health check (ok)"),
            ('sum(increase(embedding_requests_total{result="error"}[1m]))', "health check (failed)")], "short",
         "Calls to the embedding model per minute. Every search sends one (the app embeds the question). "
         "The health check sends one every 10 seconds, so the graph is never empty. "
         "Failed calls should stay at 0.", dict(decimals=0)),
    ], h=7, kind=timeseries)
    b.row("Resources")
    b.stats([
        ("Host CPU", E["cpu"], dict(unit="percent", thresholds=PCT, decimals=0, vmax=100)),
        ("Host memory used", E["mem"], dict(unit="percent", thresholds=PCT, decimals=0, vmax=100,
         description="Without the file cache that can be given back.")),
        ("Host disk used", E["disk"], dict(unit="percent", thresholds=PCT, decimals=0, vmax=100)),
        ("Percona Search JVM heap", E["mongot_heap"], dict(unit="percent", thresholds=PCT, decimals=0, vmax=100)),
        ("OpenSearch JVM heap", E["os_heap"], dict(unit="percent", thresholds=PCT, decimals=0, vmax=100)),
    ])
    b.charts([
        ("CPU by container", [("osmc_container_cpu_percent", "{{service}}")], "percent", "100 is one full core."),
        ("Memory by container", [("osmc_container_memory_bytes", "{{service}}")], "bytes",
         "Without file cache that can be given back."),
        ("Vector index memory", [(E["mongot_index_mem"], "Percona Search"), (E["os_index_mem"], "OpenSearch")], "bytes",
         "Memory each engine needs to keep the vector index searchable. Quantization stores the vectors "
         "with fewer bits, so this falls, and so does the number of neighbours the search finds. "
         "Percona Search: mongot's required memory. OpenSearch: k-NN graph memory."),
    ], h=8)


def overview():
    b = Board()
    overview_rows(b)
    emit("osmc-basic.json", "osmc-basic", "Vector search: key metrics", b)


# ----------------------------------------------------------------------------
# 6. With recall
# ----------------------------------------------------------------------------

def side_by_side():
    e2e_mongot = 'max(embedding_end_to_end_recall_at_10{engine="mongot"})'
    e2e_opensearch = 'max(embedding_end_to_end_recall_at_10{engine="opensearch"})'
    ann_mongot = "max(vector_search_recall_at_10)"
    ann_opensearch = "max(opensearch_vector_search_recall_at_10)"
    ann = ("ANN recall: the same saved question vector goes to the engine, and its top 10 is compared with "
           "an exact search of the live documents. It does not call the model. 1.00 means the engine "
           "returns what an exact search would. If it drops, look at the engine or the index.")
    vectors = ("Embedding check. The probe embeds the text of 5 saved games again with the live model and "
               "compares each new vector with the vector stored for that game. 1.00 means the same vector. "
               "A different model gives a much lower value. It does not call the engine.")
    results = ("Query check. Saved test questions are embedded now with the live model and searched in the "
               "engine. Their top 10 is compared with the top 10 for the vector the question had when the "
               "catalog was built. 1.00 means the same results. A different model drops it on both engines. "
               "If only one engine drops, that engine has a problem, for example deleted documents in OpenSearch.")
    BIG = {"calcs": ["lastNotNull"], "displayMode": "table", "placement": "right", "showLegend": True}
    b = Board()
    b.row("ANN recall@10")
    opts = dict(vmax=1, thresholds=recall_thresholds, decimals=2, legend=BIG, color_by_thresholds=True)
    ann = ("ANN recall: the same saved question vector goes to the engine, and its top 10 is compared with "
           "an exact search of the live documents. It does not call the model. 1.00 means the engine "
           "returns what an exact search would. If it drops, look at the engine or the index.")
    b.charts([
        ("Percona Search ANN recall@10", [(ann_mongot, "now")], "short", ann, opts),
        ("OpenSearch ANN recall@10", [(ann_opensearch, "now")], "short", ann, opts),
    ], h=8, kind=timeseries)
    b.row("Embedding drift")
    b.charts([
        ("Embedding check: vector similarity", [
            ("min(embedding_canary_cosine_min)", "lowest"),
            ("avg(embedding_canary_cosine_mean)", "average")],
         "short", vectors, dict(vmax=1, decimals=2, thresholds=cosine_thresholds, legend=BIG)),
        ("Query check: result overlap", [
            (e2e_mongot, "Percona Search"), (e2e_opensearch, "OpenSearch")],
         "short", results, dict(vmax=1, decimals=2, thresholds=recall_thresholds, legend=BIG)),
    ], h=9, kind=timeseries)
    overview_rows(b)
    emit("osmc-side-by-side.json", "osmc-side-by-side", "Vector search: key metrics + recall", b)


def write_all():
    overview()
    side_by_side()
