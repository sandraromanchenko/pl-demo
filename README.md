# PL-demo — Board Games Search

A self-contained demo of **full-text**, **vector** and **hybrid** search over ~20k
board games, powered by **Percona Server for MongoDB** + **mongot** with **auto-embedding**

One codebase runs two ways:

- **Local** — one machine, `docker compose up` (all profiles)
- **AWS** — three plain CPU EC2 hosts by role (data / models / app),
  each running one compose profile, provisioned by Terraform.

Everything is split by **compose profiles**; cross-host references are env vars
whose defaults equal the compose service names

| Profile | Services | Role |
|---------|----------|------|
| `data` | `mongod`, `mongot`, `pmm-client` | database + search + monitoring agent |
| `models` | `tei`, `ollama` | OpenAI-compatible embedding backends |
| `app` | `backend`, `frontend`, `seed`, `pmm-server` | API, UI, loader, monitoring UI |

## Search flow

- **Full-text** — `$search` over `name` / `description` / `categories` /
  `mechanics` (uses `text_index`).
- **Vector** — `$vectorSearch` with a `query` string (mongot auto-embeds it)
  against the vector index for the selected model.
- **Hybrid** — runs both top-K and merges them with **Reciprocal Rank Fusion
  (RRF)** in the backend. (A native `$rankFusion` stage is a possible future
  alternative.)
- **Model selection** — one autoEmbed index per model; the UI dropdown picks
  which index vector/hybrid queries target.

| `model` | Backend | Dims | Vector index |
|---------|---------|------|--------------|
| `bge-small` (default) | `tei` (`BAAI/bge-small-en-v1.5`) | 384 | `vec_bge_small` |
| `nomic-embed-text` | `ollama` | 768 | `vec_nomic` |
| `bge-m3` | `ollama` | 1024 | `vec_bge_m3` |

Which models are enabled on start is controlled by **`EMBED_MODELS`** (comma-separated),
which drives image pulls and seed creation / vector indexes, so they can't drift out of sync.
Default is `bge-small` (one model, one index); enable more to compare:

```bash
EMBED_MODELS=bge-small,nomic-embed-text,bge-m3 docker compose up -d
```

---

## ⚠️ Auto-embedding requires mongot build with `OPENAI_COMPATIBLE`

Vector and hybrid search depend on mongot's **auto-embedding** (PSMDB-2143).
This stack therefore defaults `MONGOT_IMAGE` to a build that includes the
provider: **`perconalab/percona-search-mongodb:dev`**. Override it if you need a
specific build:

```bash
MONGOT_IMAGE=perconalab/percona-search-mongodb:pr-XX docker compose up -d
```

On AWS, set the `mongot_image` Terraform variable (it also defaults to `:dev`).

---

## Local quick start

```bash
cd pl-demo
cp .env.example .env
docker compose up -d
docker compose ps
```

> Prefer not to use a `.env`? Pass the profiles explicitly instead:
> `docker compose --profile data --profile models --profile app up -d`

Then open:

- **Frontend UI** — http://localhost:8081
- **Backend API** — http://localhost:8000 (`/health`, `/models`, `/search`)
- **PMM UI** — https://localhost:8443 (login `admin` / `admin`)

The one-shot `seed` service waits for Mongo, loads the board games, builds the
`search_text` field, creates the `text_index` + per-model autoEmbed vector
indexes, and waits for them to report `READY`. Watch it with:

```bash
docker compose logs -f seed
```

Choose the dataset with `DATASET` (`sample` default → `data/sample_boardgames.ndjson`,
~20 popular games, or `full` → `data/boardgames.ndjson`); see
[`data/README.md`](data/README.md).

Start without loading anything:

```bash
SEED_DATA=false docker compose up -d
```

Tear down (keep data / wipe volumes):

```bash
docker compose down
docker compose down -v
```

> **CPU embedding note.** Embedding ~20k descriptions runs on **CPU**, so the
> first seed is a slower one-time step (minutes) while mongot embeds every document

### Search examples

Via the API (`type` = `fulltext` | `vector` | `hybrid`; `model` applies to
vector/hybrid):

```bash
# Full-text over name/description/categories/mechanics
curl "http://localhost:8000/search?q=cooperative%20deck%20building&type=fulltext&limit=5"

# Vector (auto-embed) with the default bge-small index
curl "http://localhost:8000/search?q=fight%20monsters%20in%20a%20dungeon&type=vector&model=bge-small&limit=5"

# Vector with the Ollama nomic model
curl "http://localhost:8000/search?q=build%20an%20economic%20engine&type=vector&model=nomic-embed-text&limit=5"

# Hybrid (full-text + vector, merged with RRF)
curl "http://localhost:8000/search?q=space%20exploration%20strategy&type=hybrid&model=bge-small&limit=5"

# Which models/indexes are available (drives the UI dropdown)
curl "http://localhost:8000/models"
```

Or just use the UI: type a query, pick the search type, and (for vector/hybrid)
pick the model/index.

---

## AWS deploy (3 hosts, Terraform + compose profiles)

`deploy/aws/` launches **three EC2 instances from the same standard Ubuntu 24.04
(noble) AMI**, one per role, each with its own `instance_type`. Each host's `user_data` installs Docker + compose plugin, clones this repo, writes its `.env` (Terraform interpolates the other hosts' private IPs), and runs `docker compose --profile <role> up -d`.

Networking: new `pl-demo` security group allows SSH, ICMP, all traffic within
SG and egress all and also opens the web ports; it's attached to all three
hosts. The intra-SG rule covers the private cross-host ports since every host 
shares the group. Private IPs come from pre-created ENIs (avoids guessing free 
addresses and breaks the data↔app dependency cycle); each host gets an Elastic IP 
(SSH + egress; the app EIP also bakes a stable `VITE_API_BASE` into the frontend). 
All resources carry the mandatory `iit-billing-tag: dev`.

