#!/usr/bin/env bash
# Phase 06 — Verification.
# Checks each core service and the web UI. Prints a pass/fail checklist.
# Never hard-fails — orchestrator reads VERIFY_STATUS for exit code.
# Writes: VERIFY_STATUS (passed | partial)

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

log_section "Phase 06: Verification"

require_state "SERVICES_INSTALLED"

all_passed=true

check_service() {
    local name="$1"
    if systemctl is-active --quiet "${name}" 2>/dev/null; then
        log_info "  ✓  ${name}"
    else
        log_warn "  ✗  ${name} — not active (check: sudo journalctl -u ${name} -f)"
        all_passed=false
    fi
}

log_info "Service status:"
check_service ships-ahoy-rtl-ais
check_service ships-ahoy-ais
check_service ships-ahoy-enrichment
check_service ships-ahoy-web

log_info "Web UI check (http://localhost:5000):"
if curl -sf --max-time 10 http://localhost:5000 > /dev/null 2>&1; then
    log_info "  ✓  Web UI responding"
else
    log_warn "  ✗  Web UI not responding — ships-ahoy-web may still be starting"
    all_passed=false
fi

DIALOUT_STATUS="$(state_get "DIALOUT_STATUS")"
if [[ "${DIALOUT_STATUS}" == "added" ]]; then
    log_warn ""
    log_warn "  ⚠  dialout group added — LOG OUT AND BACK IN before enabling ticker."
    log_warn "     Then: sudo systemctl enable --now ships-ahoy-ticker"
fi

if "${all_passed}"; then
    state_set "VERIFY_STATUS" "passed"
    log_info "Phase 06 complete. VERIFY_STATUS=passed"
else
    state_set "VERIFY_STATUS" "partial"
    log_warn "Phase 06 complete. VERIFY_STATUS=partial (see warnings above)"
fi
