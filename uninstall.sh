#!/usr/bin/env bash
# uninstall.sh — ShipsAhoy uninstaller.
#
# Removes everything that setup.sh installed on this machine:
#   1. Stops, disables, and removes all systemd service and target unit files
#   2. Optionally removes the rtl-ais binary
#   3. Optionally removes the uv package manager
#   4. Optionally removes the user from the dialout group
#   5. Optionally removes the repo directory (including the virtualenv and database)
#
# Usage:
#   bash uninstall.sh              # interactive — prompts for each optional step
#   bash uninstall.sh --yes        # non-interactive — removes everything without prompts
#   bash uninstall.sh --keep-repo  # skip repo deletion even with --yes
#
# Run as a normal user (not root); sudo is called internally where needed.

set -uo pipefail

# ── Argument parsing ──────────────────────────────────────────────────────────
UNATTENDED=false
KEEP_REPO=false

for arg in "$@"; do
    case "${arg}" in
        --yes)        UNATTENDED=true  ;;
        --keep-repo)  KEEP_REPO=true   ;;
        --help|-h)
            sed -n '2,20p' "$0" | sed 's/^# \?//'
            exit 0
            ;;
        *)
            echo "Unknown argument: ${arg}"
            echo "Usage: bash uninstall.sh [--yes] [--keep-repo]"
            exit 1
            ;;
    esac
done

# ── Resolve paths ─────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP_DIR="${SCRIPT_DIR}/setup"
STATE_FILE="${SETUP_DIR}/.state"
LOG_FILE="${SETUP_DIR}/uninstall.log"
SYSTEMD_DIR="/etc/systemd/system"

mkdir -p "${SETUP_DIR}"
exec > >(tee -a "${LOG_FILE}") 2>&1
export _SA_TEE=1

# ── Logging helpers ───────────────────────────────────────────────────────────
_ts()       { date '+%Y-%m-%d %H:%M:%S'; }
log_info()  { printf '[%s] [INFO ] %s\n' "$(_ts)" "$*"; }
log_warn()  { printf '[%s] [WARN ] %s\n' "$(_ts)" "$*"; }
log_error() { printf '[%s] [ERROR] %s\n' "$(_ts)" "$*"; }
log_section() {
    echo ""
    printf '[%s] [=====] === %s ===\n' "$(_ts)" "$*"
    echo ""
}
die() { log_error "$*"; log_error "Log: ${LOG_FILE}"; exit 1; }

# ── State helpers (read-only) ─────────────────────────────────────────────────
state_get() {
    local key="$1"
    [[ -f "${STATE_FILE}" ]] || { echo ""; return 0; }
    grep "^${key}=" "${STATE_FILE}" 2>/dev/null | tail -1 | cut -d= -f2- || true
}

# ── Interactive prompt ────────────────────────────────────────────────────────
# Returns 0 (yes) or 1 (no).
ask() {
    local prompt="$1"
    local default="${2:-n}"   # 'y' or 'n'

    if [[ "${UNATTENDED}" == "true" ]]; then
        [[ "${default}" == "y" ]] && return 0 || return 1
    fi

    local choices
    [[ "${default}" == "y" ]] && choices="[Y/n]" || choices="[y/N]"

    while true; do
        printf '%s %s ' "${prompt}" "${choices}"
        read -r answer </dev/tty
        answer="${answer:-${default}}"
        case "${answer,,}" in
            y|yes) return 0 ;;
            n|no)  return 1 ;;
            *)     echo "  Please answer y or n." ;;
        esac
    done
}

# ── Safety check ──────────────────────────────────────────────────────────────
if [[ "${EUID}" -eq 0 ]]; then
    die "Do not run as root. Run as your normal user — sudo is called internally."
fi

if [[ "$(uname -s)" != "Linux" ]]; then
    die "This uninstaller only supports Linux (detected: $(uname -s))."
fi

# ── Read install state (best-effort) ──────────────────────────────────────────
INSTALL_USER="$(state_get "INSTALL_USER")"
REPO_DIR_STATE="$(state_get "REPO_DIR")"
RTLAIS_BIN="$(state_get "RTLAIS_BIN")"
DIALOUT_STATUS="$(state_get "DIALOUT_STATUS")"

# Fall back to current values if state file is absent
INSTALL_USER="${INSTALL_USER:-${USER}}"
REPO_DIR_STATE="${REPO_DIR_STATE:-${SCRIPT_DIR}}"

