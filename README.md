# SynTrack

SynTrack visualizes synteny between genome assemblies in a browser, using
single-copy markers (SCMs) derived from per-genome BLAST tables as the unit of
synteny. Genomes are drawn as stacked tracks; syntenic connections are derived
on demand between adjacent pairs and rendered as ribbons or marker lines
depending on zoom.

It supports interactive reordering, cross-genome region highlighting, in silico
fluorescence in situ hybridization (FISH) marker sets, and export of marker
identifiers for probe design.

- Design: [`docs/DESIGN_v03.md`](docs/DESIGN_v03.md) (authoritative)
- Implementation plan: [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md)
- Test dataset: [`example_data/README.md`](example_data/README.md)

## Status

v0.5.2. Phases 1-4 of the design are implemented: the viewer, region
highlighting, FISH marker sets, the disk-backed pair cache with `syntrack
precompute`, and container distribution. Marker sets are private to the browser
session that created them, so one server can be shared by several users.

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
| Highlight by coordinates | Type `chr1:1,000,000-2,500,000` (or `chr1:from:to`, `chr1 from to`; 1-based) in the header box — region is on the "Color by" reference genome |
| Fade reference coloring | "Fade" slider in the header |
| Download highlighted SCM IDs | ↓ SCM IDs button (TSV: scm_id · present_in · one 0/1 column per genome) |
| Clear highlight | **Esc**, or Reset view |
| Save a highlight as a marker set | ★ Save as set — the set is named after the region and the reference genome |
| Load a marker set from file | Load, in the Marker sets panel — one SCM ID per line, or a TSV whose first column holds them |
| Read a truncated set or genome name | hover the sidebar row |
| Save one set's SCM IDs | ↓ on that set's row (complete set, not the on-screen cap) |
| FISH density preview | FISH preview — whole-genome signal per set; Export PNG writes a high-resolution image |
| Marker-set budget in use | shown in the status bar while sets are loaded |

## Run in a container (recommended for end users)

SynTrack ships as a Docker image on `ghcr.io/kavonrtep/syntrack` and as an
Apptainer SIF attached to each [GitHub Release](https://github.com/kavonrtep/syntrack/releases).
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

# HPC (Apptainer) — substitute the release you want
VERSION=v0.5.2
wget https://github.com/kavonrtep/syntrack/releases/download/$VERSION/syntrack-$VERSION.sif
apptainer run --bind /path/to/data:/path/to/data:ro \
  --env SYNTRACK_CONFIG=$PWD/syntrack_config.yaml \
  syntrack-$VERSION.sif
```

### Several users on one server

Marker sets are held in the server process and namespaced per browser, so two
people using the same instance do not see or overwrite each other's sets. The
set a browser uploads is restored when its page reloads. Sets do not survive a
server restart; re-import the SCM-ID file to recreate one.

Set storage is bounded (128 MB of marker indices across all sessions). The
status bar shows the share in use. Logs name every stored and dropped set; set
`SYNTRACK_LOG_LEVEL=DEBUG` for more detail.

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

After any of the three options, install the git pre-commit hook (ruff lint
+ format + whitespace / EOL hygiene). `./dev.sh setup` does this
automatically; on the manual paths run:

```bash
pre-commit install
# first commit may be slow while pre-commit fetches the hook repos
```

Skip hooks for one commit with `git commit --no-verify` if you must.

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
# listens on http://127.0.0.1:8765 (override with --host / --port, or
# server.host / server.port in the YAML)
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

### Precompute the pair cache (optional)

Deriving a genome pair on first view takes seconds on large datasets. Writing
the cache ahead of time removes that wait:

```bash
./dev.sh syntrack precompute --config example_data/syntrack_config.yaml --pairs adjacent
```

- `-c, --config FILE` — configuration file. Falls back to `$SYNTRACK_CONFIG`.
- `-o, --output DIR` — cache directory. Default: `data.cache_dir` from the config.
- `--pairs TEXT` — `all`, `adjacent`, or an explicit list such as `A:B,B:A`. Default (`all`).

`serve` reads the `.npz` files from the cache directory and skips re-derivation.

### Logging

The server logs to stdout at INFO. `SYNTRACK_LOG_LEVEL=DEBUG` adds per-request
timing spans; the `Server-Timing` response header carries them regardless.
Marker-set storage logs every set stored, dropped or evicted, with the cause.

## Test, lint, build

```bash
# Backend
./dev.sh pytest                      # full suite; integration tests need the pea data linked
./dev.sh pytest -m "not integration" # fast inner loop
./dev.sh ruff check syntrack tests
./dev.sh ruff format syntrack tests
./dev.sh mypy

# Frontend
cd frontend
npm test                             # vitest: coords, LOD, alignment, hit-test, colors, API client,
                                     # marker-set recovery, region parsing, SCM export
npm run check                        # svelte-check
npm run build                        # production bundle into frontend/dist/

# Container
docker build -t syntrack:dev .       # matches the CI image-smoke job
```

Benchmarks are skipped by default:

```bash
./dev.sh pytest tests/bench --benchmark-only
```

Browser flows (screenshots, the SCM-ID download) run under Playwright. The
browser binary is a one-time per-machine install:

```bash
cd frontend
npx playwright install chromium      # ~115 MB
npx playwright test                  # builds dist, starts the server, drives the app
```

See [`docs/ONBOARDING.md`](docs/ONBOARDING.md) for the container requirements of
that step.

## Repo layout

```
syntrack/             Python backend (FastAPI)
frontend/             Svelte 5 + TypeScript + Vite (unit tests + Playwright flows)
docs/                 Design, implementation plan, onboarding
docs/design/          Design notes for individual features
deploy/               Container deployment: compose template + guide
example_data/         Symlinks to the pea pangenome test dataset
tests/                Backend tests (unit + api + bench + integration)
dev.sh                Hermit-sandbox venv wrapper + ./dev.sh setup bootstrap
.venv-hermit/         Created by ./dev.sh setup (gitignored)
.venv/                Created by your host-side tooling, if any (gitignored)
```

## License

GNU General Public License v3.0 or later. The full text is in
[`LICENSE`](LICENSE).

Copyright (C) 2026 Petr Novak, Biology Centre CAS, Laboratory of Molecular
Cytogenetics.

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version. It is distributed without any warranty; see the License for details.
