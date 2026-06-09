# Repository Guidelines

This file owns the operational workflow (commands, style, conventions). For
architecture, the domain model, and the non-negotiable invariants, see
`CLAUDE.md`. Keep the two de-duplicated.

## Project Structure & Module Organization

SynTrack is a Python 3.12 backend plus a Svelte/TypeScript frontend. Backend code lives in `syntrack/`: `api/` contains FastAPI routes, `derive/` contains synteny logic, `io/` parses input files, and `store/` manages genome/SCM data. Backend tests are split into `tests/unit/` and `tests/api/`. Frontend code lives in `frontend/src/`, with canvas helpers in `frontend/src/canvas/` and API code in `frontend/src/api/`. Product/design decisions belong in `docs/`, especially `docs/DESIGN_v03.md`. Example configuration and data helpers live in `example_data/`.

## Build, Test, and Development Commands

- `./dev.sh setup`: create the Python venv and install backend dev dependencies.
- `cd frontend && npm install`: install frontend dependencies from `package-lock.json`.
- `./dev.sh syntrack serve --config example_data/syntrack_config.yaml --dev-cors`: run the API on `127.0.0.1:8765`.
- `cd frontend && npm run dev`: run the Vite frontend on `localhost:5173`.
- `./dev.sh syntrack lint-data --config example_data/syntrack_config.yaml`: validate data without starting the UI.
- `docker build -t syntrack:dev .`: build the container image used by CI smoke checks.

## Coding Style & Naming Conventions

Python uses Ruff with a 100-character line length and Python 3.12 target; run `./dev.sh ruff check syntrack tests` and `./dev.sh ruff format syntrack tests`. Mypy is strict for `syntrack/`, so new functions need complete type annotations. Use snake_case for Python modules, functions, fixtures, and tests. Frontend code uses TypeScript modules and Svelte components; keep components PascalCase and utility files in local style.

## Testing Guidelines

Run backend tests with `./dev.sh pytest` or targeted paths such as `./dev.sh pytest tests/unit/test_pair.py`. For the fast inner loop use `./dev.sh pytest -m "not integration"` — the full suite is ~100s because the `integration` tests derive the real pea data; run the full suite before commits/releases. Integration tests are marked `integration` and depend on `example_data/` symlinks from `./example_data/link_data.sh`. Benchmarks live in `tests/bench/` and are skipped by default (`--benchmark-skip`); run them with `./dev.sh pytest tests/bench --benchmark-only`. Frontend tests use Vitest: `cd frontend && npm test`; type/component checks use `npm run check`. Name Python tests `test_*.py` and frontend tests `*.test.ts`. Add or update tests for every behavior change; there is no separate coverage gate.

## Commit & Pull Request Guidelines

Git history uses short conventional prefixes: `feat:`, `fix:`, `perf:`, `docs:`, and `release:`. Keep commits focused and imperative, for example `fix: preserve genome order after reset`. Pull requests should describe the user-visible change, list backend/frontend/container checks run, link issues when relevant, and include screenshots or short screen recordings for UI changes.

## Agent-Specific Instructions

Prefer existing patterns and docs over new abstractions. Do not commit generated outputs such as `.venv*`, `frontend/dist/`, caches, or local data symlinks. Keep configuration examples in sync when changing config schema or deployment behavior.
