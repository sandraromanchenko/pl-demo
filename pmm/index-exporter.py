"""Expose the search index status that $listSearchIndexes reports, for PMM.

mongot publishes its own per-index status (mongot_index_stats_indexStatusCode),
but that gauge tracks mongot's internal state machine and settles long before
mongod stops reporting PENDING/BUILDING: mongod discovers new indexes on a poll
and caches mongot's replies, so on a 50-document collection the internally
observable INITIAL_SYNC lasts a few seconds while $listSearchIndexes says
PENDING for ~20s and BUILDING for ~60s. Only mongod knows the status a user
sees, so poll it here and let PMM scrape the result.
"""

import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from pymongo import MongoClient
from pymongo.errors import PyMongoError

MONGO_URI = os.environ.get(
    "MONGO_URI", "mongodb://root:root@mongod:27017/?authSource=admin&directConnection=true"
)
MONGO_DB = os.environ.get("MONGO_DB", "boardgames")
MONGO_COLLECTION = os.environ.get("MONGO_COLLECTION", "games")
PORT = int(os.environ.get("EXPORTER_PORT", "9947"))
POLL_INTERVAL = float(os.environ.get("POLL_INTERVAL", "2"))

# Emit every status as an explicit 0/1 rather than only the active one. A series
# that disappears keeps its last value for PMM's staleness window, which would
# leave BUILDING reading 1 after the index is READY.
STATUSES = ("PENDING", "BUILDING", "READY", "STALE", "FAILED", "DELETING")

_lock = threading.Lock()
_state = {"indexes": [], "up": 0, "errors": 0, "scraped_at": 0.0, "error": ""}


def index_type(doc):
    # $listSearchIndexes reports no type field, so infer it from the definition:
    # a full-text index carries "mappings", a vector index carries "fields".
    definition = doc.get("latestDefinition") or {}
    if "mappings" in definition:
        return "search"
    if "fields" in definition:
        return "vectorSearch"
    return "unknown"


def poll(client):
    coll = client[MONGO_DB][MONGO_COLLECTION]
    indexes = [
        {
            "name": doc.get("name", ""),
            "type": index_type(doc),
            "status": (doc.get("status") or "").upper(),
            "queryable": 1 if doc.get("queryable") else 0,
        }
        for doc in coll.aggregate([{"$listSearchIndexes": {}}])
    ]
    with _lock:
        _state.update(indexes=indexes, up=1, scraped_at=time.time(), error="")


def poll_forever():
    # Before `make demo-mongod-search` mongod has no mongot wired and this
    # command fails outright; before `make demo-indexes` it returns nothing.
    # Both are expected demo states, so keep polling instead of exiting.
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    while True:
        try:
            poll(client)
        except (PyMongoError, OSError) as exc:
            with _lock:
                _state.update(
                    indexes=[], up=0, errors=_state["errors"] + 1, error=type(exc).__name__
                )
        time.sleep(POLL_INTERVAL)


def escape(value):
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "")


def render():
    with _lock:
        snapshot = dict(_state, indexes=list(_state["indexes"]))
    out = [
        "# HELP search_index_status Index status from $listSearchIndexes (1 for the active status).",
        "# TYPE search_index_status gauge",
    ]
    base = 'db="%s",collection="%s"' % (escape(MONGO_DB), escape(MONGO_COLLECTION))
    for index in snapshot["indexes"]:
        labels = '%s,index="%s",type="%s"' % (
            base,
            escape(index["name"]),
            escape(index["type"]),
        )
        # An unrecognised status still has to appear, or the stack silently
        # loses an index and the panel total stops matching reality.
        statuses = STATUSES
        if index["status"] and index["status"] not in STATUSES:
            statuses = STATUSES + (index["status"],)
        for status in statuses:
            out.append(
                'search_index_status{%s,status="%s"} %d'
                % (labels, status, 1 if status == index["status"] else 0)
            )
    out += [
        "# HELP search_index_queryable Whether $listSearchIndexes reports the index as queryable.",
        "# TYPE search_index_queryable gauge",
    ]
    for index in snapshot["indexes"]:
        out.append(
            'search_index_queryable{%s,index="%s",type="%s"} %d'
            % (base, escape(index["name"]), escape(index["type"]), index["queryable"])
        )
    out += [
        "# HELP search_index_exporter_up Whether the last $listSearchIndexes call succeeded.",
        "# TYPE search_index_exporter_up gauge",
        "search_index_exporter_up %d" % snapshot["up"],
        "# HELP search_index_exporter_errors_total Failed $listSearchIndexes calls.",
        "# TYPE search_index_exporter_errors_total counter",
        "search_index_exporter_errors_total %d" % snapshot["errors"],
        "# HELP search_index_exporter_last_scrape_timestamp_seconds Last successful poll.",
        "# TYPE search_index_exporter_last_scrape_timestamp_seconds gauge",
        "search_index_exporter_last_scrape_timestamp_seconds %.3f" % snapshot["scraped_at"],
    ]
    return "\n".join(out) + "\n"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        if self.path.split("?")[0] not in ("/metrics", "/"):
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = render().encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    threading.Thread(target=poll_forever, daemon=True).start()
    print("search index exporter listening on :%d" % PORT, flush=True)
    ThreadingHTTPServer(("", PORT), Handler).serve_forever()
