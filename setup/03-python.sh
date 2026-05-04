#!/usr/bin/env bash
# Phase 03 — Python environment.
# Installs uv and runs uv sync to create the virtualenv.
# Writes: UV_BIN, VENV_PYTHON

SETUP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SETUP_DIR}/.." && pwd)"

export LOG_FILE="${LOG_FILE:-${SETUP_DIR}/install.log}"
export STATE_FILE="${STATE_FILE:-${SETUP_DIR}/.state}"

if [[ -z "${_SA_TEE:-}" ]]; then
    exec > >(tee -a "${LOG_FILE}") 2>&1
    export _SA_TEE=1
fi

set -euo pipefail
source "${SETUP_DIR}/lib.sh"
[[ -f "${STATE_FILE}" ]] && source "${STATE_FILE}" 2>/dev/null || true

log_section "Phase 03: Python environment"

require_state "REPO_DIR"
REPO_DIR="$(state_get "REPO_DIR")"

if cmd_exists uv; then
    log_info "uv already installed: $(uv --version) — skipping install."
else
    log_info "Installing uv..."
    retry 3 bash -c 'curl -LsSf https://astral.sh/uv/install.sh | sh' \
        || die "Failed to install uv after 3 attempts."

    export PATH="${HOME}/.local/bin:${PATH}"

    if ! cmd_exists uv; then
        die "uv install appeared to succeed but 'uv' is not on PATH. Open a new shell and re-run."
    fi
    log_info "uv installed: $(uv --version)"
fi

export PATH="${HOME}/.local/bin:${PATH}"

log_info "Running uv sync in ${REPO_DIR}..."
retry 3 bash -c "cd '${REPO_DIR}' && uv sync" \
    || die "uv sync failed after 3 attempts."

VENV_PYTHON="${REPO_DIR}/.venv/bin/python"
if [[ ! -f "${VENV_PYTHON}" ]]; then
    die "uv sync completed but ${VENV_PYTHON} was not created."
fi
log_info "Virtualenv Python: ${VENV_PYTHON} ✓"

UV_BIN="$(command -v uv)"
state_set "UV_BIN"      "${UV_BIN}"
state_set "VENV_PYTHON" "${VENV_PYTHON}"
log_info "Phase 03 complete. UV_BIN=${UV_BIN}, VENV_PYTHON=${VENV_PYTHON}"
