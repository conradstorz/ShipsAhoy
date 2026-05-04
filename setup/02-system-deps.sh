#!/usr/bin/env bash
# Phase 02 — System dependencies.
# Installs git, curl, and rtl-ais (via apt or source build).
# Writes: RTLAIS_BIN

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

log_section "Phase 02: System dependencies"

require_state "INSTALL_USER"
require_state "REPO_DIR"

log_info "Updating package lists..."
retry 3 sudo apt-get update -qq || die "Failed to update package lists after 3 attempts."

if cmd_exists git && cmd_exists curl; then
    log_info "git and curl already installed — skipping."
else
    log_info "Installing git and curl..."
    retry 3 sudo apt-get install -y git curl || die "Failed to install git/curl after 3 attempts."
fi

if cmd_exists rtl_ais; then
    log_info "rtl_ais already installed at $(command -v rtl_ais) — skipping."
else
    if apt-cache show rtl-ais &>/dev/null 2>&1; then
        log_info "Installing rtl-ais from package manager..."
        retry 3 sudo apt-get install -y rtl-ais || die "apt install of rtl-ais failed after 3 attempts."
    else
        log_warn "rtl-ais not found in apt — building from source."
        log_info "Installing build dependencies..."
        retry 3 sudo apt-get install -y build-essential cmake libusb-1.0-0-dev \
            || die "Failed to install build deps after 3 attempts."

        TMP_BUILD="$(mktemp -d)"
        log_info "Cloning rtl-ais source into ${TMP_BUILD}..."
        retry 3 git clone --depth=1 https://github.com/dgiardini/rtl-ais "${TMP_BUILD}/rtl-ais" \
            || die "Failed to clone rtl-ais after 3 attempts."

        log_info "Building rtl-ais..."
        make -C "${TMP_BUILD}/rtl-ais" \
            || die "make failed for rtl-ais source build."

        log_info "Installing rtl-ais..."
        sudo make -C "${TMP_BUILD}/rtl-ais" install \
            || die "make install failed for rtl-ais."

        rm -rf "${TMP_BUILD}"
        log_info "rtl-ais built and installed from source."
    fi

    if ! cmd_exists rtl_ais; then
        die "rtl_ais install appeared to succeed but the binary is not on PATH."
    fi
fi

RTLAIS_BIN="$(command -v rtl_ais)"
state_set "RTLAIS_BIN" "${RTLAIS_BIN}"
log_info "Phase 02 complete. RTLAIS_BIN=${RTLAIS_BIN}"
