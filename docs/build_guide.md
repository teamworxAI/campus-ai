# Build guide: from a fresh machine

This guide takes a new machine to a working stack: tests passing, models
fetched, a Europeana collection indexed and searchable. Everything runs in
Docker, so you don't need Python on the host.

```mermaid
flowchart TD
    P[1. Install Docker + Git] --> C[2. Clone the repo]
    C --> E[3. Create .env]
    E --> B[4. Build images]
    B --> T[5. Run unit tests]
    T --> M[6. Fetch model weights<br/>one time, needs internet]
    M --> V[7. Verify offline embedding]
    V --> H[8. Harvest Europeana<br/>needs internet + key]
    H --> I[9. Index + search<br/>offline]
    I --> G{NVIDIA GPU?}
    G -->|yes| GP[10. Enable GPU overlay]
    G -->|no| D[Done]
    GP --> D
```

## 0. Requirements

| | Minimum | Recommended |
|---|---|---|
| OS | Linux x86-64, macOS (Apple silicon or Intel), Windows 10/11 with WSL 2 | Ubuntu 24.04 or newer |
| CPU / RAM | 4 cores / 12 GB free for Docker (embedding peaks near 8 GB) | 8+ cores / 16 GB+ |
| Free disk | 25 GB | 40 GB |
| GPU | none | NVIDIA with bfloat16 support (Ampere or newer) |
| Network | Internet for steps 2, 4, 6 and 8 only | — |

Disk use after setup:

| Item | Size |
|---|---|
| `campus-ai:embed` image (PyTorch etc.) | ~10 GB |
| `campus-ai:test` image | ~0.4 GB |
| `neo4j` image | ~1.1 GB |
| Model weights (EmbeddingGemma 2 1.5 GB, e5-small 0.5 GB) | ~2 GB |
| 300 Europeana items with thumbnails | ~11 MB |
| Build cache during the first build | 2–5 GB, reclaimable |

## 1. Install Docker and Git

You need Docker Engine 24+ with the Compose v2 plugin. This repo is tested
with Docker 29.8 and Compose v5.6.

