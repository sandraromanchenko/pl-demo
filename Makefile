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
FRONTEND_PORT ?= 8081

.DEFAULT_GOAL := help
.PHONY: help seed prestart prestart-app prestart-mongod prestart-data \
        prestart-models prestart-pmm-password demo-state demo-add-search \
        demo-mongot demo-models demo-mongod-search demo-indexes demo-data \
        demo-search demo-status demo-reset demo-wait demo-insert diagram \
        osmc-up osmc-wire osmc-seed osmc-reindex osmc-ask dashboards \
        osmc-rag-up osmc-rag-down os-up os-down os-load os-recall os-degrade \
        os-merge os-watch os-status os-wire os-ask degrade-both restore-both \
        swap-model restore-model quantize unquantize offline-prepare offline-check offline-up offline-test

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
	@echo
	@echo "OSMC — green dashboard, recall gauge (the talk is demo/talk.sh):"
	@echo "  make osmc-up           PSMDB, mongot, Ollama, PMM, search UI, recall"
	@echo "  make osmc-seed         embed the catalog, add churn vectors, write the golden set"
	@echo "  make osmc-rag-up LLM=1 start vLLM + assistant. Never started otherwise; refuses without LLM=1"
	@echo "  make osmc-rag-down LLM=1 stop the assistant"
	@echo "  make osmc-reindex      rebuild the vector index"
	@echo
	@echo "OpenSearch alternative (Faiss HNSW, same vectors; mongot is untouched):"
	@echo "  make os-up             start OpenSearch + exporter, register with PMM"
	@echo "  make os-load           copy the catalog vectors into OpenSearch"
	@echo "  http://localhost:8081  search app: PSMDB + mongot and OpenSearch, one or both side by side"
	@echo "  demo/talk.sh           the five minutes, Enter between steps"
	@echo "  make dashboards        regenerate the PMM dashboards (pmm/render_dashboards.py)"
	@echo "  make os-ask Q='...'    app answer next to the exact answer"
	@echo "  make os-recall         recall@10 against an exact scan of the live docs"
	@echo "  make os-degrade        delete documents that are in the questions' top 10"
	@echo "  make degrade-both      the same deletes in mongot and OpenSearch (backed up)"
	@echo "  make restore-both      undo it and reload OpenSearch"
	@echo "  make os-merge          expunge the deletes; the graph is rebuilt"
	@echo "  make swap-model        stage 2: embed questions with snowflake-arctic-embed:22m (same size, catalog unchanged)"
	@echo "  make restore-model     back to the model the catalog was built with"
	@echo "  make quantize          Percona Search index with scalar quantization (MODE=binary, CANDIDATES=100)"
	@echo "  make unquantize        back to the full-precision index"
	@echo "  make os-watch          recall every 10 seconds"
	@echo "  make os-down           stop OpenSearch"
	@echo
	@echo "No internet (a conference):"
	@echo "  make offline-prepare   with the internet, once: pull, build, cache every image and model"
	@echo "  make offline-check     is everything here? (needs no internet)"
	@echo "  make offline-up        start the whole demo: no build, no pull"
	@echo "  make offline-test      rehearse: start it with every container cut off from the internet"

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

prestart-mongod:
	$(RUN) data 'docker compose --profile data pull'
	$(RUN) data 'docker compose --profile data rm -sf mongot'
	$(RUN) data 'MONGOD_CONF=mongod-nosearch.conf docker compose --profile data up -d --force-recreate mongod pmm-client'

prestart-data:
	$(RUN) app 'docker compose --profile seed run --rm -T -e SEED_PHASE=data seed'
	-$(RUN) app 'docker compose --profile seed run --rm -T -e SEED_PHASE=fulltext seed'

prestart-models:
	$(RUN) models 'demo/models.sh warm'

demo-state:
	$(RUN) data 'docker compose --profile data ps'
	$(RUN) data 'docker compose exec -T mongod dba-mongosh --eval "db.getSiblingDB(\"boardgames\").games.countDocuments({})"'

demo-add-search:
	$(MAKE) demo-mongot
	$(MAKE) demo-models
	$(MAKE) demo-mongod-search

demo-mongot:
	$(RUN) data 'cat config/mongot.yml'
	$(RUN) data 'docker compose --profile data up -d --no-deps mongot index-exporter'
	$(RUN) data 'docker compose exec -T pmm-client pmm-admin add external-serverless --external-name=boardgames-mongot --group=percona-search --url=http://mongot:9946/metrics --skip-connection-check'
	$(RUN) data 'docker compose exec -T pmm-client pmm-admin add external-serverless --external-name=boardgames-search-indexes --group=percona-search --url=http://index-exporter:9947/metrics --skip-connection-check'

demo-models:
	$(RUN) models 'demo/models.sh start'

demo-mongod-search:
	$(RUN) data 'diff -I "^#" config/mongod-nosearch.conf config/mongod.conf || true'
	$(RUN) data 'MONGOD_CONF=mongod.conf docker compose --profile data up -d --force-recreate mongod'

demo-indexes:
	$(RUN) app 'docker compose --profile seed run --rm -T -e SEED_PHASE=indexes seed'

