---
date: 2026-05-04
topic: Raspberry Pi setup scripts
status: approved
supersedes: docs/superpowers/specs/2026-03-19-installer-script-design.md
---

# Raspberry Pi Setup Scripts — Design Spec

## Context

Replaces the monolithic `install.sh` at the repo root with a structured,
self-logging, fault-tolerant setup system. Target: a freshly imaged
headless Raspbian install with SSH working. Workflow: clone the repo,
run `bash setup.sh`.

The previous `install.sh` is removed. `setup.sh` is the new entry point.

---

## Requirements

- **Idempotent** — safe to re-run from the top; each phase skips work
  already done.
- **Self-logging** — all output tees to both the console and
  `setup/install.log` simultaneously. Multiple runs append to the same
  file, separated by a timestamped banner.
- **Fault-tolerant** — transient operations (network fetches, apt,
  git clone, uv sync) are wrapped in exponential-backoff retry. Hard
  failures (wrong OS, binary not found after install, missing state key)
  call `die` immediately.
- **Inter-phase state contract** — phases communicate through
  `setup/.state` (sourceable `KEY=VALUE`). Each phase asserts the keys
  it needs via `require_state` before doing any work.
- **Single entry point** — `bash setup.sh` runs all phases in order.
  Individual phases can also be re-run in isolation for debugging.
- **Verification phase** — final phase actively checks service health
  and web UI reachability; prints a pass/fail checklist.

---

## Directory Structure

```
setup.sh                       ← entry point
setup/
  lib.sh                       ← shared: logging, retry, state I/O, die
  .state                       ← generated; inter-phase key=value contract
  install.log                  ← appended on every run
  01-preflight.sh
  02-system-deps.sh
  03-python.sh
  04-uart.sh
  05-services.sh
  06-verify.sh
```

`.state` is plain sourceable bash. A complete successful install produces:

```bash
INSTALL_USER=pi
REPO_DIR=/home/pi/ShipsAhoy
RTLAIS_BIN=/usr/bin/rtl_ais
UV_BIN=/home/pi/.local/bin/uv
VENV_PYTHON=/home/pi/ShipsAhoy/.venv/bin/python
DIALOUT_STATUS=already_member   # or: added
SERVICES_INSTALLED=yes
VERIFY_STATUS=passed            # or: partial
```

---

## `setup/lib.sh` — Shared Infrastructure

Sourced at the top of every script (orchestrator and all phase scripts).
Requires `LOG_FILE` and `STATE_FILE` to be set in the environment before
sourcing.

### Logging

Every call writes a timestamped line to both stdout and `$LOG_FILE`.

```
[2026-05-04 14:23:01] [INFO]  Installing rtl-ais from package manager...
[2026-05-04 14:23:08] [WARN]  rtl-ais not in apt — building from source
[2026-05-04 14:23:08] [ERROR] make failed after 3 attempts
```

Functions: `log_info`, `log_warn`, `log_error`, `log_section` (prints
a `===` banner and blank lines for readability).

### Hard Failure

`die "message"` — logs at ERROR level, prints the log file path, exits
non-zero. Used for failures where continuing makes no sense.

### Retry

```bash
retry N CMD...
```

Runs `CMD` up to `N` times. On each failure: logs the attempt number,
sleeps an exponentially increasing delay (5s → 10s → 20s … capped at
60s), then retries. Returns non-zero if all attempts fail (caller must
handle, usually with `|| die "..."` ).

Applied to: `apt-get update`, `apt-get install`, `git clone` (source
build), the `uv` installer curl, `uv sync`.

### State I/O

- `state_set KEY VALUE` — appends or replaces `KEY=VALUE` in
  `$STATE_FILE`. Safe to call multiple times with the same key.
- `state_get KEY` — echoes the value; empty string if absent.
- `require_state KEY` — calls `die` if the key is absent or empty.
  Used at the top of each phase to assert preconditions formally.

### Idempotency Helpers

- `cmd_exists NAME` — true if `command -v NAME` succeeds
- `in_group USER GROUP` — true if the user is already in the group
- `service_enabled NAME` — true if `systemctl is-enabled NAME` is
  `enabled`

---

## Phase Scripts

### `01-preflight.sh`

**Preconditions:** none (first phase).

**Checks:**
- `uname -s` == `Linux`
- `$EUID` != 0 (not running as root)
- `sudo` is on PATH
- `$REPO_DIR` contains a `.git` directory

**Writes:** `INSTALL_USER`, `REPO_DIR`

**Idempotency:** pure verification, no system changes — always safe to
re-run.

---

### `02-system-deps.sh`

**Preconditions:** `INSTALL_USER`, `REPO_DIR`

**Steps:**
1. `apt-get update` — `retry 3`
2. Install `git`, `curl` — skipped if `cmd_exists git && cmd_exists curl`
3. Install `rtl-ais`:
   - Skip entirely if `cmd_exists rtl_ais`
   - Try `apt-get install -y rtl-ais` — `retry 3`
   - If not in apt: install build deps, `git clone --depth=1` with
     `retry 3`, `cmake`, `make`, `make install`
   - Hard-fail if binary still not found after install

**Writes:** `RTLAIS_BIN=$(command -v rtl_ais)`

**Idempotency:** `cmd_exists rtl_ais` check means source build is only
attempted once; apt installs are idempotent by default.

---

### `03-python.sh`

**Preconditions:** `REPO_DIR`

**Steps:**
1. Install `uv` — skipped if `cmd_exists uv`. Otherwise `curl -LsSf
   https://astral.sh/uv/install.sh | sh` with `retry 3`. Adds
   `~/.local/bin` to `PATH` for this session.
