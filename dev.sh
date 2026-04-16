#!/usr/bin/env bash
# Run any command inside the appropriate project venv, with the hermit
# sandbox's PIP_TARGET / PYTHONPATH neutralised (a no-op on a regular Linux
# host where those aren't set).
#
# Venv resolution (first match wins, and the chosen venv must have an
# executable python — ``-x`` follows symlinks, so a hermit-built venv with a
# dangling interpreter when invoked from outside the sandbox fails this
# check and falls through):
#   1. ./.venv-hermit     — hermit-sandbox venv, created by `./dev.sh setup`.
#   2. ./.venv            — host-side venv, whatever you manage yourself.
#
# Usage:
#   ./dev.sh setup                # create/recreate .venv-hermit (hermit only)
#   ./dev.sh <command> [args...]  # run a command in the resolved venv
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
HERMIT_VENV_DIR="${SCRIPT_DIR}/.venv-hermit"
HOST_VENV_DIR="${SCRIPT_DIR}/.venv"
SANDBOX_PYTHON="/opt/envs/pydata/bin/python3.12"

resolve_venv() {
  # Echo the first venv dir whose bin/python is a real executable; empty if
  # nothing usable is present.
  if [[ -x "${HERMIT_VENV_DIR}/bin/python" ]]; then
    echo "${HERMIT_VENV_DIR}"
  elif [[ -x "${HOST_VENV_DIR}/bin/python" ]]; then
    echo "${HOST_VENV_DIR}"
  fi
}

do_setup() {
  if [[ ! -x "${SANDBOX_PYTHON}" ]]; then
    echo "hermit Python 3.12 not found at ${SANDBOX_PYTHON}." >&2
    echo "If you're outside the hermit sandbox, create .venv with your own tooling:" >&2
    echo "  uv venv --python 3.12 && uv pip install -e '.[dev]'" >&2
    echo "  # or: python3.12 -m venv .venv && .venv/bin/pip install -e '.[dev]'" >&2
    exit 1
  fi
  rm -rf "${HERMIT_VENV_DIR}"
  "${SANDBOX_PYTHON}" -m venv "${HERMIT_VENV_DIR}"
  env -u PIP_TARGET -u PYTHONPATH "${HERMIT_VENV_DIR}/bin/python" \
    -m pip install --quiet --force-reinstall uv
  env -u PIP_TARGET -u PYTHONPATH PATH="${HERMIT_VENV_DIR}/bin:${PATH}" \
    "${HERMIT_VENV_DIR}/bin/uv" pip install --quiet -e ".[dev]"
  # Install the git pre-commit hook from .pre-commit-config.yaml. Idempotent;
  # rerunning setup on an existing checkout just re-points the hook.
  if [[ -f "${SCRIPT_DIR}/.pre-commit-config.yaml" ]]; then
    env -u PIP_TARGET -u PYTHONPATH PATH="${HERMIT_VENV_DIR}/bin:${PATH}" \
      "${HERMIT_VENV_DIR}/bin/pre-commit" install --install-hooks >/dev/null
    echo "pre-commit hook installed at .git/hooks/pre-commit"
  fi
  echo "venv ready at ${HERMIT_VENV_DIR}"
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

VENV_DIR="$(resolve_venv)"
if [[ -z "${VENV_DIR}" ]]; then
  echo "no usable venv found." >&2
  echo "  inside hermit:  ./dev.sh setup   (creates .venv-hermit)" >&2
  echo "  outside hermit: uv venv --python 3.12 && uv pip install -e '.[dev]'" >&2
  echo "                  # or python3.12 -m venv .venv && .venv/bin/pip install -e '.[dev]'" >&2
  exit 1
fi
VENV_BIN="${VENV_DIR}/bin"

cmd="$1"; shift
if [[ -x "${VENV_BIN}/${cmd}" ]]; then
  exe="${VENV_BIN}/${cmd}"
else
  exe="${cmd}"
fi

exec env -u PIP_TARGET -u PYTHONPATH PATH="${VENV_BIN}:${PATH}" "${exe}" "$@"
