#!/usr/bin/env bash
# Is everything here to run the demo with no internet? Needs no internet itself.
#
#   demo/offline-check.sh        (or: make offline-check)
set -uo pipefail
cd "$(cd "$(dirname "$0")/.." && pwd)"

fail=0
ok()  { printf '  ok    %s\n' "$*"; }
bad() { printf '  MISSING  %s\n' "$*"; fail=$((fail + 1)); }
env_get() { sed -n "s/^$1=//p" .env 2>/dev/null | tail -1; }

echo "Images"
images=()
for key in MONGOD_IMAGE MONGOT_IMAGE PMM_SERVER_IMAGE PMM_CLIENT_IMAGE OPENSEARCH_IMAGE OLLAMA_IMAGE \
           SEED_IMAGE; do
  value=$(env_get $key)
  if [ -z "$value" ]; then bad "$key is not pinned in .env"; continue; fi
  images+=("$value")
done
images+=(pl-demo-backend:latest pl-demo-frontend:latest pl-demo-osmc:latest alpine
         python:3.12-slim node:20-alpine nginx:1.27-alpine golang:1.23-bookworm debian:bookworm-slim)
for img in "${images[@]}"; do
  if docker image inspect "$img" >/dev/null 2>&1; then ok "$img"; else bad "image $img"; fi
done

echo "Python tools start without pip downloading anything"
if docker run --rm --network none "$(env_get SEED_IMAGE)" \
     pip install --quiet --no-cache-dir pymongo==4.10.1 'numpy==2.1.3' >/dev/null 2>&1; then
  ok "pymongo 4.10.1 and numpy 2.1.3 are in $(env_get SEED_IMAGE)"
else
  bad "pip needs the network inside $(env_get SEED_IMAGE)"
fi

echo "Volumes with data"
for v in mongod_data mongot_data ollama_data pmm_data osmc_golden opensearch_data; do
  if docker volume inspect "pl-demo_$v" >/dev/null 2>&1; then ok "pl-demo_$v"; else bad "volume pl-demo_$v"; fi
done

echo "Embedding models"
# A throwaway ollama with no network reads the volume, the same way the real one does.
listing=$(docker run --rm --network none -v pl-demo_ollama_data:/root/.ollama --entrypoint /bin/sh \
  "$(env_get OLLAMA_IMAGE)" -c '/bin/ollama serve >/dev/null 2>&1 & for i in $(seq 1 40); do /bin/ollama list >/dev/null 2>&1 && break; sleep 1; done; /bin/ollama list' 2>/dev/null)
echo "$listing" | grep -q "^bge-small" && ok "bge-small" || bad "ollama model bge-small"
echo "$listing" | grep -q "^snowflake-arctic-embed:22m" && ok "snowflake-arctic-embed:22m (the model swap)" || bad "ollama model snowflake-arctic-embed:22m"

echo "Seeded catalog"
if docker run --rm -v pl-demo_osmc_golden:/g alpine test -s /g/golden.json; then ok "golden.json"; else bad "golden.json (make osmc-seed)"; fi

echo
if [ "$fail" -eq 0 ]; then
  echo "Everything is here. Start with:  make offline-up"
else
  echo "$fail thing(s) missing. With the internet, run:  make offline-prepare"
  exit 1
fi
