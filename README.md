# PL-demo - Board Games Search

A self-contained stack for **full-text**, **vector** and **hybrid** search over board games list, powered by **Percona Server for MongoDB** + **Percona Search for MongoDB** with **auto-embedding**

One codebase runs two ways:

- **Local** — one machine, `docker compose up` (all profiles)
- **AWS** — three EC2 hosts by role (data / models / app),
  each running one compose profile, provisioned by Terraform

Everything is split by **compose profiles**; cross-host references are env vars
whose defaults equal the compose service names

| Profile | Services | Role |
|---------|----------|------|
| `data` | `mongod`, `mongot`, `pmm-client` | database + search + monitoring agent |
| `models` | `tei`, `ollama` | OpenAI-compatible embedding backends |
| `app` | `backend`, `frontend`, `pmm-server` | API, UI, monitoring UI |
| `seed` | `seed` | one-shot loader: documents + indexes, run on demand |

## Search flow

- **Text** — MongoDB's built-in `$text` operator on a classic text index
- **Full-text** — mongot `$search` (Lucene) over the same fields, with **fuzzy**
  matching so misspellings still hit
- **Vector** — `$vectorSearch` with `query` string (mongot auto-embeds it)
  against the vector index for the selected model
- **Hybrid** — runs both top-K and merges them with **Reciprocal Rank Fusion
  (RRF)** in the backend
- **Model selection** — one autoEmbed index per model; the UI dropdown picks
  which index vector/hybrid queries target

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

## Auto-embedding

Vector and hybrid search use mongot **auto-embedding** (`OPENAI_COMPATIBLE`,
PSMDB-2143), included in **`percona/percona-search-mongodb:1.70.4`**
Override `MONGOT_IMAGE` / Terraform `mongot_image` variable only if you need another tag.

---

## Quick start - local

Database, search, embedding model, API and UI on one machine:

```bash
cd pl-demo
cp .env.example .env      # COMPOSE_PROFILES enables data + models + app
docker compose up -d      # start everything
make seed                 # load games, create indexes, wait for READY
docker compose ps         # optional: everything should be up/healthy
```

Open UI and search:

- **Frontend UI** — http://localhost:8081
- **Backend API** — http://localhost:8000 (`/health`, `/models`, `/games`, `/search`)
- **PMM UI** — https://localhost:8443 (login `admin` / `admin1`)

The first run pulls the images and downloads the embedding model, so expect a
few minutes before `make seed` finishes; it prints progress and exits once every
index reports `READY`. After that the data lives in Docker volumes, so later
`docker compose up -d` runs come up seeded.

> One command instead of two? Add `seed` to `COMPOSE_PROFILES` in `.env`
> (`COMPOSE_PROFILES=data,models,app,seed`) and `docker compose up -d` loads the
> data as well — the loader waits for the database and retries until search is
> reachable. Running it separately just makes the progress easier to watch.

> Prefer not to use a `.env`? Pass the profiles explicitly instead:
> `docker compose --profile data --profile models --profile app up -d`

The one-shot `seed` service waits for Mongo, loads the board games, builds the
`search_text` field, creates a classic MongoDB text index (`text_idx` for `$text`),
the mongot `text_index` + per-model autoEmbed vector indexes, and waits for the
mongot indexes to report `READY`. `make seed` runs it in the foreground so you
can watch that happen; the equivalent compose command is:

```bash
docker compose --profile seed run --rm -T seed
```

It runs in two phases, selected with `SEED_PHASE`, so the database can be filled
before search exists:

| `SEED_PHASE` | Does | Needs |
|--------------|------|-------|
| `data` | documents, `rank_idx`, classic `text_idx` | mongod only |
| `indexes` | mongot `text_index` + autoEmbed vector indexes, waits for `READY` | mongot + an embedding backend |
| `all` (default) | both | everything |

Nothing is loaded until you run the seed step, so `docker compose up -d` on its
own already gives you an empty stack. `SEED_DATA=false` additionally makes the
seed service a no-op if you keep `seed` in `COMPOSE_PROFILES`.

Tear down (keep data / wipe volumes):

```bash
docker compose down
docker compose down -v
```

### Search examples

Via the API (`type` = `text` | `fulltext` | `vector` | `hybrid`; `model` applies to
vector/hybrid):

```bash
# Classic MongoDB $text (built-in text index; typos miss)
curl "http://localhost:8000/search?q=destroy%20zombies%20and%20not%20difficult%20riles&type=text&limit=5"

# Full-text (mongot $search + fuzzy; same query)
curl "http://localhost:8000/search?q=destroy%20zombies%20and%20not%20difficult%20riles&type=fulltext&limit=5"

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
(noble) AMI**, one per role, each with its own `instance_type`. Each host's `user_data` installs Docker + compose plugin, clones this repo, and writes its `.env` (Terraform interpolates the other hosts' private IPs).

### Quick start — AWS

```bash
cd deploy/aws
cp terraform.tfvars.example terraform.tfvars   # set key_name (an existing EC2 key pair)
terraform init
terraform apply -var='auto_start=true'         # or: TF_VAR_key_name=my-key terraform apply -var='auto_start=true'
terraform output                               # frontend_url, public IPs, ready-made ssh commands
```

Each host clones `repo_url` on boot (the example tfvars points at the GitHub
copy), so push any local changes before `terraform apply`. `terraform apply`
returns when the instances exist; cloud-init still has to install Docker, pull
images and seed. Give it a few minutes, then open `frontend_url`.

`auto_start=true` starts mongod/mongot, the embedding backends, and the seed
from `user_data` (seed retries until the other hosts are reachable). Leave it
unset/`false` for the live demo, which only pulls images and leaves search off.

Then open:

- **Frontend UI** — `http://<app_public_ip>/`
- **Backend API** — `http://<app_public_ip>:8000`
- **PMM UI** — `https://<app_public_ip>:8443` (login `admin` / `admin1`)