demo-insert:
	$(RUN) data 'sed -n "/^const game = {/,/^};/p" data/keep-it-open.js'
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
	$(RUN) data 'docker compose --profile data rm -sfv mongod mongot pmm-client index-exporter'
	$(RUN) data 'docker volume rm -f pl-demo_mongod_data pl-demo_mongot_data'
	$(RUN) app 'docker compose --profile app rm -sfv pmm-server'
	$(RUN) app 'docker volume rm -f pl-demo_pmm_data'
	$(RUN) models 'docker compose --profile models stop ollama'
	@echo "Reset done. Run 'make prestart' to rebuild the pre-demo state."

OSMC := docker compose $$(osmc/compose-files.sh) --profile data --profile models --profile app --profile osmc
OSMC_RAG := $(OSMC) --profile osmc-rag

osmc-up:
	$(RUN) app '$(OSMC) up -d --build'
	$(MAKE) prestart-pmm-password
	$(MAKE) osmc-wire
	@# Pictures and card details come from the games collection; load it if the volume was recreated.
	$(MAKE) prestart-data
	@echo
	@echo "Stack is up. Next: make osmc-seed  (embeds passages, several minutes)"
	@echo "Search: http://localhost:$(FRONTEND_PORT)"
	@echo "API:    $(BACKEND_URL)/search"
	@echo "PMM:    https://localhost:8443/graph/d/osmc-basic/  (admin / admin1)"
osmc-wire:
	$(RUN) app 'demo/osmc-wire.sh'

osmc-seed:
	$(RUN) app 'docker compose --profile osmc-seed run --rm -T osmc-seed'
	@# The result cards take their picture and details from the games collection; refill it if empty.
	$(MAKE) prestart-data

# vLLM and the assistant start only with an explicit flag: make osmc-rag-up LLM=1
osmc-rag-up:
	@[ "$(LLM)" = "1" ] || { echo "vLLM is off. It starts only with:  make osmc-rag-up LLM=1"; exit 1; }
	$(RUN) app '$(OSMC_RAG) up -d --build osmc-rag vllm'
	$(MAKE) osmc-wire
	@echo
	@echo "Assistant: the Ask tab at http://localhost:$(FRONTEND_PORT)"
	@echo "vLLM is still loading if /ask hangs; wait until docker compose logs vllm show the model is ready."

osmc-rag-down:
	@[ "$(LLM)" = "1" ] || { echo "vLLM is off. To stop it anyway:  make osmc-rag-down LLM=1"; exit 1; }
	$(RUN) app '$(OSMC_RAG) stop osmc-rag vllm'

dashboards:
	python3 pmm/render_dashboards.py

osmc-reindex:
	$(RUN) app '$(OSMC) run --rm --no-deps -T --entrypoint /usr/local/bin/reindex osmc-recall'

osmc-ask:
	$(RUN) app 'curl -sS -G http://localhost:8090/ask --data-urlencode "q=$(Q)"'


OSLAB := docker compose --profile opensearch-lab run --rm -T opensearch-lab

os-up:
	$(RUN) data 'docker compose --profile data up -d mongod'
	$(RUN) app 'docker compose --profile opensearch up -d'
	$(MAKE) os-wire
	@echo "OpenSearch: http://localhost:9200  (next: make os-load)"
	@echo "Search app: http://localhost:8081  (the same question to mongot and OpenSearch)"
	@echo "PMM:        https://localhost:8443/graph/d/osmc-side-by-side/  (admin / admin1)"

os-wire:
	$(RUN) app 'docker compose --profile app ps --status running --format "{{.Service}}" | grep -qx pmm-client && demo/osmc-wire.sh || echo "PMM is not running; skipping registration (make osmc-up first)"'

os-ask:
	$(RUN) app '$(OSLAB) ask "$(Q)"'

os-down:
	$(RUN) app 'docker compose --profile opensearch stop opensearch'

os-load:
	$(RUN) app '$(OSLAB) load'

os-recall:
	$(RUN) app '$(OSLAB) recall'

os-degrade:
	$(RUN) app '$(OSLAB) degrade'

# The same documents deleted in MongoDB (mongot) and in OpenSearch.
degrade-both:
	$(RUN) app '$(OSLAB) degrade-both'

# Put them back in MongoDB and reload OpenSearch. Run before every rehearsal.
restore-both:
	$(RUN) app '$(OSLAB) restore'

os-merge:
	$(RUN) app '$(OSLAB) merge'

SWAP_MODEL ?= snowflake-arctic-embed:22m
swap-model:
	$(RUN) app '$(OSLAB) swap-model $(SWAP_MODEL)'

restore-model:
	$(RUN) app '$(OSLAB) restore-model'

offline-prepare:
	demo/offline-prepare.sh

offline-check:
	demo/offline-check.sh

offline-test:
	demo/offline-test.sh

offline-up:
	docker compose $$(osmc/compose-files.sh) --profile data --profile models --profile app --profile osmc \
	  --profile opensearch up -d --no-build --pull never
	$(MAKE) prestart-pmm-password
	$(MAKE) osmc-wire
	@echo
	@echo "Up. Search: http://localhost:$(FRONTEND_PORT)   PMM: https://localhost:8443/graph/d/osmc-basic/ (admin / admin1)"
	@echo "Reset the demo state (games, right model, no quantization):  make restore-both"

MODE ?= scalar
CANDIDATES ?=
quantize:
	$(RUN) app 'docker compose --profile opensearch-lab run --rm -T -e CANDIDATES=$(CANDIDATES) opensearch-lab quantize $(MODE)'

unquantize:
	$(RUN) app '$(OSLAB) unquantize'

os-watch:
	$(RUN) app '$(OSLAB) watch'

os-status:
	$(RUN) app '$(OSLAB) status'
