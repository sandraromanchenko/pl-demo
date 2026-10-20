#!/usr/bin/env bash
# Embedding backend on the models host. Every enabled model, including
# bge-small, is served by Ollama.

set -euo pipefail

mode=${1:-start}

# EMBED_MODELS from the environment, else from .env
models=${EMBED_MODELS:-}
if [ -z "$models" ] && [ -f .env ]; then
  models=$(sed -n 's/^EMBED_MODELS=//p' .env | tail -1)
fi
models=${models:-bge-small}

if [ -z "$(echo "$models" | tr -d ' ,')" ]; then
  echo "demo/models.sh: EMBED_MODELS='$models' needs no embedding backend"
  exit 0
fi

echo "EMBED_MODELS=$models -> ollama"

if [ "$mode" = warm ]; then
  docker compose --profile models pull
fi

docker compose --profile models up -d ollama

deadline=$((SECONDS + 900))
echo "waiting for ollama ..."
listed=0
while [ "$SECONDS" -lt "$deadline" ]; do
  if ! docker compose ps --status running --format '{{.Service}}' | grep -qx ollama; then
    echo "ollama container exited while pulling the model:" >&2
    docker compose logs --tail 40 ollama >&2 || true
    exit 1
  fi
  listed=1
  for m in $(echo "$models" | tr ',' ' '); do
    docker compose exec -T ollama ollama list 2>/dev/null | grep -q "^$m" || listed=0
  done
  if [ "$listed" = 1 ]; then
    echo "ollama ready"
    break
  fi
  echo "  still pulling ($models) ..."
  sleep 5
done
if [ "$listed" != 1 ]; then
  echo "WARN ollama not ready after 900s" >&2
  docker compose logs --tail 40 ollama >&2 || true
fi

if [ "$mode" = warm ]; then
  docker compose --profile models stop ollama
  echo "models warmed and stopped; weights cached in the compose volumes"
fi