echo ""
echo "==================================================================="
echo "=== ShipsAhoy Uninstaller — $(date '+%Y-%m-%d %H:%M:%S') ==="
echo "==================================================================="
echo ""
log_info "Repo directory : ${REPO_DIR_STATE}"
log_info "Install user   : ${INSTALL_USER}"
[[ -n "${RTLAIS_BIN}" ]] && log_info "rtl_ais binary : ${RTLAIS_BIN}" || log_info "rtl_ais binary : (not recorded in state)"
echo ""

if ! ${UNATTENDED}; then
    echo "This will remove ShipsAhoy from this machine."
    echo "You will be asked before each optional step."
    echo ""
    if ! ask "Continue with uninstall?" "y"; then
        echo "Aborted."
        exit 0
    fi
fi

# ═══════════════════════════════════════════════════════════════════════════════
# Step 1 — Systemd services
# ═══════════════════════════════════════════════════════════════════════════════
log_section "Step 1: Stopping and removing systemd services"

UNITS=(
    ships-ahoy-rtl-ais
    ships-ahoy-ais
    ships-ahoy-enrichment
    ships-ahoy-web
    ships-ahoy-ticker
)
TARGET="ships-ahoy"

if ! command -v systemctl &>/dev/null; then
    log_warn "systemctl not found — skipping service removal."
else
    for unit in "${UNITS[@]}"; do
        svc="${unit}.service"
        unit_file="${SYSTEMD_DIR}/${svc}"

        # Stop
        if systemctl is-active --quiet "${svc}" 2>/dev/null; then
            log_info "Stopping ${svc}..."
            sudo systemctl stop "${svc}" || log_warn "Could not stop ${svc} (may already be stopped)."
        else
            log_info "${svc}: not running — skip stop."
        fi

        # Disable
        if systemctl is-enabled --quiet "${svc}" 2>/dev/null; then
            log_info "Disabling ${svc}..."
            sudo systemctl disable "${svc}" || log_warn "Could not disable ${svc}."
        else
            log_info "${svc}: not enabled — skip disable."
        fi

        # Remove unit file
        if [[ -f "${unit_file}" ]]; then
            log_info "Removing ${unit_file}..."
            sudo rm -f "${unit_file}"
        else
            log_info "${unit_file}: not present — skip."
        fi
    done

    # Target
    target_file="${SYSTEMD_DIR}/${TARGET}.target"
    if [[ -f "${target_file}" ]]; then
        log_info "Removing ${target_file}..."
        sudo systemctl disable "${TARGET}.target" 2>/dev/null || true
        sudo rm -f "${target_file}"
    fi

    log_info "Reloading systemd daemon..."
    sudo systemctl daemon-reload
    sudo systemctl reset-failed 2>/dev/null || true
    log_info "Systemd services removed."
fi

# ═══════════════════════════════════════════════════════════════════════════════
# Step 2 — rtl-ais binary
# ═══════════════════════════════════════════════════════════════════════════════
log_section "Step 2: rtl-ais binary"

# Prefer recorded path; fall back to PATH lookup
RTL_BIN="${RTLAIS_BIN:-$(command -v rtl_ais 2>/dev/null || true)}"

if [[ -z "${RTL_BIN}" ]]; then
    log_info "rtl_ais not found on this system — skipping."
elif ask "Remove rtl-ais (${RTL_BIN})? Other SDR tools may depend on it." "n"; then
    # Try apt removal first; fall back to direct binary removal
    if dpkg -l rtl-ais &>/dev/null 2>&1; then
        log_info "Removing rtl-ais via apt..."
        sudo apt-get remove -y rtl-ais || log_warn "apt remove failed — trying manual removal."
    else
        log_info "rtl-ais was installed from source. Removing binary directly..."
        sudo rm -f "${RTL_BIN}"
        # Also clean up any co-installed files from 'make install'
        sudo rm -f /usr/local/lib/librtlsdr* 2>/dev/null || true
        sudo rm -f /usr/local/include/rtl-sdr*.h 2>/dev/null || true
    fi
    log_info "rtl-ais removed."
else
    log_info "rtl-ais kept."
fi

# ═══════════════════════════════════════════════════════════════════════════════
# Step 3 — uv package manager
# ═══════════════════════════════════════════════════════════════════════════════
log_section "Step 3: uv package manager"

