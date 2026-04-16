# SynTrack

Genome synteny visualization tool. Multi-genome view with adjacent-pair connection ribbons, reference-palette coloring that propagates colour across genomes via SCM identity, double-click synteny alignment, and Ctrl-drag region highlight with cross-genome tick marks + TSV export.

- Design: [`docs/DESIGN_v03.md`](docs/DESIGN_v03.md) (authoritative)
- Implementation plan: [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md)
- Test dataset: [`example_data/README.md`](example_data/README.md)

## Status

**v0.1.3 shipped; v0.2.0 is container-distribution** (published Docker image on GHCR + Apptainer SIF as a GitHub Release asset). Everything from Phase 1 + 2 plus v0.1.1 reference-propagated colors & scoped zoom/pan, v0.1.2 perf fixes & double-click alignment, and v0.1.3 region highlight with fade control and TSV export. User-defined FISH paint sets (§6.3) and Phase 4 (tuning UI, exports, precompute) still deferred.

### Keyboard / pointer cheatsheet

| Action | Gesture |
|---|---|
| Pan | click-drag on a bar |
| Zoom | mouse wheel over a bar |
| Scope pan/zoom to one genome | **Shift** + drag / wheel over that genome's bar |
| Reorder genomes | drag the label strip above a track |
| Toggle a genome on/off | sidebar checkbox |
| Vertical alignment | **double-click** a bar — every other genome shifts to match basewise resolution + syntenic position |
| Highlight region | **Ctrl / Cmd + click-drag** on a bar — shows ticks on every genome that contains a matching SCM |
| Fade reference coloring | "Fade" slider in the header |
| Download highlighted SCM IDs | ↓ SCM IDs button (TSV: scm_id · present_in · one 0/1 column per genome) |
| Clear highlight | **Esc**, or Reset view |

## Run in a container (recommended for end users)

From v0.2.0 SynTrack ships as a Docker image on `ghcr.io/kavonrtep/syntrack`
and as an Apptainer SIF attached to each [GitHub Release](https://github.com/kavonrtep/syntrack/releases).
End-to-end how-to including the compose template, SSH-tunnel recipe for remote
servers, HPC Apptainer usage, mount conventions, and troubleshooting lives in
[`deploy/README.md`](deploy/README.md).

TL;DR:

```bash
# Laptop / server
mkdir syntrack-run && cd syntrack-run
curl -LO https://raw.githubusercontent.com/kavonrtep/syntrack/main/deploy/docker-compose.yml
cp /path/to/your/syntrack_config.yaml .
# edit docker-compose.yml to add `host_path:host_path:ro` mounts for each
# directory referenced by your genomes.csv
docker compose up
# open http://localhost:8765

# HPC (Apptainer)
wget https://github.com/kavonrtep/syntrack/releases/download/v0.2.0/syntrack-v0.2.0.sif
apptainer run --bind /path/to/data:/path/to/data:ro \
  --env SYNTRACK_CONFIG=$PWD/syntrack_config.yaml \
  syntrack-v0.2.0.sif
```

See `deploy/README.md` for the full story.

## Run from source (developers)

### Prerequisites

- Python ≥ 3.12 (any patch version of 3.12 / 3.13 / 3.14 works)
- Node.js ≥ 18 + npm
- `uv` (recommended) — [install options](https://docs.astral.sh/uv/getting-started/installation/)

## Quickstart (development)

### 1. Backend venv

**Inside this repo's hermit sandbox (the usual case here):**

```bash
./dev.sh setup
```

This creates `.venv-hermit/` using the in-sandbox Python 3.12 (`/opt/envs/pydata/bin/python3.12`), bootstraps `uv` inside it, and installs the project in editable mode with dev deps. All subsequent commands in the docs go through `./dev.sh <command>`, which also unsets `PIP_TARGET` / `PYTHONPATH` so the hermit env vars don't leak into the venv.

> **Note.** The hermit-sandbox venv is named `.venv-hermit` so it doesn't collide with a plain `.venv` your outside-sandbox tooling (IDE, host-side `uv`) may maintain. The two can't share a venv because each context resolves Python on a different path. Both names are gitignored. `./dev.sh <cmd>` picks `.venv-hermit` when its interpreter is actually executable (i.e. you're inside hermit), and transparently falls back to `.venv` otherwise — so the same command works in both contexts.

**On a non-hermit Linux box with uv:**

```bash
uv python install 3.12       # skip if 3.12+ is already on PATH
uv venv --python 3.12        # creates ./.venv
uv pip install -e ".[dev]"
```

**On a non-hermit Linux box without uv:**

```bash
python3.12 -m venv .venv     # or python3.13 / python3.14 / python3
.venv/bin/pip install -e ".[dev]"
```

### 2. Frontend dependencies

```bash
cd frontend && npm install && cd ..
```

### 3. Test-data symlinks (one-time, refresh when source data changes)

```bash
./example_data/link_data.sh
```

### Run (two terminals)

Terminal 1 — backend:

```bash
./dev.sh syntrack serve --config example_data/syntrack_config.yaml --dev-cors
# listens on http://127.0.0.1:8765
```

Terminal 2 — frontend (Vite dev server with hot reload, proxies /api → :8765):

```bash
cd frontend && npm run dev
# listens on http://localhost:5173
```

Open <http://localhost:5173> in the browser.

### Verify the data layer (no UI)

```bash
./dev.sh syntrack lint-data --config example_data/syntrack_config.yaml
```

Prints per-genome filtering statistics. Exits non-zero on load errors.

## Test, lint, build

```bash
# Backend
./dev.sh pytest                      # 195 tests; 9 use --integration via the real pea data
./dev.sh ruff check syntrack tests
./dev.sh ruff format syntrack tests
./dev.sh mypy

# Frontend
cd frontend
npm test                             # vitest, 38 tests on coords / LOD / alignment / hit-test / colors
npm run check                        # svelte-check
npm run build                        # production bundle into frontend/dist/

# Container
docker build -t syntrack:dev .       # matches the CI image-smoke job
```

## Repo layout

```
syntrack/             Python backend (FastAPI)
frontend/             Svelte 5 + TypeScript + Vite
docs/                 Design + implementation plan
example_data/         Symlinks to the pea pangenome test dataset
tests/                Backend tests (unit + api + integration)
dev.sh                Hermit-sandbox venv wrapper + ./dev.sh setup bootstrap
.venv-hermit/         Created by ./dev.sh setup (gitignored)
.venv/                Created by your host-side tooling, if any (gitignored)
```
