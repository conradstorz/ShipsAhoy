# Pi Setup Scripts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the monolithic `install.sh` with a self-logging, idempotent, fault-tolerant orchestrator + phase-script system that turns a fresh headless Raspbian install into a running ShipsAhoy node.

**Architecture:** A top-level `setup.sh` entry point redirects all output through `tee` (console + log file), then runs six numbered phase scripts as subprocesses in sequence. Each phase sources a shared `setup/lib.sh`, asserts its preconditions via `require_state`, and writes discovered values to `setup/.state` (sourceable `KEY=VALUE`) for subsequent phases to read.

**Tech Stack:** Bash 5, systemd, apt, uv, shellcheck (optional lint)

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `setup.sh` | Create | Orchestrator — tee setup, run_phase loop, final summary |
| `setup/lib.sh` | Create | Shared: logging, retry, state I/O, die, idempotency helpers |
| `setup/01-preflight.sh` | Create | OS/user/sudo checks; writes INSTALL_USER, REPO_DIR |
| `setup/02-system-deps.sh` | Create | apt + rtl-ais (pkg or source); writes RTLAIS_BIN |
| `setup/03-python.sh` | Create | uv install + uv sync; writes UV_BIN, VENV_PYTHON |
| `setup/04-uart.sh` | Create | dialout group; writes DIALOUT_STATUS |
| `setup/05-services.sh` | Create | systemd unit install/enable/start; writes SERVICES_INSTALLED |
| `setup/06-verify.sh` | Create | health checks + web UI ping; writes VERIFY_STATUS |
| `install.sh` | Delete | Superseded by setup.sh |
| `docs/raspberry-pi-setup.md` | Modify | Point to setup.sh; demote manual steps to appendix |

---

## Key Conventions (read before implementing)

**Tee strategy:** The orchestrator runs `exec > >(tee -a "${LOG_FILE}") 2>&1` and exports `_SA_TEE=1`. Phase scripts check for `_SA_TEE` and set up their own tee only when running standalone. `_log()` in lib.sh just echoes to stdout — the active tee always handles the log write.

**set -euo pipefail:** Used in all phase scripts. `retry` returns non-zero on exhaustion; callers must chain with `|| die "message"` to get a useful error before set -e exits the script.

**State file:** Plain `KEY=VALUE` lines, written by `state_set`, read by `state_get` / `require_state`. Values are simple strings (paths, short keywords) with no spaces. Phase scripts source `.state` at startup so state keys become shell variables; `require_state` still reads from the file for formal precondition checks.

**Idempotency:** Every operation checks "is this already done?" before acting. Re-running from scratch is always safe.

---

## Task 1: `setup/lib.sh` — Shared infrastructure

**Files:**
- Create: `setup/lib.sh`
- Create (temp): `setup/test_lib.sh` (deleted after passing)

- [ ] **Step 1.1: Write the lib.sh test first**

Create `setup/test_lib.sh`:

```bash
#!/usr/bin/env bash
# Smoke test for lib.sh. Run: bash setup/test_lib.sh
set -euo pipefail

SETUP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export LOG_FILE="/tmp/shipsahoy-lib-test.log"
export STATE_FILE="/tmp/shipsahoy-lib-test.state"
export _SA_TEE=1   # suppress tee setup inside lib

rm -f "${LOG_FILE}" "${STATE_FILE}"

source "${SETUP_DIR}/lib.sh"

# --- state_set / state_get round-trip ---
state_set "TESTKEY" "hello"
result="$(state_get "TESTKEY")"
[[ "${result}" == "hello" ]] || { echo "FAIL: state_get returned '${result}', want 'hello'"; exit 1; }

# --- state_set overwrites existing key ---
state_set "TESTKEY" "world"
result="$(state_get "TESTKEY")"
[[ "${result}" == "world" ]] || { echo "FAIL: overwrite returned '${result}', want 'world'"; exit 1; }

# --- state_get returns empty string for missing key ---
result="$(state_get "NOSUCHKEY")"
[[ -z "${result}" ]] || { echo "FAIL: missing key returned '${result}', want ''"; exit 1; }

# --- require_state passes when key exists ---
require_state "TESTKEY"

# --- cmd_exists with known command ---
cmd_exists "bash" || { echo "FAIL: cmd_exists bash returned false"; exit 1; }

# --- cmd_exists with nonexistent command ---
cmd_exists "__no_such_cmd_xyz__" && { echo "FAIL: cmd_exists nonexistent returned true"; exit 1; } || true

# --- retry succeeds on first try ---
retry 3 true || { echo "FAIL: retry of 'true' should succeed"; exit 1; }

# --- retry exhausts attempts and returns non-zero ---
attempt_count=0
count_calls() { (( attempt_count++ )); return 1; }
retry 2 count_calls || true   # || true: don't exit on expected failure
[[ "${attempt_count}" -eq 2 ]] || { echo "FAIL: retry called fn ${attempt_count} times, want 2"; exit 1; }

rm -f "${LOG_FILE}" "${STATE_FILE}"
echo "All lib.sh tests passed."
```

