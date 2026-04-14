#!/usr/bin/env bash
# Run any command inside the project venv with the hermit sandbox's PIP_TARGET /
# PYTHONPATH neutralised. Usage: ./dev.sh <command> [args...]
#
# Examples:
#   ./dev.sh pytest -q
#   ./dev.sh syntrack --help
#   ./dev.sh uv pip install -e ".[dev]"
#   ./dev.sh ruff check syntrack tests
#   ./dev.sh mypy
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_BIN="${SCRIPT_DIR}/.venv/bin"

if [[ ! -x "${VENV_BIN}/python" ]]; then
  echo "no venv at ${SCRIPT_DIR}/.venv — see README.md quickstart" >&2
  exit 1
fi

if [[ $# -eq 0 ]]; then
  echo "usage: ./dev.sh <command> [args...]" >&2
  exit 64
fi

cmd="$1"; shift
if [[ -x "${VENV_BIN}/${cmd}" ]]; then
  exe="${VENV_BIN}/${cmd}"
else
  exe="${cmd}"
fi

exec env -u PIP_TARGET -u PYTHONPATH PATH="${VENV_BIN}:${PATH}" "${exe}" "$@"
