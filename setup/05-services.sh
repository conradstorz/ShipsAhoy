#!/usr/bin/env bash
# Phase 05 — Systemd service installation.
# Installs unit files, enables and starts the four core services.
# Ticker is installed but left disabled.
# Writes: SERVICES_INSTALLED=yes

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

log_section "Phase 05: Systemd services"

require_state "RTLAIS_BIN"
require_state "INSTALL_USER"
require_state "REPO_DIR"
require_state "VENV_PYTHON"

RTLAIS_BIN="$(state_get "RTLAIS_BIN")"
INSTALL_USER="$(state_get "INSTALL_USER")"
REPO_DIR="$(state_get "REPO_DIR")"

SYSTEMD_DIR="/etc/systemd/system"

UNITS=(
    ships-ahoy-rtl-ais
    ships-ahoy-ais
    ships-ahoy-enrichment
    ships-ahoy-web
    ships-ahoy-ticker
)

for unit in "${UNITS[@]}"; do
    src="${REPO_DIR}/systemd/${unit}.service"
    dst="${SYSTEMD_DIR}/${unit}.service"
    if [[ ! -f "${src}" ]]; then
        log_warn "Template not found, skipping: ${src}"
        continue
    fi
    log_info "Installing ${unit}.service..."
    sed \
        -e "s|__USER__|${INSTALL_USER}|g" \
        -e "s|__REPO_DIR__|${REPO_DIR}|g" \
        -e "s|__RTLAIS_BIN__|${RTLAIS_BIN}|g" \
        "${src}" | sudo tee "${dst}" > /dev/null
done

TARGET_SRC="${REPO_DIR}/systemd/ships-ahoy.target"
TARGET_DST="${SYSTEMD_DIR}/ships-ahoy.target"
if [[ -f "${TARGET_SRC}" ]]; then
    log_info "Installing ships-ahoy.target..."
    sudo cp "${TARGET_SRC}" "${TARGET_DST}"
fi

log_info "Reloading systemd daemon..."
sudo systemctl daemon-reload

CORE_SERVICES=(
    ships-ahoy-rtl-ais
    ships-ahoy-ais
    ships-ahoy-enrichment
    ships-ahoy-web
)

for svc in "${CORE_SERVICES[@]}"; do
    if service_enabled "${svc}"; then
        log_info "${svc}: already enabled — restarting..."
        sudo systemctl restart "${svc}" || log_warn "Restart of ${svc} failed — check journalctl."
    else
        log_info "Enabling and starting ${svc}..."
        sudo systemctl enable "${svc}.service" \
            || die "Failed to enable ${svc}."
        sudo systemctl start "${svc}.service" \
            || die "Failed to start ${svc}."
    fi
done

sudo systemctl enable ships-ahoy.target 2>/dev/null || true

log_info "Ticker service installed but NOT started (requires UART hardware)."
log_info "Enable manually when ready:  sudo systemctl enable --now ships-ahoy-ticker"

state_set "SERVICES_INSTALLED" "yes"
log_info "Phase 05 complete. SERVICES_INSTALLED=yes"