- [ ] **Step 1.2: Run the test — confirm it fails because lib.sh does not exist yet**

```bash
bash setup/test_lib.sh
```

Expected: `setup/lib.sh: No such file or directory` (or similar source error)

- [ ] **Step 1.3: Write `setup/lib.sh`**

Create `setup/lib.sh` with this exact content:

```bash
#!/usr/bin/env bash
# setup/lib.sh — Shared functions sourced by every ShipsAhoy setup script.
# Must be sourced AFTER LOG_FILE, STATE_FILE, and _SA_TEE are exported.
# _log() writes to stdout only; the active tee (set up by orchestrator or
# phase standalone preamble) handles writing to the log file.

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

_ts() { date '+%Y-%m-%d %H:%M:%S'; }

_log() {
    local level="$1"; shift
    echo "[$(_ts)] [${level}] $*"
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
    if [[ -f "${STATE_FILE}" ]]; then
        grep -v "^${key}=" "${STATE_FILE}" > "${tmp}" 2>/dev/null || true
        mv "${tmp}" "${STATE_FILE}"
    fi
    echo "${key}=${val}" >> "${STATE_FILE}"
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

# True if USER is already a member of GROUP
in_group() { id -nG "$1" 2>/dev/null | tr ' ' '\n' | grep -qx "$2"; }

# True if systemd unit NAME is enabled
service_enabled() { systemctl is-enabled "$1" 2>/dev/null | grep -q '^enabled$'; }
```

- [ ] **Step 1.4: Run the test — confirm it passes**

```bash
bash setup/test_lib.sh
```

Expected output:
```
All lib.sh tests passed.
```

- [ ] **Step 1.5: Syntax-check lib.sh**

```bash
bash -n setup/lib.sh
```

Expected: no output (clean syntax)

- [ ] **Step 1.6: Delete the test file and commit**

```bash
rm setup/test_lib.sh
git add setup/lib.sh
git commit -m "feat: add setup/lib.sh shared infrastructure (logging, retry, state I/O)"
```

---

## Task 2: `setup/01-preflight.sh`

**Files:**
- Create: `setup/01-preflight.sh`

- [ ] **Step 2.1: Write `setup/01-preflight.sh`**

```bash
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

# ---------------------------------------------------------------------------
log_section "Phase 01: Pre-flight checks"

# 1. Must be Linux
if [[ "$(uname -s)" != "Linux" ]]; then
    die "This installer only supports Linux (detected: $(uname -s))."
fi
log_info "OS: Linux ✓"

# 2. Must not run as root
if [[ "${EUID}" -eq 0 ]]; then
    die "Do not run as root. Run as a normal user — sudo is called internally."
fi
log_info "User: ${USER} (non-root) ✓"

# 3. sudo must be available
if ! cmd_exists sudo; then
    die "'sudo' is not installed. Install it and ensure ${USER} has sudo access."
fi
log_info "sudo: available ✓"

# 4. Must be inside a git repo (sanity-check that we're in the right directory)
if [[ ! -d "${REPO_DIR}/.git" ]]; then
    die "No .git directory found at ${REPO_DIR}. Run setup.sh from inside the cloned ShipsAhoy repo."
fi
log_info "Repo: ${REPO_DIR} ✓"

# ---------------------------------------------------------------------------
state_set "INSTALL_USER" "${USER}"
state_set "REPO_DIR"     "${REPO_DIR}"

log_info "Phase 01 complete. INSTALL_USER=${USER}, REPO_DIR=${REPO_DIR}"
```

