#!/usr/bin/env bash
# Phase 01 — Pre-flight checks.
# Verifies OS, user, sudo, and git repo. No system changes.
# Writes: INSTALL_USER, REPO_DIR

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

log_section "Phase 01: Pre-flight checks"

if [[ "$(uname -s)" != "Linux" ]]; then
    die "This installer only supports Linux (detected: $(uname -s))."
fi
log_info "OS: Linux ✓"

if [[ "${EUID}" -eq 0 ]]; then
    die "Do not run as root. Run as a normal user — sudo is called internally."
fi
log_info "User: ${USER} (non-root) ✓"

if ! cmd_exists sudo; then
    die "'sudo' is not installed. Install it and ensure ${USER} has sudo access."
fi
log_info "sudo: available ✓"

if [[ ! -d "${REPO_DIR}/.git" ]]; then
    die "No .git directory found at ${REPO_DIR}. Run setup.sh from inside the cloned ShipsAhoy repo."
fi
log_info "Repo: ${REPO_DIR} ✓"

state_set "INSTALL_USER" "${USER}"
state_set "REPO_DIR"     "${REPO_DIR}"

log_info "Phase 01 complete. INSTALL_USER=${USER}, REPO_DIR=${REPO_DIR}"