2. Hard-fail if `uv` still not on PATH after install.
3. `uv sync` from `$REPO_DIR` — `retry 3`.
4. Hard-fail if `.venv/bin/python` does not exist after sync.

**Writes:** `UV_BIN`, `VENV_PYTHON`

**Idempotency:** `uv` installer is idempotent; `uv sync` is idempotent.

---

### `04-uart.sh`

**Preconditions:** `INSTALL_USER`

**Steps:**
1. Check `in_group $INSTALL_USER dialout` — if already member, write
   `DIALOUT_STATUS=already_member` and return.
2. Otherwise: `sudo usermod -aG dialout $INSTALL_USER`, write
   `DIALOUT_STATUS=added`.
3. Log a prominent warning: group change takes effect on next login;
   ticker service will not have serial access until then.

**Writes:** `DIALOUT_STATUS`

---

### `05-services.sh`

**Preconditions:** `RTLAIS_BIN`, `INSTALL_USER`, `REPO_DIR`,
`VENV_PYTHON`

**Steps:**
1. For each of the 5 unit files: `sed` substitutes `__USER__`,
   `__REPO_DIR__`, `__RTLAIS_BIN__` and writes to
   `/etc/systemd/system/`. Overwrites safely — idempotent.
2. Copy `ships-ahoy.target`.
3. `sudo systemctl daemon-reload`.
4. For each core service (`rtl-ais`, `ais`, `enrichment`, `web`):
   - Check `service_enabled NAME` before calling `systemctl enable`
   - `systemctl enable NAME`
   - `systemctl start NAME`
5. Ticker service installed but left disabled. A log note explains the
   manual enable command.

**Writes:** `SERVICES_INSTALLED=yes`

**Idempotency:** enable and start are safe to repeat; overwriting unit
files with identical content is harmless.

---

### `06-verify.sh`

**Preconditions:** `SERVICES_INSTALLED=yes`

**Checks (pass/fail per item, no hard-fail):**
- `systemctl is-active ships-ahoy-rtl-ais`
- `systemctl is-active ships-ahoy-ais`
- `systemctl is-active ships-ahoy-enrichment`
- `systemctl is-active ships-ahoy-web`
- `curl -sf --max-time 10 http://localhost:5000`

If `DIALOUT_STATUS=added`: logs a reminder about the logout requirement
for the ticker service (warning, not a failure).

**Writes:** `VERIFY_STATUS=passed` (all checks green) or
`VERIFY_STATUS=partial` (one or more failed).

The orchestrator reads `VERIFY_STATUS` to set its final exit code — the
full checklist is always printed even if some items fail.

---

## Orchestrator (`setup.sh`)

Does **not** use `set -e`. Manages errors explicitly via exit-code
inspection.

**Startup sequence:**
1. Derive `REPO_DIR` from script location.
2. Ensure `setup/` directory exists.
3. Open log: append `=== RUN START: <timestamp> ===` to
   `setup/install.log`.
4. Redirect all subsequent output: `exec > >(tee -a "$LOG_FILE") 2>&1`
5. Export `LOG_FILE` and `STATE_FILE` for phase subprocess inheritance.

**Phase loop:**

```bash
run_phase() {
    local script="$REPO_DIR/setup/$1"
    log_section "Running $1"
    env LOG_FILE="$LOG_FILE" STATE_FILE="$STATE_FILE" bash "$script"
    local exit_code=$?
    if [[ $exit_code -ne 0 ]]; then
        log_error "Phase $1 failed (exit $exit_code)"
        echo ""
        echo "  ✗ Installation stopped at: $1"
        echo "    Log: $LOG_FILE"
        echo "    Fix the issue above, then re-run:  bash setup.sh"
        echo "    Or re-run just this phase:         bash setup/$1"
        echo ""
        exit $exit_code
    fi
    # Re-source state after each phase to pick up newly written keys
    [[ -f "$STATE_FILE" ]] && source "$STATE_FILE"
}

run_phase 01-preflight.sh
run_phase 02-system-deps.sh
run_phase 03-python.sh
run_phase 04-uart.sh
run_phase 05-services.sh
run_phase 06-verify.sh
```

**Final summary** (sources `.state` for values):

```
============================================================
  ShipsAhoy installation complete
============================================================
  User:     pi
  Repo:     /home/pi/ShipsAhoy
  rtl_ais:  /usr/bin/rtl_ais
  Web UI:   http://192.168.1.42:5000
  Verify:   passed
  Log:      /home/pi/ShipsAhoy/setup/install.log

  Useful commands:
    sudo systemctl status ships-ahoy-ais
    sudo journalctl -u ships-ahoy-ais -f
    sudo systemctl restart ships-ahoy.target
============================================================
```

If `VERIFY_STATUS=partial`: notes which services are down and directs
the user to `journalctl -u <service> -f`.

---

## Existing Files

- `install.sh` (repo root) — **deleted**. `setup.sh` is the new entry
  point.
- `docs/raspberry-pi-setup.md` — updated to reference `bash setup.sh`
  as the installation method; manual systemd steps become an appendix
  ("what the installer does under the hood").

---

## What Is Not In Scope

- RTL-SDR kernel module blacklisting (DVB-T driver) — left as a
  troubleshooting note in the docs, not automated.
- ESP32 firmware flashing — Windows-side workflow, separate concern.
- Network or firewall configuration.
- SSH key setup.
- Ticker service enablement — intentionally manual; requires UART
  hardware and a logout/login after dialout group add.