- [ ] **Step 2.2: Syntax-check**

```bash
bash -n setup/01-preflight.sh
```

Expected: no output

- [ ] **Step 2.3: Verify idempotency (safe to run twice)**

On a Linux machine, run it once, then run it again without modifying state:

```bash
bash setup/01-preflight.sh
bash setup/01-preflight.sh
```

Expected: both runs print the INFO lines and exit 0. Check that `.state` contains exactly one `INSTALL_USER=` and one `REPO_DIR=` line (no duplicates):

```bash
grep -c "^INSTALL_USER=" setup/.state
```

Expected: `1`

- [ ] **Step 2.4: Commit**

```bash
git add setup/01-preflight.sh
git commit -m "feat: add setup/01-preflight.sh"
```

---

## Task 3: `setup/02-system-deps.sh`

**Files:**
- Create: `setup/02-system-deps.sh`

- [ ] **Step 3.1: Write `setup/02-system-deps.sh`**

```bash
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

# ---------------------------------------------------------------------------
log_section "Phase 02: System dependencies"

require_state "INSTALL_USER"
require_state "REPO_DIR"

# 1. apt-get update
log_info "Updating package lists..."
retry 3 sudo apt-get update -qq || die "Failed to update package lists after 3 attempts."

# 2. git and curl
if cmd_exists git && cmd_exists curl; then
    log_info "git and curl already installed — skipping."
else
    log_info "Installing git and curl..."
    retry 3 sudo apt-get install -y git curl || die "Failed to install git/curl after 3 attempts."
fi

# 3. rtl-ais
if cmd_exists rtl_ais; then
    log_info "rtl_ais already installed at $(command -v rtl_ais) — skipping."
else
    # Try package manager first
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

    # Verify the binary appeared
    if ! cmd_exists rtl_ais; then
        die "rtl_ais install appeared to succeed but the binary is not on PATH."
    fi
fi

# ---------------------------------------------------------------------------
RTLAIS_BIN="$(command -v rtl_ais)"
state_set "RTLAIS_BIN" "${RTLAIS_BIN}"
log_info "Phase 02 complete. RTLAIS_BIN=${RTLAIS_BIN}"
```

- [ ] **Step 3.2: Syntax-check**

```bash
bash -n setup/02-system-deps.sh
```

Expected: no output

- [ ] **Step 3.3: Verify idempotency**

If `rtl_ais` is already installed in your environment, run the script twice:

```bash
bash setup/02-system-deps.sh
bash setup/02-system-deps.sh
```

Second run should log "rtl_ais already installed at ... — skipping." and exit 0.

Check state:

```bash
grep "^RTLAIS_BIN=" setup/.state
```

Expected: `RTLAIS_BIN=/usr/bin/rtl_ais` (or similar)

- [ ] **Step 3.4: Commit**

```bash
git add setup/02-system-deps.sh
git commit -m "feat: add setup/02-system-deps.sh"
```

---

## Task 4: `setup/03-python.sh`

**Files:**
- Create: `setup/03-python.sh`

- [ ] **Step 4.1: Write `setup/03-python.sh`**

