#!/usr/bin/env bash
# Phase 04 — UART / serial access.
# Adds the install user to the dialout group for ESP32 serial access.
# Writes: DIALOUT_STATUS (already_member | added)

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

log_section "Phase 04: UART / serial access"

require_state "INSTALL_USER"
INSTALL_USER="$(state_get "INSTALL_USER")"

if in_group "${INSTALL_USER}" dialout; then
    log_info "User '${INSTALL_USER}' is already in the dialout group — skipping."
    state_set "DIALOUT_STATUS" "already_member"
else
    log_info "Adding '${INSTALL_USER}' to the dialout group..."
    sudo usermod -aG dialout "${INSTALL_USER}" \
        || die "Failed to add ${INSTALL_USER} to dialout group."
    state_set "DIALOUT_STATUS" "added"
    log_warn "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    log_warn "  Group change takes effect on NEXT LOGIN."
    log_warn "  Log out and back in before enabling the ticker service."
    log_warn "  Until then, ships-ahoy-ticker will not have serial access."
    log_warn "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
fi

DIALOUT_STATUS="$(state_get "DIALOUT_STATUS")"
log_info "Phase 04 complete. DIALOUT_STATUS=${DIALOUT_STATUS}"
