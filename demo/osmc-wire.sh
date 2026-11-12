#!/usr/bin/env bash
# Register mongot, the catalog index exporter, the recall gauge, the OpenSearch, embedding and
# health exporters, the search API, and vLLM with PMM. Safe to re-run: a name that is already registered is left alone.
# vLLM is only registered when that container is actually running.
set -euo pipefail

cd "$(dirname "$0")/.."

compose() {
  docker compose --profile data --profile app --profile osmc --profile osmc-rag --profile opensearch "$@"
}

add_external() {
  local name=$1 url=$2 out
  # `pmm-admin list` does not show external-serverless nodes, so try to add and
  # treat "already exists" as success.
  if out=$(compose exec -T pmm-client pmm-admin add external-serverless \
      --external-name="$name" \
      --group=vector-observability \
      --url="$url" \
      --skip-connection-check 2>&1); then
    echo "registered: $name -> $url"
  elif grep -q "already exists" <<<"$out"; then
    echo "already registered: $name"
  else
    echo "$out" >&2
    return 1
  fi
}

ready=0
for _ in $(seq 1 40); do
  if compose exec -T pmm-client pmm-admin status >/dev/null 2>&1; then
    ready=1
    break
  fi
  echo "waiting for pmm-admin"
  sleep 3
done
if [ "$ready" != 1 ]; then
  echo "pmm-admin never became ready. Run 'make prestart-pmm-password' and retry." >&2
  exit 1
fi

# Host ports, because pmm-server resolves these names via extra_hosts to the host.
add_external boardgames-mongot "http://mongot:9946/metrics"
add_external boardgames-search-indexes "http://index-exporter:9947/metrics"
add_external osmc-catalog-indexes "http://osmc-index-exporter:9949/metrics"
add_external osmc-recall "http://osmc-recall:9948/metrics"
if compose ps --status running --format '{{.Service}}' | grep -qx osmc-opensearch-exporter; then
  add_external osmc-opensearch "http://osmc-opensearch-exporter:9951/metrics"
else
  echo "skipping osmc-opensearch: OpenSearch alternative is not running (make os-up)"
fi
if compose ps --status running --format '{{.Service}}' | grep -qx osmc-embedding-probe; then
  add_external osmc-embedding "http://osmc-embedding-probe:9952/metrics"
else
  echo "skipping osmc-embedding: the embedding probe is not running (make os-up)"
fi
if compose ps --status running --format '{{.Service}}' | grep -qx osmc-health-exporter; then
  add_external osmc-health "http://osmc-health-exporter:9953/metrics"
else
  echo "skipping osmc-health: the health exporter is not running (make os-up)"
fi
if compose ps --status running --format '{{.Service}}' | grep -qx backend; then
  add_external osmc-app "http://osmc-app:8000/metrics"
else
  echo "skipping osmc-app: the search API is not running"
fi
if compose ps --status running --format '{{.Service}}' | grep -qx vllm; then
  add_external osmc-vllm "http://vllm:8002/metrics"
else
  echo "skipping osmc-vllm: vLLM is off (it starts only with: make osmc-rag-up LLM=1)"
fi

# Scrape every 5 seconds (PMM default is 10), so a drop in recall shows up quickly on stage.
curl -sk -u admin:admin1 -X PUT -H 'Content-Type: application/json' \
  "https://localhost:8443/v1/server/settings" \
  -d '{"metrics_resolutions":{"hr":"5s","mr":"5s","lr":"30s"}}' >/dev/null \
  && echo "PMM metrics resolution: 5 seconds" || echo "could not set the PMM metrics resolution (skipped)"