```bash
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

# ---------------------------------------------------------------------------
log_section "Phase 03: Python environment"

require_state "REPO_DIR"
REPO_DIR="$(state_get "REPO_DIR")"

# 1. Install uv
if cmd_exists uv; then
    log_info "uv already installed: $(uv --version) — skipping install."
else
    log_info "Installing uv..."
    retry 3 bash -c 'curl -LsSf https://astral.sh/uv/install.sh | sh' \
        || die "Failed to install uv after 3 attempts."

    # The uv installer writes to ~/.local/bin; add to PATH for this session
    export PATH="${HOME}/.local/bin:${PATH}"

    if ! cmd_exists uv; then
        die "uv install appeared to succeed but 'uv' is not on PATH. Open a new shell and re-run."
    fi
    log_info "uv installed: $(uv --version)"
fi

# Ensure ~/.local/bin is in PATH even if uv was already installed
export PATH="${HOME}/.local/bin:${PATH}"

# 2. Install Python dependencies
log_info "Running uv sync in ${REPO_DIR}..."
retry 3 bash -c "cd '${REPO_DIR}' && uv sync" \
    || die "uv sync failed after 3 attempts."

# 3. Verify virtualenv was created
VENV_PYTHON="${REPO_DIR}/.venv/bin/python"
if [[ ! -f "${VENV_PYTHON}" ]]; then
    die "uv sync completed but ${VENV_PYTHON} was not created."
fi
log_info "Virtualenv Python: ${VENV_PYTHON} ✓"

# ---------------------------------------------------------------------------
UV_BIN="$(command -v uv)"
state_set "UV_BIN"      "${UV_BIN}"
state_set "VENV_PYTHON" "${VENV_PYTHON}"
log_info "Phase 03 complete. UV_BIN=${UV_BIN}, VENV_PYTHON=${VENV_PYTHON}"
```

- [ ] **Step 4.2: Syntax-check**

```bash
bash -n setup/03-python.sh
```

Expected: no output

- [ ] **Step 4.3: Verify idempotency**

If `uv` is already installed:

```bash
bash setup/03-python.sh
bash setup/03-python.sh
```

Second run should log "uv already installed" and re-run `uv sync` (idempotent). Both should exit 0.

```bash
grep "^VENV_PYTHON=" setup/.state
```

Expected: path ending in `.venv/bin/python`

- [ ] **Step 4.4: Commit**

```bash
git add setup/03-python.sh
git commit -m "feat: add setup/03-python.sh"
```

---

## Task 5: `setup/04-uart.sh`

**Files:**
- Create: `setup/04-uart.sh`

- [ ] **Step 5.1: Write `setup/04-uart.sh`**

```bash
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

# ---------------------------------------------------------------------------
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
```

- [ ] **Step 5.2: Syntax-check**

```bash
bash -n setup/04-uart.sh
```

Expected: no output

- [ ] **Step 5.3: Verify idempotency**

Run twice on a machine where the user IS in the dialout group:

```bash
bash setup/04-uart.sh
bash setup/04-uart.sh
```

Both runs should log "already in the dialout group — skipping." and exit 0.

```bash
grep "^DIALOUT_STATUS=" setup/.state
```

Expected: `DIALOUT_STATUS=already_member` (or `added`)

- [ ] **Step 5.4: Commit**

```bash
git add setup/04-uart.sh
git commit -m "feat: add setup/04-uart.sh"
```

---

## Task 6: `setup/05-services.sh`

**Files:**
- Create: `setup/05-services.sh`

- [ ] **Step 6.1: Write `setup/05-services.sh`**

```bash
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

# ---------------------------------------------------------------------------
log_section "Phase 05: Systemd services"

require_state "RTLAIS_BIN"
require_state "INSTALL_USER"
require_state "REPO_DIR"
require_state "VENV_PYTHON"

RTLAIS_BIN="$(state_get "RTLAIS_BIN")"
INSTALL_USER="$(state_get "INSTALL_USER")"
REPO_DIR="$(state_get "REPO_DIR")"

SYSTEMD_DIR="/etc/systemd/system"

# Install all five unit files (overwrite is idempotent)
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

# Install the grouping target
TARGET_SRC="${REPO_DIR}/systemd/ships-ahoy.target"
TARGET_DST="${SYSTEMD_DIR}/ships-ahoy.target"
if [[ -f "${TARGET_SRC}" ]]; then
    log_info "Installing ships-ahoy.target..."
    sudo cp "${TARGET_SRC}" "${TARGET_DST}"
fi

log_info "Reloading systemd daemon..."
sudo systemctl daemon-reload

# Enable and start the four core services
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

# Enable the target (allows 'systemctl start ships-ahoy.target')
sudo systemctl enable ships-ahoy.target 2>/dev/null || true

log_info "Ticker service installed but NOT started (requires UART hardware)."
log_info "Enable manually when ready:  sudo systemctl enable --now ships-ahoy-ticker"

# ---------------------------------------------------------------------------
state_set "SERVICES_INSTALLED" "yes"
log_info "Phase 05 complete. SERVICES_INSTALLED=yes"
```