UV_BIN="$(command -v uv 2>/dev/null || true)"

if [[ -z "${UV_BIN}" ]]; then
    log_info "uv not found on PATH — skipping."
elif ask "Remove uv (${UV_BIN})? It may be used by other Python projects." "n"; then
    # uv is typically installed to ~/.local/bin or ~/.cargo/bin
    rm -f "${HOME}/.local/bin/uv" "${HOME}/.local/bin/uvx" 2>/dev/null || true
    rm -f "${HOME}/.cargo/bin/uv" "${HOME}/.cargo/bin/uvx" 2>/dev/null || true
    # If still on PATH (e.g. installed system-wide via apt/brew)
    if command -v uv &>/dev/null; then
        log_warn "uv is still on PATH after removing from ~/.local/bin and ~/.cargo/bin."
        log_warn "You may need to remove it manually: $(command -v uv)"
    else
        log_info "uv removed."
    fi
else
    log_info "uv kept."
fi

# ═══════════════════════════════════════════════════════════════════════════════
# Step 4 — dialout group membership
# ═══════════════════════════════════════════════════════════════════════════════
log_section "Step 4: dialout group membership"

if [[ "${DIALOUT_STATUS}" == "added" ]]; then
    if ask "Remove '${INSTALL_USER}' from the dialout group? (Added by ShipsAhoy for ESP32 access.)" "n"; then
        sudo gpasswd -d "${INSTALL_USER}" dialout \
            && log_info "Removed ${INSTALL_USER} from dialout group." \
            || log_warn "Could not remove from dialout group — may not have been a member."
        log_warn "Group change takes effect on next login."
    else
        log_info "dialout membership kept."
    fi
else
    log_info "ShipsAhoy did not add this user to dialout (or state not recorded) — skipping."
fi

# ═══════════════════════════════════════════════════════════════════════════════
# Step 5 — Repo directory (virtualenv, database, code)
# ═══════════════════════════════════════════════════════════════════════════════
log_section "Step 5: Repo directory"

if [[ "${KEEP_REPO}" == "true" ]]; then
    log_info "--keep-repo specified — skipping repo removal."
elif ask "Delete the entire repo directory '${REPO_DIR_STATE}'?
  This removes the code, virtualenv (.venv/), database (ships.db), photos, and all logs.
  THIS CANNOT BE UNDONE." "n"; then
    # Extra safety: require explicit confirmation for repo deletion
    if ! ${UNATTENDED}; then
        printf "Type 'delete' to confirm permanent deletion: "
        read -r confirm </dev/tty
        if [[ "${confirm}" != "delete" ]]; then
            log_info "Confirmation not received — repo directory kept."
        else
            log_info "Deleting ${REPO_DIR_STATE}..."
            # Use a subshell so we're not inside the directory we're deleting
            (cd / && sudo rm -rf "${REPO_DIR_STATE}")
            log_info "Repo directory deleted."
        fi
    else
        # --yes without --keep-repo: still require the directory to exist and be sane
        if [[ "${REPO_DIR_STATE}" == "/" ]] || [[ "${REPO_DIR_STATE}" == "${HOME}" ]]; then
            log_warn "Refusing to delete suspicious path '${REPO_DIR_STATE}' — skipping."
        else
            log_info "Deleting ${REPO_DIR_STATE}..."
            (cd / && sudo rm -rf "${REPO_DIR_STATE}")
            log_info "Repo directory deleted."
        fi
    fi
else
    log_info "Repo directory kept."
    # Still clean up the virtualenv and compiled cache to free disk space
    if ask "Remove just the virtualenv (.venv/) and __pycache__ to free disk space?" "y"; then
        rm -rf "${REPO_DIR_STATE}/.venv" 2>/dev/null || true
        find "${REPO_DIR_STATE}" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
        log_info "Virtualenv and cache removed."
    fi
fi

# ═══════════════════════════════════════════════════════════════════════════════
# Done
# ═══════════════════════════════════════════════════════════════════════════════
echo ""
echo "==================================================================="
echo "=== ShipsAhoy Uninstall Complete — $(date '+%Y-%m-%d %H:%M:%S') ==="
echo "==================================================================="
echo ""
log_info "Log written to: ${LOG_FILE}"
echo ""