Enabled models are the Terraform `embed_models` variable (becomes
`EMBED_MODELS` in each host's `.env`). Tear the whole thing down with
`terraform destroy`.

### What each host does on boot

Default (`auto_start=false`) is the presentation pre-demo state — images on
disk, search not running:

| Role | On boot (`auto_start=false`) | On boot (`auto_start=true`) |
|------|------------------------------|-----------------------------|
| `app` | `backend` / `frontend` / `pmm-server` up; seed image pulled | same, then seed loads documents and indexes |
| `data` | `mongod` / `mongot` / `pmm-client` images pulled; **not** started | those containers started |
| `models` | images pulled; weights cached; backends **stopped** | embedding backends started |

Networking: new `pl-demo` security group allows SSH, ICMP, all traffic within
SG and egress all and also opens the web ports; it's attached to all three
hosts. The intra-SG rule covers the private cross-host ports since every host 
shares the group. Private IPs come from pre-created ENIs (avoids guessing free 
addresses and breaks the data↔app dependency cycle); each host gets an Elastic IP 
(SSH + egress; the app EIP also bakes a stable `VITE_API_BASE` into the frontend).

![pl-demo architecture: Application host, Data host, Models host](docs/architecture.png)

Source is `docs/architecture.dot`; regenerate the PNG with `make diagram` (needs
Graphviz).

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
- **mongot metrics** are enabled at `:9946/metrics`. After mongot is started,
  `demo/live.sh` registers it with PMM as the external service
  `boardgames-mongot` (`pmm-admin add external-serverless`).
- The provisioned **Percona Search for MongoDB — Mongot** dashboard is under
  **Dashboards → Percona Search**, or directly at
  `https://<app-host>:8443/graph/d/percona-search-mongot/`. It shows readiness,
  search throughput and latency, auto-embedding/search workers, CPU, JVM heap,
  and errors.

Cross-host wiring / credentials (defaults):

| Var | Default | Meaning |
|-----|---------|---------|
| `PMM_SERVER` | `pmm-server` (local) / app private IP (AWS) | where the client sends metrics |
| `PMM_SERVER_PORT` | `8443` | PMM server HTTPS port |
| `PMM_USERNAME` / `PMM_PASSWORD` | `admin` / `admin1` | PMM login; also used by the client to register |

**Log in to the PMM UI with `admin` / `admin1`**. Skip the first-login password
prompt — `make prestart` resets the password to `admin1` so pmm-client can
register. A UI-only change leaves mongot metrics unreachable.

---

## Repo layout

```
pl-demo/
  docker-compose.yml          # profiles: data | models | app | seed
  .env.example                # all cross-host endpoints, local defaults
  Makefile                    # make seed, plus the presentation steps
  demo/                       # presentation scripts and runbook
  docs/                       # architecture.dot + rendered architecture.png
  env/                        # per-role .env templates for AWS
  config/
    mongod.conf               # mongotHost: mongot:27028 (co-located)
    mongod-nosearch.conf      # same, minus the mongot settings
    mongot.yml                # syncSource mongod:27017 as user mongot
    embedding-service-configs.yml.tmpl  # ${TEI_URL} / ${OLLAMA_URL}
    keyfile
    mongot-password           # SCRAM password for the mongot user
    dba-password              # SCRAM password for the dba operator user
    dba-mongosh.sh            # mongosh as dba, password from the file
  data/                       # dataset + seed.py
  backend/                    # FastAPI (app/{main,db,search,config}.py)
  frontend/                   # React + Vite + Tailwind, nginx
  deploy/aws/                 # Terraform: 3 typed instances + SG + user_data
```

## How cross-host wiring works

- `config/mongod.conf` (`mongotHost: mongot:27028`) and `config/mongot.yml`
  (`syncSource … mongod:27017`) stay container-local — `mongod` + `mongot` are
  always **co-located on the data host**, keeping gRPC and mongot's SCRAM user
  on one machine. mongod still uses a replica-set keyfile; mongot does not.
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
| Vector/hybrid returns an error; seed logs "could not create vector index" | `MONGOT_IMAGE` is older than `1.70.4` (no `OPENAI_COMPATIBLE` provider). |
| `/health` 503 | Backend can't reach Mongo — check `MONGO_URI` and that the data host's `27017` is reachable. |
| Indexes stuck not `READY` | Embedding backend still downloading its model, or mongot can't reach `TEI_URL`/`OLLAMA_URL`; check `docker compose logs mongot`. |