- [ ] **Step 6.2: Syntax-check**

```bash
bash -n setup/05-services.sh
```

Expected: no output

- [ ] **Step 6.3: Commit**

```bash
git add setup/05-services.sh
git commit -m "feat: add setup/05-services.sh"
```

---

## Task 7: `setup/06-verify.sh`

**Files:**
- Create: `setup/06-verify.sh`

- [ ] **Step 7.1: Write `setup/06-verify.sh`**

```bash
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

# ---------------------------------------------------------------------------
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

# Web UI check (with short timeout so the script doesn't hang)
log_info "Web UI check (http://localhost:5000):"
if curl -sf --max-time 10 http://localhost:5000 > /dev/null 2>&1; then
    log_info "  ✓  Web UI responding"
else
    log_warn "  ✗  Web UI not responding — ships-ahoy-web may still be starting"
    all_passed=false
fi

# DIALOUT warning (not a failure)
DIALOUT_STATUS="$(state_get "DIALOUT_STATUS")"
if [[ "${DIALOUT_STATUS}" == "added" ]]; then
    log_warn ""
    log_warn "  ⚠  dialout group added — LOG OUT AND BACK IN before enabling ticker."
    log_warn "     Then: sudo systemctl enable --now ships-ahoy-ticker"
fi

# ---------------------------------------------------------------------------
if "${all_passed}"; then
    state_set "VERIFY_STATUS" "passed"
    log_info "Phase 06 complete. VERIFY_STATUS=passed"
else
    state_set "VERIFY_STATUS" "partial"
    log_warn "Phase 06 complete. VERIFY_STATUS=partial (see warnings above)"
fi
```

- [ ] **Step 7.2: Syntax-check**

```bash
bash -n setup/06-verify.sh
```

Expected: no output

- [ ] **Step 7.3: Commit**

```bash
git add setup/06-verify.sh
git commit -m "feat: add setup/06-verify.sh"
```

---

## Task 8: `setup.sh` orchestrator + delete `install.sh`

**Files:**
- Create: `setup.sh`
- Delete: `install.sh`

- [ ] **Step 8.1: Write `setup.sh`**

```bash
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
# The run separator goes through tee so it appears on both console and log.
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

    # Run phase as subprocess; it inherits LOG_FILE, STATE_FILE, _SA_TEE,
    # and the tee-redirected stdout from this process.
    bash "${script}"
    local exit_code=$?

    if [[ ${exit_code} -ne 0 ]]; then
        log_error "Phase ${name} failed (exit ${exit_code})"
        echo ""
        echo "  ✗ Installation stopped at: ${name}"
        echo "    Log:  ${LOG_FILE}"
        echo ""
        echo "  To continue after fixing the issue:"
        echo "    bash setup.sh                   (re-run all phases)"
        echo "    bash setup/${name}   (re-run only this phase)"
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
```

- [ ] **Step 8.2: Syntax-check `setup.sh`**

```bash
bash -n setup.sh
```

Expected: no output

- [ ] **Step 8.3: Delete `install.sh`**

```bash
git rm install.sh
```

- [ ] **Step 8.4: Make `setup.sh` executable and commit**

```bash
chmod +x setup.sh
git add setup.sh
git commit -m "feat: add setup.sh orchestrator, remove install.sh"
```

---

## Task 9: Make phase scripts executable and update docs

**Files:**
- Modify: `setup/01-preflight.sh` through `setup/06-verify.sh` (chmod)
- Modify: `docs/raspberry-pi-setup.md`

- [ ] **Step 9.1: Make all setup scripts executable**

```bash
chmod +x setup/01-preflight.sh setup/02-system-deps.sh setup/03-python.sh \
         setup/04-uart.sh setup/05-services.sh setup/06-verify.sh
```

