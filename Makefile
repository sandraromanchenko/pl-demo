# pl-demo control plane: one target per step of the presentation
#
# Every target runs through demo/run.sh, which executes locally by default and
# over SSH when demo/aws.env sets DEMO_HOST_DATA / DEMO_HOST_MODELS /
# DEMO_HOST_APP. The same commands therefore drive a laptop or the three AWS
# hosts. See demo/README.md for the runbook.

SHELL := /bin/bash
RUN := demo/run.sh
MAKEFLAGS += --no-print-directory

Q ?= fight monsters in a dungeon
MODEL ?= bge-small
BACKEND_URL ?= http://localhost:8000

.DEFAULT_GOAL := help
.PHONY: help seed prestart prestart-app prestart-mongod prestart-data \
        prestart-models prestart-pmm-password demo-state demo-add-search \
        demo-mongot demo-models demo-mongod-search demo-indexes demo-data \
        demo-search demo-status demo-reset demo-wait demo-insert diagram

help:
	@echo "Pre-demo (run well before the audience arrives):"
	@echo "  make prestart          database running with data, web app up,"
	@echo "                         images pulled, model weights cached;"
	@echo "                         search and the embedding model NOT running"
	@echo
	@echo "Live talk (one script, Enter between commands):"
	@echo "  demo/live.sh           starting point, add search, create indexes"
	@echo
	@echo "The same commands without pauses (dry run / recovery):"
	@echo "  make demo-state        what is running and that the data is there"
	@echo "  make demo-add-search   mongot + embedding backend + mongod restart"
	@echo "  make demo-indexes      full-text + autoEmbed vector indexes"
	@echo "  make demo-insert       add Keep It Open (live closer)"
	@echo
	@echo "Utilities:"
	@echo "  make seed              load documents AND create every index (no demo)"
	@echo "  make demo-data         load the documents only"
	@echo "  make demo-search       vector query against the API"
	@echo "  make demo-wait         block until AWS user_data bootstrap is done"
	@echo "  make demo-status       what is running on each host"
	@echo "  make demo-reset        wipe data + indexes + PMM for a fresh rehearsal"

# pre-demo state: MongoDB up WITHOUT search, data is loaded, UI and API up
# demo-wait first: on AWS, user_data is still cloning and pulling right after
# terraform apply, and racing it fails on a half-built /opt/pl-demo
prestart: demo-wait prestart-app prestart-mongod prestart-data prestart-models
	@echo
	@echo "Pre-demo state ready: database + data + web app up, search not enabled."

prestart-app:
	$(RUN) app 'docker compose --profile app pull pmm-server'
	$(RUN) app 'docker compose --profile seed pull seed'
	$(RUN) app 'docker compose --profile app up -d --build backend frontend pmm-server'
	$(MAKE) prestart-pmm-password

prestart-pmm-password:
	$(RUN) app 'until docker compose exec -T pmm-server curl -sk -o /dev/null -w "%{http_code}" https://localhost:8443/ping | grep -q 200; do sleep 3; done'
	$(RUN) app 'docker compose exec -T pmm-server change-admin-password admin1'

# mongod-nosearch.conf has no mongot settings, so $search / $vectorSearch do not exist yet
prestart-mongod:
	$(RUN) data 'docker compose --profile data pull'
	$(RUN) data 'docker compose --profile data rm -sf mongot'
	$(RUN) data 'MONGOD_CONF=mongod-nosearch.conf docker compose --profile data up -d --force-recreate mongod pmm-client'

prestart-data:
	$(RUN) app 'docker compose --profile seed run --rm -T -e SEED_PHASE=data seed'

prestart-models:
	$(RUN) models 'demo/models.sh warm'

demo-state:
	$(RUN) data 'docker compose --profile data ps'
	$(RUN) data 'docker compose exec -T mongod dba-mongosh --eval "db.getSiblingDB(\"boardgames\").games.countDocuments({})"'

# add search + models
demo-add-search:
	$(MAKE) demo-mongot
	$(MAKE) demo-models
	$(MAKE) demo-mongod-search

# mongot comes up on its own, alongside running database
demo-mongot:
	$(RUN) data 'cat config/mongot.yml'
	$(RUN) data 'docker compose --profile data up -d --no-deps mongot'
	$(RUN) data 'docker compose exec -T pmm-client pmm-admin add external-serverless --external-name=boardgames-mongot --group=percona-search --url=http://mongot:9946/metrics --skip-connection-check'

demo-models:
	$(RUN) models 'demo/models.sh start'

# restart that enables search
demo-mongod-search:
	$(RUN) data 'diff -I "^#" config/mongod-nosearch.conf config/mongod.conf || true'
	$(RUN) data 'MONGOD_CONF=mongod.conf docker compose --profile data up -d --force-recreate mongod'

# add full-text + autoEmbed vector indexes over the existing documents,
# waiting for mongot to report READY (which is when the embeddings exist)
demo-indexes:
	$(RUN) app 'docker compose --profile seed run --rm -T -e SEED_PHASE=indexes seed'

demo-insert:
	$(RUN) data 'cat data/keep-it-open.js'
	$(RUN) data 'docker compose exec -T -i mongod dba-mongosh --file /dev/stdin < data/keep-it-open.js'

# ----------------------------------------------------------------- utilities
demo-data: prestart-data

seed:
	$(RUN) app 'docker compose --profile seed run --rm -T seed'

demo-search:
	$(RUN) app 'curl -sG "$(BACKEND_URL)/search" --data-urlencode "q=$(Q)" -d type=vector -d model=$(MODEL) -d limit=5'

demo-wait:
	@demo/wait.sh

diagram:
	dot -Tpng -Gdpi=160 docs/architecture.dot -o docs/architecture.png

demo-status:
	@demo/status.sh

demo-reset:
	$(RUN) data 'docker compose --profile data rm -sfv mongod mongot pmm-client'
	$(RUN) data 'docker volume rm -f pl-demo_mongod_data pl-demo_mongot_data'
	$(RUN) app 'docker compose --profile app rm -sfv pmm-server'
	$(RUN) app 'docker volume rm -f pl-demo_pmm_data'
	$(RUN) models 'docker compose --profile models stop tei ollama'
	@echo "Reset done. Run 'make prestart' to rebuild the pre-demo state."