**Ubuntu / Debian**

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"     # then log out and back in
sudo apt-get install -y git
docker compose version              # must print v2 or later
```

**macOS.** Install Docker Desktop from https://www.docker.com/products/docker-desktop/.
In Settings → Resources, give it at least 12 GB of memory and 40 GB of disk.
Git comes with the Xcode command line tools (`xcode-select --install`).

**Windows.** Install WSL 2 (`wsl --install`), then Docker Desktop with the
WSL 2 backend and Git for Windows. In Settings → Resources, allow 12+ GB
memory. Run the commands below in PowerShell or a WSL shell. For faster file
access, clone inside the WSL file system (`\\wsl$\...`).

Check that Docker works:

```bash
docker run --rm hello-world
```

## 2. Clone the repository

The repository is private. Authenticate with the GitHub CLI
(`gh auth login`), with a personal access token, or with SSH:

```bash
git clone https://github.com/teamworxai/campus-ai.git
cd campus-ai
```

To get work in progress that isn't merged yet, check out its branch, e.g.
`git checkout r8-europeana`.

## 3. Create `.env`

```bash
cp .env.example .env
```

Edit `.env`:

| Key | Needed for | Value |
|---|---|---|
| `MODELS_DIR` | all model work | Host folder for weights. Empty means `./models`. Share it across projects, e.g. `C:/models` on Windows or `/srv/models` on Linux |
| `HF_TOKEN` | optional | Only if Hugging Face rate-limits you. The models aren't gated |
| `NEO4J_PASSWORD` | optional | Set it **before** Neo4j first starts; empty means `campus-ai-local`. Neo4j has no published ports |
| `EUROPEANA_API_KEY` | step 8 | Free from https://pro.europeana.eu/page/get-api |
| `COMPOSE_FILE` | step 10 | GPU overlay; leave commented on machines without NVIDIA |

`.env` is gitignored. Never commit it.

## 4. Build the images

```bash
docker compose build
```

This builds `campus-ai:test` (about 1 minute) and `campus-ai:embed` (about
5–15 minutes, which downloads PyTorch). Dependencies come from `uv.lock`,
so every machine gets the same versions.

**Behind a TLS-inspecting corporate proxy?** The Dockerfile accepts the
proxy's CA certificate as an optional build secret named `ca`. Copy the
pattern in `.claude/compose.cloud.yaml`: a `secrets: ca: file:
<path to CA bundle>` entry, plus `build: secrets: [ca]` and the
`HTTPS_PROXY` build args on each service. Pass the same CA to the
`fetch-*` services via `SSL_CERT_FILE`.

## 5. Run the unit tests

```bash
docker compose run --rm test
```

Expect `OK (skipped=3)`. The three skipped tests need the embed image and
Neo4j, and run in step 7.

## 6. Fetch model weights (one time)

```bash
docker compose run --rm fetch-models
```

This downloads EmbeddingGemma 2 and the e5-small baseline (about 2 GB) into
`MODELS_DIR`, using the layout `<org>/<model>`. It is the only step that
downloads models.

**Air-gapped machine.** Run this step on a connected machine, then copy the
`MODELS_DIR` folder over (USB, `rsync`, `scp`). Keep the same layout:
`google/embeddinggemma-2/`, `intfloat/multilingual-e5-small/`.

## 7. Verify offline embedding and the graph

```bash
docker compose run --rm embed                                 # bake-off on the sample set
docker compose run --rm embed python -m unittest discover -s tests   # all tests, incl. Neo4j
docker compose run --rm embed python scripts/graph_search.py index evals/embed/sample_bakeoff.jsonl
docker compose run --rm embed python scripts/graph_search.py eval evals/embed/sample_bakeoff.jsonl
```

Expected:
- The bake-off prints recall@10 for `embeddinggemma-2` and `e5-small`.
- The unit tests report `OK` with no skips.
- The eval prints `embeddinggemma-2 hybrid: recall@10 all=1.000, en=1.000, fr=1.000 (5 queries)`.

The first `embed` run starts Neo4j and waits for its health check, which
takes about 20 seconds.

**Optional: prove that the embed container is offline.**

```bash
docker compose run --rm embed python -c "import socket; socket.create_connection(('huggingface.co', 443), 3)"
# fails with socket.gaierror: no route out of the internal network
```

## 8. Harvest a Europeana collection

```bash
docker compose run --rm fetch-europeana --rows 300
```

This takes about 2 minutes and writes `data/europeana/salmon/items.jsonl`
plus thumbnails. Options are in the [user guide](user_guide.md#1-harvest-from-europeana).

## 9. Index and search

```bash
docker compose run --rm embed python scripts/graph_search.py index data/europeana/salmon/items.jsonl
docker compose run --rm embed python scripts/graph_search.py search "salmon fishing boats" -k 5
docker compose run --rm embed python scripts/graph_search.py search "a fish on a plate" --label Image -k 5
```

On 4 CPU cores without a GPU, indexing the default harvest (151 items, 94
images, 376 nodes) took 17 minutes; 300 items with 295 images took 45. A GPU
is much faster. Results list
items and images with their linked collection, institution and creator.

Then start the web app and open http://localhost:8080:

```bash
docker compose up -d web
```

## 10. Optional: NVIDIA GPU

1. Install the NVIDIA driver and the NVIDIA Container Toolkit
   (https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html).
   Docker Desktop on Windows supports GPUs through WSL 2 with a current
   driver.
2. Check: `docker run --rm --gpus all ubuntu nvidia-smi`.
3. In `.env`, set
   `COMPOSE_FILE=compose.yaml:compose.gpu.yaml` (Linux/macOS) or
   `COMPOSE_FILE=compose.yaml;compose.gpu.yaml` (Windows).
4. Run `docker compose run --rm embed`. Models now run in bfloat16 on the GPU.

macOS has no GPU passthrough to Docker, so models run on the CPU there.

## Verification checklist

- [ ] `docker compose version` prints v2+
- [ ] `docker compose run --rm test` → `OK (skipped=3)`
- [ ] `MODELS_DIR` contains `google/embeddinggemma-2` and `intfloat/multilingual-e5-small`
- [ ] `docker compose run --rm embed python -m unittest discover -s tests` → `OK`
- [ ] Sample eval → `recall@10 all=1.000`
- [ ] `data/europeana/<name>/items.jsonl` exists after a harvest
- [ ] `search` returns Items and Images with linked evidence
- [ ] http://localhost:8080 shows pictures for "salmon fishing on rivers"
- [ ] `git status` shows no `.env`, `models/` or `data/europeana/` files

## Updating and cleaning up

```bash
git pull
docker compose build                 # rebuilds only changed layers
docker compose down                  # stop containers, keep the graph
docker compose down -v               # also delete the graph volume
docker builder prune -f              # free build cache
docker image rm campus-ai:embed campus-ai:test   # remove the project images
```

## For maintainers: changing dependencies

```bash
docker run --rm -v "$PWD":/app -w /app python:3.13-slim sh -c "pip install uv && uv add <package> && uv lock"
docker compose build
```

Commit `pyproject.toml` and `uv.lock` together.