```mermaid
flowchart LR
  user["Browser"]

  subgraph appHost ["app host"]
    fe["frontend :80"]
    be["backend :8000"]
    seed["seed (one-shot)"]
    pmmsrv["pmm-server :8443"]
  end

  subgraph dataHost ["data host"]
    mongod["mongod :27017"]
    mongot["mongot"]
    pmmcli["pmm-client"]
  end

  subgraph modelsHost ["models host (bigger CPU)"]
    tei["tei :8085"]
    ollama["ollama :11434"]
  end

  user --> fe
  fe --> be
  be -->|"MONGO_URI"| mongod
  seed --> mongod
  mongod <-->|"local gRPC + keyfile"| mongot
  mongot -->|"TEI_URL"| tei
  mongot -->|"OLLAMA_URL"| ollama
  pmmcli -->|"PMM_SERVER :8443"| pmmsrv
```

### Deploy

```bash
cd deploy/aws
cp terraform.tfvars.example terraform.tfvars
# REQUIRED edits: key_name (an existing EC2 key pair) or pass it at apply time:
# TF_VAR_key_name=my-key terraform apply
terraform init
terraform apply
```

Outputs include `frontend_url`, `backend_url`, `pmm_url`, the per-host public
IPs, and ready-made `ssh` commands. Tear the whole thing down with:

```bash
terraform destroy
```

### Security group

One new `pl-demo` group attached to all three hosts:

| Rule | Source | Purpose |
|------|--------|---------|
| SSH `22` | `0.0.0.0/0` | admin access |
| ICMP | `0.0.0.0/0` | ping |
| **all traffic within the SG** (self) | this SG | cross-host `27017` / `8085` / `11434` / `8443` |
| `80` / `8000` / `8443` | `web_ingress_cidr` | frontend / backend / PMM UI (served by the app host) |
| egress all | — | image pulls, model downloads |


### Per-role env templates

`env/data.env`, `env/models.env`, `env/app.env` document exactly what each host
needs (Terraform renders equivalents automatically). Use them if you deploy by
hand: fill in `MODELS_PRIVATE_IP` / `APP_PRIVATE_IP` / `DATA_PRIVATE_IP` /
`APP_PUBLIC_IP` and run the matching profile.

---

## Monitoring (PMM)

- **`pmm-server`** runs in the `app` profile; its web UI is published on the app
  host at **`https://<app-host>:8443`** (self-signed TLS).
- **`pmm-client`** is a sidecar in the `data` profile. On startup it registers
  itself against `PMM_SERVER` and adds the local `mongod` (MongoDB exporter) as
  the service `boardgames-mongod`.

Cross-host wiring / credentials (defaults):

| Var | Default | Meaning |
|-----|---------|---------|
| `PMM_SERVER` | `pmm-server` (local) / app private IP (AWS) | where the client sends metrics |
| `PMM_SERVER_PORT` | `8443` | PMM server HTTPS port |
| `PMM_USERNAME` / `PMM_PASSWORD` | `admin` / `admin` | PMM login; also used by the client to register |

**Log in to the PMM UI with `admin` / `admin`** (PMM may prompt you to change
the password on first login). Change `PMM_PASSWORD` (compose) or the
`pmm_password` Terraform variable for anything real.

---

## Repo layout

```
pl-demo/
  docker-compose.yml          # profiles: data | models | app
  .env.example                # all cross-host endpoints, local defaults
  env/                        # per-role .env templates for AWS
  config/
    mongod.conf               # mongotHost: mongot:27028 (co-located)
    mongot.yml                # syncSource mongod:27017 + auto-embedding
    embedding-service-configs.yml.tmpl  # ${TEI_URL} / ${OLLAMA_URL}
    keyfile
  data/                       # dataset + sample + seed.py + prepare_data.py
  backend/                    # FastAPI (app/{main,db,search,config}.py)
  frontend/                   # React + Vite + Tailwind, nginx
  deploy/aws/                 # Terraform: 3 typed instances + SG + user_data
```

## How cross-host wiring works

- `config/mongod.conf` (`mongotHost: mongot:27028`) and `config/mongot.yml`
  (`syncSource … mongod:27017`) stay container-local — `mongod` + `mongot` are
  always **co-located on the data host**, keeping the hard coupling (keyfile,
  `syncSource`, gRPC) on one machine.
- The embedding catalog is a template
  (`config/embedding-service-configs.yml.tmpl`) with `${TEI_URL}` (default
  `http://tei:80`) and `${OLLAMA_URL}` (default `http://ollama:11434`), rendered
  at mongot container start so it can point at the models host on AWS.
- Backend/seed `MONGO_URI` defaults to
  `mongodb://root:root@mongod:27017/?authSource=admin&directConnection=true`;
  on the app host it points at the data host's private IP. `directConnection=true`
  sidesteps the replica-set advertised-hostname gotcha across hosts.

## Troubleshooting

| Symptom | Check |
|---------|-------|
| Vector/hybrid returns an error; seed logs "could not create vector index" | `MONGOT_IMAGE` lacks the `OPENAI_COMPATIBLE` provider — use a dev build. |
| `/health` 503 | Backend can't reach Mongo — check `MONGO_URI` and that the data host's `27017` is reachable. |
| Indexes stuck not `READY` | Embedding backend still downloading its model, or mongot can't reach `TEI_URL`/`OLLAMA_URL`; check `docker compose logs mongot`. |
| First seed is slow | Expected — CPU embedding of the full dataset. See the CPU note above. |
| Empty results on the sample data | The sample is small (~20 games); try broader queries or load `data/boardgames.ndjson`. |
