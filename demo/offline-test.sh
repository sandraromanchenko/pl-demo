#!/usr/bin/env bash
# Rehearse the trip: start the whole demo with the internet cut off for every container, then check it.
#
#   demo/offline-test.sh        (or: make offline-test)
#
# Every service gets a DNS server that does not exist, so a container that tries to reach pypi.org,
# registry.ollama.ai or huggingface.co fails the way it would on a plane. Names inside the demo network
# still resolve. Nothing is pulled and nothing is built. Volumes (data, models, weights) are kept.
# Afterwards `make offline-up` puts the normal settings back.
set -euo pipefail
cd "$(cd "$(dirname "$0")/.." && pwd)"

profiles=(--profile data --profile models --profile app --profile osmc --profile opensearch)
files=($(osmc/compose-files.sh 2>/dev/null))
# Naming any -f turns off the default docker-compose.yml, so list it when nothing else did.
[ "${#files[@]}" -gt 0 ] || files=(-f docker-compose.yml)
override=$(mktemp /tmp/pl-demo-offline-XXXX.yml)
trap 'rm -f "$override"' EXIT

{
  echo "services:"
  docker compose "${files[@]}" "${profiles[@]}" config --services | while read -r svc; do
    printf '  %s:\n    dns: ["192.0.2.1"]\n' "$svc"
  done
} > "$override"

echo "== Stop the stack (volumes are kept)"
docker compose "${files[@]}" "${profiles[@]}" --profile opensearch-lab down --remove-orphans

echo "== Start with no internet"
docker compose "${files[@]}" -f "$override" "${profiles[@]}" up -d --no-build --pull never

echo "== Wait for the services"
for _ in $(seq 1 90); do
  ok=1
  curl -sf localhost:8000/health >/dev/null 2>&1 || ok=0
  curl -sf localhost:11434/api/tags >/dev/null 2>&1 || ok=0
  curl -sf localhost:9200/_cluster/health >/dev/null 2>&1 || ok=0
  curl -sf localhost:8081/ >/dev/null 2>&1 || ok=0
  [ "$ok" = 1 ] && break
  sleep 3
done

echo "== Register with PMM"
make prestart-pmm-password >/dev/null
for try in $(seq 1 12); do
  make osmc-wire >/tmp/pl-demo-wire.log 2>&1 && break
  echo "  PMM is not connected yet ($try/12)"; sleep 10
done
tail -3 /tmp/pl-demo-wire.log

echo "== Checks"
sleep 20
fail=0
check() { if eval "$2" >/dev/null 2>&1; then printf '  ok    %s\n' "$1"; else printf '  FAILED  %s\n' "$1"; fail=$((fail + 1)); fi; }
search() { curl -sf -G localhost:8000/search --data-urlencode "q=urban apocalypse" -d type=vector -d "engine=$1" -d limit=5 | python3 -c 'import sys,json; sys.exit(0 if len(json.load(sys.stdin)["results"])==5 else 1)'; }
check "search app answers"            "curl -sf localhost:8081/"
check "Percona Search vector search"  "search mongot"
check "OpenSearch vector search"      "search opensearch"
check "embedding probe is running"    "curl -sf localhost:9952/metrics | grep -q embedding_canary"
check "health exporter is running"    "curl -sf localhost:9953/metrics | grep -q embedding_service_up"
# After a cold start OpenSearch loads its graph first, the first recall value takes a minute or two.
for _ in $(seq 1 30); do curl -sf localhost:9951/metrics | grep -q opensearch_vector_search_recall && break; sleep 5; done
check "OpenSearch exporter is running" "curl -sf localhost:9951/metrics | grep -q opensearch_vector_search_recall"
check "recall probe is running"       "curl -sf localhost:9948/metrics | grep -q vector_search_recall"
check "embedding model serving"       "curl -sf localhost:9953/metrics | grep -q '^embedding_service_up 1'"
check "no python container stuck on pip" "! docker ps --format '{{.Names}} {{.Status}}' | grep -E 'exporter|probe' | grep -i -E 'restarting|exited'"
echo
if [ "$fail" -eq 0 ]; then echo "Works with no internet."; else echo "$fail check(s) failed."; exit 1; fi
