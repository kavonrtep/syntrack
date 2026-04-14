# SynTrack

Genome synteny visualization tool. Multi-genome view with adjacent-pair connection ribbons, region highlight propagation (post-v0.1), and in silico FISH painting (post-v0.1).

- Design: [`docs/DESIGN_v03.md`](docs/DESIGN_v03.md) (authoritative)
- Implementation plan: [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md)
- Test dataset: [`example_data/README.md`](example_data/README.md)

## Status

**v0.1 = Phases 1 + 2 complete.** Browse-only viewer with reorder, block ribbons, and SCM-line LOD switch. No highlight, FISH, or exports yet (deferred to v0.2 per IMPLEMENTATION_PLAN D16).

## Quickstart (development)

This repo's environment has `PIP_TARGET=/envs/pip` and `PYTHONPATH=/envs/pip` set by the hermit sandbox. The `dev.sh` wrapper neutralizes them so the project venv works correctly.

### One-time setup

```bash
# Backend venv
/opt/envs/pydata/bin/python3.12 -m venv .venv
PIP_TARGET= PYTHONPATH= .venv/bin/python -m pip install --force-reinstall uv
./dev.sh uv pip install -e ".[dev]"

# Frontend dependencies
cd frontend && npm install && cd ..

# Test data symlinks (one-time, refresh when source data changes)
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
./dev.sh pytest                      # 159 tests; 7 use --integration via the real pea data
./dev.sh ruff check syntrack tests
./dev.sh ruff format syntrack tests
./dev.sh mypy

# Frontend
cd frontend
npm test                             # vitest, 21 tests on coords + LOD math
npm run check                        # svelte-check
npm run build                        # production bundle into frontend/dist/
```

## Repo layout

```
syntrack/             Python backend (FastAPI)
frontend/             Svelte 5 + TypeScript + Vite
docs/                 Design + implementation plan
example_data/         Symlinks to the pea pangenome test dataset
tests/                Backend tests (unit + api + integration)
dev.sh                Wrapper that neutralizes PIP_TARGET / PYTHONPATH
```