- [ ] **Step 9.2: Update `docs/raspberry-pi-setup.md`**

Replace the "Part 8: Configure systemd services" section (which walks through manual unit file creation) with the following content at that position:

```markdown
## Part 8: Install and start services

Run the installer. It handles everything in Parts 1–7 automatically:

```bash
git clone https://github.com/<your-fork>/ShipsAhoy.git
cd ShipsAhoy
bash setup.sh
```

The installer logs everything to `setup/install.log`. If it stops, fix
the issue it reports and re-run `bash setup.sh` — completed phases are
skipped automatically.

### What the installer does (reference)

If you prefer to understand or customise each step, the six phases are:

| Phase | Script | What it does |
|---|---|---|
| 01 | `setup/01-preflight.sh` | Verifies OS, user, sudo |
| 02 | `setup/02-system-deps.sh` | apt update, git, curl, rtl-ais |
| 03 | `setup/03-python.sh` | uv install, uv sync |
| 04 | `setup/04-uart.sh` | dialout group for serial/UART |
| 05 | `setup/05-services.sh` | systemd unit install, enable, start |
| 06 | `setup/06-verify.sh` | health checks, web UI ping |

Each phase script can be re-run in isolation:
```bash
bash setup/03-python.sh
```

### After installation

```bash
# Check service status
sudo systemctl status ships-ahoy-ais

# Follow live logs
sudo journalctl -u ships-ahoy-ais -f

# Stop / start everything
sudo systemctl stop  ships-ahoy.target
sudo systemctl start ships-ahoy.target

# Enable the ESP32 ticker (requires UART hardware + logout/login after install)
sudo systemctl enable --now ships-ahoy-ticker
```

### Troubleshooting

See `setup/install.log` for the full installation log. For service
failures, `journalctl -u <service-name> -f` shows the live output.

**RTL-SDR dongle not detected:** The DVB-T kernel driver may have claimed
the device. Blacklist it:
```bash
echo 'blacklist dvb_usb_rtl28xxu' | sudo tee /etc/modprobe.d/rtl-sdr-blacklist.conf
sudo reboot
```
```

Keep the rest of `raspberry-pi-setup.md` intact (hardware requirements, Parts 1–7 manual steps can remain as reference material under an "Appendix: Manual setup" heading).

- [ ] **Step 9.3: Commit everything**

```bash
git add setup/01-preflight.sh setup/02-system-deps.sh setup/03-python.sh \
        setup/04-uart.sh setup/05-services.sh setup/06-verify.sh \
        docs/raspberry-pi-setup.md
git commit -m "feat: make setup scripts executable, update Pi setup docs"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Covered by |
|---|---|
| Idempotent re-run | Tasks 2–7: each phase checks before acting |
| Self-logging (tee to console + log) | Task 8: orchestrator tee; all phases: standalone tee preamble |
| Retry transient ops (apt, git, curl, uv) | Tasks 3–4: `retry 3` on all network calls |
| Fail-fast on hard failures | All phases: `|| die` after every hard step |
| Orchestrator + phase scripts | Tasks 1–8 |
| `setup/.state` inter-phase contract | Task 1: lib.sh state I/O; all phases: state_set/require_state |
| Phase standalone re-run | All phases: preamble sets own LOG_FILE/STATE_FILE/tee if absent |
| Verification phase | Task 7: service checks + web UI curl |
| `VERIFY_STATUS` drives orchestrator exit code | Task 8: `setup.sh` checks VERIFY_STATUS at end |
| `install.sh` deleted | Task 8: `git rm install.sh` |
| Docs updated | Task 9 |

**No placeholders found.**

**Type/name consistency confirmed:** `state_set`/`state_get`/`require_state`/`cmd_exists`/`in_group`/`service_enabled` names are consistent across lib.sh and all six phase scripts. State keys (`INSTALL_USER`, `REPO_DIR`, `RTLAIS_BIN`, `UV_BIN`, `VENV_PYTHON`, `DIALOUT_STATUS`, `SERVICES_INSTALLED`, `VERIFY_STATUS`) are written and read with identical spelling throughout.
