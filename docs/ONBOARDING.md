# Onboarding — SynTrack development

Start here to get productive. This is the orientation + setup sequence; the
deep docs are cross-referenced rather than repeated.

## Map of the docs

| Doc | Owns |
|-----|------|
| `CLAUDE.md` | Architecture, domain model, and the non-negotiable **invariants**. Read this before changing backend logic. |
| `AGENTS.md` | Commands, coding style, test/commit conventions. The operational reference. |
| `docs/DESIGN_v03.md` | What we build — data model, algorithms, API contract. |
| `docs/IMPLEMENTATION_PLAN.md` | How we build it — stack, repo layout, phased tasks, decisions D1–D16. |
| `README.md` | Install + the two-terminal dev loop. |
| **this file** | First-day setup, the verification loop, and browser verification. |

When the design and the plan conflict, the design wins.

## The environment (hermit sandbox)

Development runs inside a Singularity container (`hermit/bioinfo-agent.sif`,
built from `hermit/bioinfo-agent.def`). The container bakes in Node 22, a
Python 3.12 data env, and CLI bioinfo tools. The host project dir is mounted at
its real path, so paths are identical inside and out.

- The sandbox sets `PIP_TARGET` / `PYTHONPATH` globally; **`./dev.sh` neutralizes
  them**. Always run Python tooling through `./dev.sh` (`./dev.sh pytest`,
  `./dev.sh ruff ...`, `./dev.sh mypy`, `./dev.sh syntrack ...`).
- npm/Vite run normally from `frontend/` (no wrapper).
- Rebuilding the container (only when `bioinfo-agent.def` changes):
  ```bash
  cd hermit
  sudo singularity build bioinfo-agent.sif bioinfo-agent.def
  ./run_agent.sh start && ./run_agent.sh claude
  ```

## First-time setup

```bash
# 1. Python venv (creates .venv-hermit, installs syntrack editable + dev deps,
#    and installs the pre-commit hooks)
./dev.sh setup

# 2. Frontend deps
cd frontend && npm install && cd ..

# 3. Example dataset (integration tests + the dev loop depend on these symlinks)
./example_data/link_data.sh
```

## Run the app (two-terminal dev loop)

```bash
# Terminal 1 — backend API on http://127.0.0.1:8765
./dev.sh syntrack serve --config example_data/syntrack_config.yaml --dev-cors

# Terminal 2 — Vite dev server on http://localhost:5173 (proxies /api → :8765)
cd frontend && npm run dev
```

Open http://localhost:5173. For a production-style run, build the frontend
(`cd frontend && npm run build`) and point the server at it via
`SYNTRACK_FRONTEND_DIR=frontend/dist` so FastAPI serves both API and UI on
:8765.

## Verification loop

**Inner loop (fast — use while iterating):**
```bash
./dev.sh pytest -m "not integration"      # skips the ~100s real-pea integration tests
./dev.sh ruff check syntrack tests
./dev.sh mypy
cd frontend && npm run check && npm test
```

**Before a commit / release (full):**
```bash
./dev.sh pytest                           # full suite incl. integration
cd frontend && npm run check && npm test && npm run build
```

Benchmarks live in `tests/bench/` and are skipped by default:
`./dev.sh pytest tests/bench --benchmark-only [--benchmark-compare=NNNN]`.

A `PostToolUse` hook (`.claude/settings.json`) auto-formats edited Python with
ruff, mirroring pre-commit so commits don't get reformatted out from under you.

## Browser verification (UI screenshots)

**Why:** type-check + build + unit tests don't render a pixel, so visual
regressions (a frozen canvas, wrong FISH colors, a blank render) slip through.
A headless browser drives the real app, screenshots key states, and those PNGs
can be inspected directly — closing that blind spot.

**Requires container v4.1+.** `bioinfo-agent.def` v4.1 added the Chromium
headless shared-library deps (libnss3, libgbm, libatk*, … + fonts-liberation).
Without them the browser downloads but dies with
`error while loading shared libraries: libnspr4.so`. Rebuild the container
(see above) to pick them up. `/usr` is read-only at runtime, so these libs
**must** come from the image — they can't be `apt install`ed in-session.

**Per-project, one-time** (browser binary → `~/.cache/ms-playwright`, which is
in the persistent sandbox home, so it survives container rebuilds). Both deps
are already in `frontend/package.json`; this just (re)installs the binary:
```bash
cd frontend
npm install                        # pulls @playwright/test + playwright
npx playwright install chromium    # ~115 MB, headless-shell
```

**Smoke check it works** (after the container rebuild):
```bash
node -e "const {chromium}=require('playwright');(async()=>{const b=await chromium.launch();const p=await b.newPage();await p.setContent('<h1>ok</h1>');await p.screenshot({path:'/tmp/ok.png'});await b.close();console.log('OK')})()"
```

**Screenshot smoke harness** — landed. `playwright.config.ts` builds `dist`,
serves it + `example_data` through the syntrack server (waiting on `/healthz`),
and `tests/e2e/screenshots.spec.ts` drives a few flows, saving PNGs to
`tests/e2e/screenshots/` (gitignored) for direct inspection. Scoped to
**chromium headless-shell only** (no firefox/webkit). Run it with:
```bash
cd frontend && npm run test:e2e
```
The PNGs are the point — read them back to eyeball the render. The spec asserts
DOM state only (the canvas is data-dependent, so it's not a pixel-diff).

## Conventions

- **Commits:** conventional prefixes — `feat:`, `fix:`, `perf:`, `docs:`,
  `release:`. Imperative, focused. Add a test for every behavior change.
- **Version lives in two files** — `pyproject.toml` and `syntrack/__init__.py`.
  Bump both together; the `/release` flow (`.claude/skills/release/`) does this,
  runs the full suite, commits, and tags `vX.Y.Z`.
- **Invariants** (caps must subsample not head-truncate; opaque SCM-IDs;
  karyotype-agnostic; int32 local / int64 global coords; frontend render paths
  must degrade not throw) are in `CLAUDE.md`. The `syntrack-reviewer` agent
  (`.claude/agents/`) checks a diff against them.
- **Don't commit** generated output: `.venv*`, `frontend/dist/`, caches, the
  `.benchmarks/` dir, or data symlinks.
