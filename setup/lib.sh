#!/usr/bin/env bash
# setup/lib.sh — Shared functions sourced by every ShipsAhoy setup script.
# Must be sourced AFTER LOG_FILE, STATE_FILE are exported.
# _log() writes to stdout only; the active tee handles writing to the log file.

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

_ts() { date '+%Y-%m-%d %H:%M:%S'; }

_log() {
    local level="$1"; shift
    printf '[%s] [%s] %s\n' "$(_ts)" "${level}" "$*"
}

log_info()    { _log "INFO " "$@"; }
log_warn()    { _log "WARN " "$@"; }
log_error()   { _log "ERROR" "$@"; }
log_section() {
    echo ""
    _log "=====" "=== $* ==="
    echo ""
}

# ---------------------------------------------------------------------------
# Hard failure — logs error, prints log path, exits non-zero
# ---------------------------------------------------------------------------

die() {
    log_error "$*"
    [[ -n "${LOG_FILE:-}" ]] && log_error "See log for details: ${LOG_FILE}"
    exit 1
}

# ---------------------------------------------------------------------------
# Retry with exponential backoff
# Usage: retry MAX_ATTEMPTS CMD [ARGS...]
# Delays: 5s, 10s, 20s, 40s, 60s (capped). Returns non-zero after MAX_ATTEMPTS.
# Callers should chain: retry N cmd || die "reason"
# ---------------------------------------------------------------------------

retry() {
    local max="$1"; shift
    local attempt=1
    local delay=5

    (( max >= 1 )) || die "retry: MAX_ATTEMPTS must be >= 1 (got ${max})"

    while true; do
        if "$@"; then
            return 0
        fi
        if (( attempt >= max )); then
            log_error "Command failed after ${max} attempt(s): $*"
            return 1
        fi
        log_warn "Attempt ${attempt}/${max} failed. Retrying in ${delay}s..."
        sleep "${delay}"
        (( delay = delay * 2 > 60 ? 60 : delay * 2 ))
        (( attempt++ ))
    done
}

# ---------------------------------------------------------------------------
# State I/O — KEY=VALUE lines in $STATE_FILE
# ---------------------------------------------------------------------------

state_set() {
    local key="$1" val="$2"
    local tmp="${STATE_FILE}.tmp"
    { grep -v "^${key}=" "${STATE_FILE}" 2>/dev/null || true; echo "${key}=${val}"; } > "${tmp}"
    mv "${tmp}" "${STATE_FILE}" || die "state_set: failed to update ${STATE_FILE}"
}

state_get() {
    local key="$1"
    [[ -f "${STATE_FILE}" ]] || { echo ""; return 0; }
    grep "^${key}=" "${STATE_FILE}" 2>/dev/null | tail -1 | cut -d= -f2- || true
}

require_state() {
    local key="$1"
    local val
    val="$(state_get "${key}")"
    if [[ -z "${val}" ]]; then
        die "Required state key '${key}' not found in ${STATE_FILE}. Run preceding phases first."
    fi
}

# ---------------------------------------------------------------------------
# Idempotency helpers
# ---------------------------------------------------------------------------

# True if NAME is on PATH
cmd_exists() { command -v "$1" &>/dev/null; }

# Usage: in_group USER GROUP — true if USER belongs to GROUP
# True if USER is already a member of GROUP
in_group() { id -nG "$1" 2>/dev/null | tr ' ' '\n' | grep -qx "$2"; }

# True if systemd unit NAME is enabled
service_enabled() { systemctl is-enabled "$1" 2>/dev/null | grep -q '^enabled$'; }
