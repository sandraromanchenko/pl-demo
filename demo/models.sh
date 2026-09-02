#!/usr/bin/env bash
# Embedding backends on the models host

set -euo pipefail

mode=${1:-start}

# EMBED_MODELS from the environment, else from .env
models=${EMBED_MODELS:-}
if [ -z "$models" ] && [ -f .env ]; then
  models=$(sed -n 's/^EMBED_MODELS=//p' .env | tail -1)
fi
models=${models:-bge-small}

need_tei=0
need_ollama=0
for m in $(echo "$models" | tr ',' ' '); do
  case "$m" in
    bge-small) need_tei=1 ;;
    *) need_ollama=1 ;;
  esac
done

services=()
if [ "$need_tei" = 1 ]; then services+=(tei); fi
if [ "$need_ollama" = 1 ]; then services+=(ollama); fi
if [ ${#services[@]} -eq 0 ]; then
  echo "demo/models.sh: EMBED_MODELS='$models' needs no embedding backend"
  exit 0
fi

echo "EMBED_MODELS=$models -> ${services[*]}"

if [ "$mode" = warm ]; then
  docker compose --profile models pull
fi

docker compose --profile models up -d "${services[@]}"

wait_for() {
  local what=$1 timeout=${2:-900} deadline
  deadline=$((SECONDS + timeout))
  while [ "$SECONDS" -lt "$deadline" ]; do
    case "$what" in
      tei) curl -fsS "http://localhost:8085/health" >/dev/null 2>&1 && return 0 ;;
      ollama)
        local listed=1
        for m in $(echo "$models" | tr ',' ' '); do
          if [ "$m" = bge-small ]; then continue; fi
          docker compose exec -T ollama ollama list 2>/dev/null | grep -q "^$m" || listed=0
        done
        if [ "$listed" = 1 ]; then return 0; fi
        ;;
    esac
    sleep 3
  done
  echo "WARN $what not ready after ${timeout}s" >&2
  return 1
}

for s in "${services[@]}"; do
  echo "waiting for $s ..."
  wait_for "$s" || true
  echo "$s ready"
done

if [ "$mode" = warm ]; then
  docker compose --profile models stop "${services[@]}"
  echo "models warmed and stopped; weights cached in the compose volumes"
fi
