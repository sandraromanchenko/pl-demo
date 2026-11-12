#!/usr/bin/env bash
# Fetch and build everything the demo needs, so it runs with no internet.
# Run this ONCE, with the internet, before you travel. It is safe to run again.
#
#   demo/offline-prepare.sh        (or: make offline-prepare)
#
# It ends with demo/offline-check.sh, which needs no internet and tells you what is missing.
set -euo pipefail
cd "$(cd "$(dirname "$0")/.." && pwd)"

say() { printf '\n== %s\n' "$*"; }

# Read the pinned image names from .env, so there is one place that says which version.
env_get() { sed -n "s/^$1=//p" .env | tail -1; }

pull_if_missing() {
  if docker image inspect "$1" >/dev/null 2>&1; then
    echo "have  $1"
  else
    echo "pull  $1"
    docker pull "$1"
  fi
}

say "Images (exact versions from .env)"
for key in MONGOD_IMAGE MONGOT_IMAGE PMM_SERVER_IMAGE PMM_CLIENT_IMAGE OPENSEARCH_IMAGE; do
  pull_if_missing "$(env_get $key)"
done
# The ollama tag is the version of the image that is already here; tag it if the registry has no such tag.
ollama_image=$(env_get OLLAMA_IMAGE)
if ! docker image inspect "$ollama_image" >/dev/null 2>&1; then
  docker pull "$ollama_image" || docker tag ollama/ollama:latest "$ollama_image"
fi
echo "have  $ollama_image"

say "Base images of the builds"
for img in python:3.12-slim node:20-alpine nginx:1.27-alpine golang:1.23-bookworm debian:bookworm-slim alpine; do
  pull_if_missing "$img"
done

say "Local images (Python tools, backend, frontend, Go probes)"
export SEED_IMAGE
SEED_IMAGE=$(env_get SEED_IMAGE)
docker compose --profile tools build pytools
docker compose $(osmc/compose-files.sh) --profile data --profile models --profile app --profile osmc \
  build backend frontend osmc-recall

say "Embedding models in the ollama volume"
docker compose --profile models up -d ollama
for _ in $(seq 1 60); do
  docker compose exec -T ollama ollama list >/dev/null 2>&1 && break
  sleep 2
done
for m in bge-small snowflake-arctic-embed:22m; do
  if docker compose exec -T ollama ollama list | grep -q "^${m%%:*}"; then
    echo "have  $m"
  else
    echo "pull  $m"
    if [ "$m" = bge-small ]; then
      docker compose exec -T ollama ollama pull qllama/bge-small-en-v1.5:f16
      docker compose exec -T ollama ollama cp qllama/bge-small-en-v1.5:f16 bge-small
    else
      docker compose exec -T ollama ollama pull "$m"
    fi
  fi
done

say "Check"
demo/offline-check.sh
