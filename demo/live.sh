#!/usr/bin/env bash
# The live presentation

set -euo pipefail
. "$(cd "$(dirname "$0")" && pwd)/lib.sh"

demo_title "Where We Begin"

demo_note "Current state: every host in the deployment"

demo_run_all 'docker compose ps'

demo_title "Bringing in the Search Engine"

demo_note "Minimal Percona Search configuration"

demo_run data 'cat config/mongot.yml'

demo_note "Model catalog configuration"

demo_run data 'sed -n "/modelName: bge-small/,/credentials/p" config/embedding-service-configs.yml.tmpl'

demo_note "Starting Percona Search service and embedding service"

demo_run data 'docker compose --profile data up -d --no-deps mongot'
demo_run models 'demo/models.sh start'

demo_note "Register Percona Search metrics with PMM"

demo_run data 'docker compose exec -T pmm-client pmm-admin add external-serverless --external-name=boardgames-mongot --group=percona-search --url=http://mongot:9946/metrics --skip-connection-check'

demo_note "Linking PSMDB to the search service (minimal config change)"

demo_run data 'diff -I "^#" config/mongod-nosearch.conf config/mongod.conf || true'

demo_note "Restarting MongoDB to apply changes, retaining all existing data"

demo_run data 'MONGOD_CONF=mongod.conf docker compose --profile data up -d --force-recreate mongod'

demo_note "The search service is now live"

demo_run data 'docker compose --profile data ps'

demo_title "Making Data Searchable"

demo_note "Defining the full-text index"

demo_run app 'grep -B1 -A12 "\"analyzer\": \"lucene.english\"" data/seed.py'

demo_note "Defining the vector index"

demo_run app 'grep -B3 -A7 "\"type\": \"autoEmbed\"" data/seed.py'

demo_note "Building indexes, so Percona Search can automatically generate document embeddings"

demo_run app 'docker compose --profile seed run --rm -T -e SEED_PHASE=indexes seed'

demo_title "A New Game Lands"

demo_note "The document we are adding"

demo_run data 'cat data/keep-it-open.js'

demo_note "insertOne — Percona Search will embed it automatically"

demo_run data 'docker compose exec -T -i mongod dba-mongosh --file /dev/stdin < data/keep-it-open.js'

