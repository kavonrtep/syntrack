# SynTrack

Genome synteny visualization tool. Multi-genome view with adjacent-pair connection ribbons, region highlight propagation, and in silico FISH painting.

- Design: [`docs/DESIGN_v03.md`](docs/DESIGN_v03.md) (authoritative)
- Implementation plan: [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md)
- Test dataset: [`example_data/README.md`](example_data/README.md)

## Status

Pre-v0.1 — backend scaffolding in progress. v0.1 will ship Phases 1+2 (browse-only viewer with reorder & block ribbons; no highlight, no FISH, no exports).

## Quickstart (development)

This repo's environment has `PIP_TARGET=/envs/pip` and `PYTHONPATH=/envs/pip` set by the hermit sandbox. Clear them when invoking the project venv:

```bash
# Create venv with Python 3.12
/opt/envs/pydata/bin/python3.12 -m venv .venv

# Install uv into the venv (one-time bootstrap)
PIP_TARGET= PYTHONPATH= .venv/bin/python -m pip install uv

# Sync dependencies (creates uv.lock on first run)
PIP_TARGET= PYTHONPATH= .venv/bin/uv pip install -e ".[dev]"

# Run tests / CLI
PIP_TARGET= PYTHONPATH= .venv/bin/python -m pytest -q
PIP_TARGET= PYTHONPATH= .venv/bin/syntrack --help
```

A `dev.sh` wrapper (TBD) will paper over the env-var dance.
