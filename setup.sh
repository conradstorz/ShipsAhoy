#!/usr/bin/env bash
# setup.sh — ShipsAhoy Raspberry Pi installer.
# Usage: bash setup.sh
#
# Runs six phases in sequence. Each phase is a self-contained script in setup/.
# All output goes to both the console and setup/install.log simultaneously.
# On failure: prints which phase failed and how to re-run it, then exits.
#
# Individual phases can be re-run in isolation for debugging:
#   bash setup/03-python.sh

# No set -e here — errors are managed explicitly via exit-code inspection.

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP_DIR="${REPO_DIR}/setup"
LOG_FILE="${SETUP_DIR}/install.log"
STATE_FILE="${SETUP_DIR}/.state"

export LOG_FILE STATE_FILE

# ── Log setup ────────────────────────────────────────────────────────────────
mkdir -p "${SETUP_DIR}"

# Redirect all output through tee: console and log file simultaneously.
exec > >(tee -a "${LOG_FILE}") 2>&1
export _SA_TEE=1

echo ""
echo "==================================================================="
echo "=== ShipsAhoy Setup — $(date '+%Y-%m-%d %H:%M:%S') ==="
echo "==================================================================="
echo ""

source "${SETUP_DIR}/lib.sh"

# ── Phase runner ─────────────────────────────────────────────────────────────
run_phase() {
    local name="$1"
    local script="${SETUP_DIR}/${name}"

    if [[ ! -f "${script}" ]]; then
        log_error "Phase script not found: ${script}"
        exit 1
    fi

    log_section "Running phase: ${name}"

    bash "${script}"
    local exit_code=$?

    if [[ ${exit_code} -ne 0 ]]; then
        log_error "Phase ${name} failed (exit ${exit_code})"
        echo ""
        echo "  ✗ Installation stopped at: ${name}"
        echo "    Log:  ${LOG_FILE}"
        echo ""
        echo "  To continue after fixing the issue:"
        echo "    bash setup.sh                    (re-run all phases)"
        echo "    bash setup/${name}    (re-run only this phase)"
        echo ""
        exit "${exit_code}"
    fi

    # Re-source state so variables written by this phase are available
    # for the final summary below.
    [[ -f "${STATE_FILE}" ]] && source "${STATE_FILE}" 2>/dev/null || true
}

# ── Run all phases ────────────────────────────────────────────────────────────
run_phase 01-preflight.sh
run_phase 02-system-deps.sh
run_phase 03-python.sh
run_phase 04-uart.sh
run_phase 05-services.sh
run_phase 06-verify.sh

# ── Final summary ─────────────────────────────────────────────────────────────
[[ -f "${STATE_FILE}" ]] && source "${STATE_FILE}" 2>/dev/null || true
PI_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"

echo ""
echo "============================================================"
echo "  ShipsAhoy installation complete"
echo "============================================================"
echo "  User:     ${INSTALL_USER:-<unknown>}"
echo "  Repo:     ${REPO_DIR}"
echo "  rtl_ais:  ${RTLAIS_BIN:-<not found>}"
echo "  Web UI:   http://${PI_IP:-<ip>}:5000"
echo "  Verify:   ${VERIFY_STATUS:-<not run>}"
echo "  Log:      ${LOG_FILE}"
echo ""
echo "  Useful commands:"
echo "    sudo systemctl status ships-ahoy-ais"
echo "    sudo journalctl -u ships-ahoy-ais -f"
echo "    sudo systemctl restart ships-ahoy.target"
echo "    sudo systemctl enable --now ships-ahoy-ticker  (after logout/login)"
echo "============================================================"
echo ""

if [[ "${VERIFY_STATUS:-}" == "partial" ]]; then
    echo "  ⚠ One or more checks failed. See warnings in the log:"
    echo "    ${LOG_FILE}"
    echo ""
    exit 1
fi
