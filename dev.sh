#!/usr/bin/env bash
# Run any command inside the hermit-sandbox project venv with the hermit
# environment's PIP_TARGET / PYTHONPATH neutralised.
#
# The venv lives at ./.venv-hermit (not ./.venv) so it doesn't collide with
# a .venv that your outside-sandbox tooling (IDE, host-side uv) may maintain.
# Each context's Python lives on a different path, so a single .venv can't
# serve both.
#
# Usage:
#   ./dev.sh setup                # (re)create .venv-hermit from scratch
#   ./dev.sh <command> [args...]  # run a command in the venv
#
# Examples:
#   ./dev.sh setup
#   ./dev.sh pytest -q
#   ./dev.sh syntrack --help
#   ./dev.sh uv pip install -e ".[dev]"
#   ./dev.sh ruff check syntrack tests
#   ./dev.sh mypy

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/.venv-hermit"
VENV_BIN="${VENV_DIR}/bin"
SANDBOX_PYTHON="/opt/envs/pydata/bin/python3.12"

do_setup() {
  if [[ ! -x "${SANDBOX_PYTHON}" ]]; then
    echo "hermit Python 3.12 not found at ${SANDBOX_PYTHON}" >&2
    exit 1
  fi
  rm -rf "${VENV_DIR}"
  "${SANDBOX_PYTHON}" -m venv "${VENV_DIR}"
  # Bootstrap uv into the venv. PIP_TARGET is unset so the install lands
  # inside the venv instead of hermit's shared pip prefix.
  env -u PIP_TARGET -u PYTHONPATH "${VENV_BIN}/python" -m pip install --quiet \
    --force-reinstall uv
  env -u PIP_TARGET -u PYTHONPATH PATH="${VENV_BIN}:${PATH}" \
    "${VENV_BIN}/uv" pip install --quiet -e ".[dev]"
  echo "venv ready at ${VENV_DIR}"
}

if [[ $# -eq 0 ]]; then
  echo "usage: ./dev.sh setup | <command> [args...]" >&2
  exit 64
fi

if [[ "$1" == "setup" ]]; then
  shift
  do_setup
  exit 0
fi

if [[ ! -x "${VENV_BIN}/python" ]]; then
  echo "no venv at ${VENV_DIR} — run: ./dev.sh setup" >&2
  exit 1
fi

cmd="$1"; shift
if [[ -x "${VENV_BIN}/${cmd}" ]]; then
  exe="${VENV_BIN}/${cmd}"
else
  exe="${cmd}"
fi

exec env -u PIP_TARGET -u PYTHONPATH PATH="${VENV_BIN}:${PATH}" "${exe}" "$@"
