# ShipsAhoy Installer Script Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create `install.sh` that fully automates ShipsAhoy setup on a Raspberry Pi from a fresh clone — installing dependencies, configuring UART, writing systemd services, and starting them — with a single command.

**Architecture:** A single bash script with `set -e`, organized into six named phase functions called in sequence. The script detects its own location so it works from any clone path. Service files are generated inline using heredocs with shell variable substitution, then written to `/etc/systemd/system/`. The `systemd/` directory in the repo is updated to serve as human-readable documentation matching the installer output.

**Tech Stack:** Bash, systemd, apt, uv, rtl-ais, Python 3 (.venv)

---

## File Map

| File | Action | Notes |
|------|--------|-------|
| `install.sh` | Create | Main installer — executable |
| `systemd/ships-ahoy-rtl-ais.service` | Create | New unit for rtl_ais binary |
| `systemd/ships-ahoy-ais.service` | Modify | Add After/Wants rtl-ais; switch to `.venv/bin/python` pattern |
| `systemd/ships-ahoy-enrichment.service` | Modify | Switch to `.venv/bin/python` pattern |
| `systemd/ships-ahoy-web.service` | Modify | Switch to `.venv/bin/python` pattern |
| `systemd/ships-ahoy-ticker.service` | Modify | Add `--esp32-port /dev/ttyAMA0`; switch to `.venv/bin/python` |
| `systemd/ships-ahoy.target` | Modify | Add `ships-ahoy-rtl-ais.service` to `Wants=` |
| `docs/raspberry-pi-setup.md` | Modify | Restructure: prerequisites → installer → post-reboot → appendix |

---

## Chunk 1: systemd templates + install.sh skeleton through Phase 3

---

### Task 1: Update systemd template files in repo

The `systemd/` directory contains templates that document what the installer writes. The existing four service files and target must be **fully replaced** — they currently contain hardcoded `/home/pi/ShipsAhoy` paths, `User=pi`, and `uv run python` in ExecStart, all of which are wrong. Write each file from scratch with the content shown below. Do not amend or patch the existing content.

**Files:**
- Create: `systemd/ships-ahoy-rtl-ais.service` (does not exist yet)
- Replace: `systemd/ships-ahoy-ais.service` (full replacement)
- Replace: `systemd/ships-ahoy-enrichment.service` (full replacement)
- Replace: `systemd/ships-ahoy-web.service` (full replacement)
- Replace: `systemd/ships-ahoy-ticker.service` (full replacement)
- Replace: `systemd/ships-ahoy.target` (full replacement)

- [ ] **Step 1: Create `systemd/ships-ahoy-rtl-ais.service`**

```ini
[Unit]
Description=ShipsAhoy RTL-AIS SDR receiver
After=network.target

[Service]
Type=simple
User=__USER__
ExecStart=__RTLAIS_BIN__ -n -T -p 0 -d 0
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=ships-ahoy.target
```

- [ ] **Step 2: Replace `systemd/ships-ahoy-ais.service`**

```ini
[Unit]
Description=ShipsAhoy AIS ingest service
After=network.target ships-ahoy-rtl-ais.service
Wants=ships-ahoy-rtl-ais.service

[Service]
Type=simple
User=__USER__
WorkingDirectory=__REPO_DIR__
ExecStart=__REPO_DIR__/.venv/bin/python __REPO_DIR__/services/ais_service.py --db __REPO_DIR__/ships.db
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=ships-ahoy.target
```

- [ ] **Step 3: Replace `systemd/ships-ahoy-enrichment.service`**

```ini
[Unit]
Description=ShipsAhoy ship enrichment service
After=network.target

[Service]
Type=simple
User=__USER__
WorkingDirectory=__REPO_DIR__
ExecStart=__REPO_DIR__/.venv/bin/python __REPO_DIR__/services/enrichment_service.py --db __REPO_DIR__/ships.db --photos-dir __REPO_DIR__/static/photos
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=ships-ahoy.target
```

- [ ] **Step 4: Replace `systemd/ships-ahoy-web.service`**

```ini
[Unit]
Description=ShipsAhoy web UI
After=network.target

[Service]
Type=simple
User=__USER__
WorkingDirectory=__REPO_DIR__
ExecStart=__REPO_DIR__/.venv/bin/python __REPO_DIR__/services/web_service.py --db __REPO_DIR__/ships.db --port 5000
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=ships-ahoy.target
```

- [ ] **Step 5: Replace `systemd/ships-ahoy-ticker.service`**

```ini
[Unit]
Description=ShipsAhoy LED matrix ticker
# After= is a startup ordering hint only; ticker runs independently once ships.db exists.
After=ships-ahoy-ais.service

[Service]
Type=simple
User=__USER__
WorkingDirectory=__REPO_DIR__
ExecStart=__REPO_DIR__/.venv/bin/python __REPO_DIR__/services/ticker_service.py --db __REPO_DIR__/ships.db --esp32-port /dev/ttyAMA0
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=ships-ahoy.target
```

- [ ] **Step 6: Replace `systemd/ships-ahoy.target`**

```ini
[Unit]
Description=ShipsAhoy All Services
Wants=ships-ahoy-rtl-ais.service ships-ahoy-ais.service ships-ahoy-ticker.service ships-ahoy-enrichment.service ships-ahoy-web.service

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 7: Commit**

```bash
git add systemd/
git commit -m "feat: update systemd templates — venv python, rtl-ais unit, esp32 uart port"
```

---

### Task 2: Create install.sh — skeleton, helpers, and Phase 1 (preflight)

**Files:**
- Create: `install.sh`

- [ ] **Step 1: Create `install.sh` with skeleton and helpers**

```bash
#!/usr/bin/env bash
set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
# Capture the real invoking user BEFORE any sudo calls change $USER context.
# This ensures service files are written with the correct non-root user.
INSTALL_USER="$USER"

# ── Helpers ────────────────────────────────────────────────
info()  { echo "  [+] $*"; }
warn()  { echo "  [!] $*"; }
abort() { echo "" ; echo "  [ERROR] $*" >&2; exit 1; }

header() {
    echo ""
    echo "============================================================"
    echo "  $*"
    echo "============================================================"
}

# ── Phases (stubs — filled in below) ──────────────────────
phase_preflight()    { :; }
phase_system_deps()  { :; }
phase_python()       { :; }
phase_uart()         { :; }
phase_services()     { :; }
phase_done()         { :; }

# ── Main ───────────────────────────────────────────────────
phase_preflight
phase_system_deps
phase_python
phase_uart
phase_services
phase_done
```

- [ ] **Step 2: Verify the skeleton is valid bash**

```bash
bash -n install.sh
```

Expected: no output (no syntax errors).

- [ ] **Step 3: Implement `phase_preflight`**

Replace the `phase_preflight() { :; }` stub with:

```bash
phase_preflight() {
    header "Phase 1: Preflight checks"

    [ "$EUID" -ne 0 ] \
        || abort "Run as your normal user, not root. sudo will be called internally."

    [ "$(uname -s)" = "Linux" ] \
        || abort "This installer is for Linux / Raspberry Pi OS only."

    sudo -v \
        || abort "sudo is required. Make sure your user has sudo privileges."

    if lsusb | grep -q "0bda:2838"; then
        info "RTL-SDR dongle detected."
    else
        warn "No RTL-SDR dongle detected. Plug it in before starting services."
    fi

    info "Preflight checks passed."
}
```

Note: the RTL-SDR check uses `if/else` — bash does not propagate a non-zero exit to `set -e` when the command is inside a conditional, so grep's exit 1 (no match) does not abort the script. This is functionally equivalent to the `|| true` pattern mentioned in the spec; both are correct.

- [ ] **Step 4: Verify syntax again**

```bash
bash -n install.sh
```

Expected: no output.

- [ ] **Step 5: Manually verify preflight logic against known conditions**

Temporarily stub out the other phases so only preflight runs, then:

```bash
# Should succeed (not root, Linux, sudo works)
./install.sh
```

Expected: prints "Preflight checks passed." and then exits cleanly (other phases are stubs).

Restore stubs to `{ :; }` after verifying. Do not commit with them running.

- [ ] **Step 6: Commit**

```bash
git add install.sh
git commit -m "feat: add install.sh skeleton and phase_preflight"
```

---

### Task 3: implement Phase 2 (system deps) and Phase 3 (python + tests)

**Files:**
- Modify: `install.sh`

- [ ] **Step 1: Implement `phase_system_deps`**

Replace the `phase_system_deps() { :; }` stub with:

```bash
phase_system_deps() {
    header "Phase 2: System dependencies"

    sudo apt-get update
    sudo apt-get install -y rtl-ais curl

    if ! command -v uv &>/dev/null; then
        info "Installing uv..."
        curl -LsSf https://astral.sh/uv/install.sh | sh
    else
        info "uv already installed."
    fi
    export PATH="$HOME/.local/bin:$PATH"

    RTLAIS_BIN="$(command -v rtl_ais)" \
        || abort "rtl_ais not found after installation. Check that rtl-ais installed correctly."
    info "rtl_ais found at: $RTLAIS_BIN"

    info "System dependencies ready."
}
```

Note: `RTLAIS_BIN` is declared here and used later in `phase_services`. Because `set -e` is active, the `|| abort` after `command -v rtl_ais` will only trigger if the command fails; the variable will always be set when execution continues.

- [ ] **Step 2: Implement `phase_python`**

Replace the `phase_python() { :; }` stub with:

```bash
phase_python() {
    header "Phase 3: Python environment and tests"

    cd "$REPO_DIR"
    uv sync

    info "Running test suite..."
    if ! uv run pytest tests/ -v; then
        abort "Tests failed. Fix the errors above before completing the install."
    fi

    info "All tests passed. Python environment ready."
}
```

- [ ] **Step 3: Verify syntax**

```bash
bash -n install.sh
```

Expected: no output.

- [ ] **Step 4: Verify `phase_python` works locally (non-Pi verification)**

Since the dev machine has the repo and uv installed, run just this phase in isolation to confirm `uv sync` and `pytest` run correctly:

```bash
cd /path/to/ShipsAhoy
uv sync
uv run pytest tests/ -v
```

Expected: all 268 tests pass.

- [ ] **Step 5: Commit**

```bash
git add install.sh
git commit -m "feat: implement phase_system_deps and phase_python in install.sh"
```

---

## Chunk 2: Phases 4–6 + raspberry-pi-setup.md

---

### Task 4: Implement Phase 4 (UART configuration)

**Files:**
- Modify: `install.sh`

- [ ] **Step 1: Implement `phase_uart`**

Replace the `phase_uart() { :; }` stub with:

```bash
phase_uart() {
    header "Phase 4: UART configuration"

    # Detect boot config path (Bookworm+ vs older Raspberry Pi OS)
    if [ -f /boot/firmware/config.txt ]; then
        CONFIG=/boot/firmware/config.txt
        CMDLINE=/boot/firmware/cmdline.txt
    else
        CONFIG=/boot/config.txt
        CMDLINE=/boot/cmdline.txt
    fi
    info "Boot config: $CONFIG"
    info "Cmdline:     $CMDLINE"

    # Add enable_uart=1 if not already present
    if grep -q "^enable_uart=1" "$CONFIG"; then
        info "enable_uart=1 already set."
    else
        echo "enable_uart=1" | sudo tee -a "$CONFIG" > /dev/null
        info "Added enable_uart=1 to $CONFIG"
    fi

    # Add dtoverlay=disable-bt if not already present
    if grep -q "^dtoverlay=disable-bt" "$CONFIG"; then
        info "dtoverlay=disable-bt already set."
    else
        echo "dtoverlay=disable-bt" | sudo tee -a "$CONFIG" > /dev/null
        info "Added dtoverlay=disable-bt to $CONFIG"
    fi

    # Remove serial console from cmdline.txt
    # Pattern handles both mid-line (followed by space) and end-of-line positions
    if grep -q "console=serial0" "$CMDLINE"; then
        sudo sed -i 's/console=serial0,[0-9]*[ ]*//g' "$CMDLINE"
        info "Removed serial console entry from $CMDLINE"
    else
        info "No serial console entry in $CMDLINE (already clean)."
    fi

    # Add user to dialout group for serial port access
    sudo usermod -aG dialout "$INSTALL_USER"
    info "Added $INSTALL_USER to dialout group."

    info "UART configuration complete. Changes take effect after reboot."
}
```

- [ ] **Step 2: Verify syntax**

```bash
bash -n install.sh
```

Expected: no output.

- [ ] **Step 3: Test UART config logic against temp files (safe, no system changes)**

```bash
# Create temp files mimicking Pi boot files
TMP=$(mktemp -d)
echo "dtparam=audio=on" > "$TMP/config.txt"
echo "console=tty1 console=serial0,115200 root=/dev/mmcblk0p2 rootfstype=ext4" > "$TMP/cmdline.txt"

# Simulate the grep+append logic for config.txt
grep -q "^enable_uart=1" "$TMP/config.txt" || echo "enable_uart=1" >> "$TMP/config.txt"
grep -q "^dtoverlay=disable-bt" "$TMP/config.txt" || echo "dtoverlay=disable-bt" >> "$TMP/config.txt"
cat "$TMP/config.txt"
# Expected: dtparam=audio=on / enable_uart=1 / dtoverlay=disable-bt

# Simulate the sed for cmdline.txt
sed -i 's/console=serial0,[0-9]*[ ]*//g' "$TMP/cmdline.txt"
cat "$TMP/cmdline.txt"
# Expected: "console=tty1 root=/dev/mmcblk0p2 rootfstype=ext4"
# (no trailing space artefacts, serial0 entry gone)

rm -rf "$TMP"
```

Verify the output matches expectations before committing.

- [ ] **Step 4: Test end-of-line position (serial0 at end of line)**

```bash
TMP=$(mktemp -d)
echo "console=tty1 console=serial0,115200" > "$TMP/cmdline.txt"
sed -i 's/console=serial0,[0-9]*[ ]*//g' "$TMP/cmdline.txt"
cat "$TMP/cmdline.txt"
# Expected: "console=tty1 " (acceptable trailing space) or "console=tty1"
# Key: "console=serial0,115200" must be gone, no corruption of other tokens
rm -rf "$TMP"
```

- [ ] **Step 5: Commit**

```bash
git add install.sh
git commit -m "feat: implement phase_uart in install.sh"
```

---

### Task 5: Implement Phase 5 (service files) and Phase 6 (completion)

**Files:**
- Modify: `install.sh`

- [ ] **Step 1: Implement `phase_services`**

Replace the `phase_services() { :; }` stub with:

```bash
phase_services() {
    header "Phase 5: Systemd service files"

    mkdir -p "$REPO_DIR/static/photos"

    PYTHON="$REPO_DIR/.venv/bin/python"

    info "Writing ships-ahoy-rtl-ais.service..."
    sudo tee /etc/systemd/system/ships-ahoy-rtl-ais.service > /dev/null <<EOF
[Unit]
Description=ShipsAhoy RTL-AIS SDR receiver
After=network.target

[Service]
Type=simple
User=$INSTALL_USER
ExecStart=$RTLAIS_BIN -n -T -p 0 -d 0
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=ships-ahoy.target
EOF

    info "Writing ships-ahoy-ais.service..."
    sudo tee /etc/systemd/system/ships-ahoy-ais.service > /dev/null <<EOF
[Unit]
Description=ShipsAhoy AIS ingest service
After=network.target ships-ahoy-rtl-ais.service
Wants=ships-ahoy-rtl-ais.service

[Service]
Type=simple
User=$INSTALL_USER
WorkingDirectory=$REPO_DIR
ExecStart=$PYTHON $REPO_DIR/services/ais_service.py --db $REPO_DIR/ships.db
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=ships-ahoy.target
EOF

    info "Writing ships-ahoy-enrichment.service..."
    sudo tee /etc/systemd/system/ships-ahoy-enrichment.service > /dev/null <<EOF
[Unit]
Description=ShipsAhoy ship enrichment service
After=network.target

[Service]
Type=simple
User=$INSTALL_USER
WorkingDirectory=$REPO_DIR
ExecStart=$PYTHON $REPO_DIR/services/enrichment_service.py --db $REPO_DIR/ships.db --photos-dir $REPO_DIR/static/photos
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=ships-ahoy.target
EOF

    info "Writing ships-ahoy-web.service..."
    sudo tee /etc/systemd/system/ships-ahoy-web.service > /dev/null <<EOF
[Unit]
Description=ShipsAhoy web UI
After=network.target

[Service]
Type=simple
User=$INSTALL_USER
WorkingDirectory=$REPO_DIR
ExecStart=$PYTHON $REPO_DIR/services/web_service.py --db $REPO_DIR/ships.db --port 5000
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=ships-ahoy.target
EOF

    info "Writing ships-ahoy-ticker.service..."
    sudo tee /etc/systemd/system/ships-ahoy-ticker.service > /dev/null <<EOF
[Unit]
Description=ShipsAhoy LED matrix ticker
# After= is a startup ordering hint only; ticker runs independently once ships.db exists.
After=ships-ahoy-ais.service

[Service]
Type=simple
User=$INSTALL_USER
WorkingDirectory=$REPO_DIR
ExecStart=$PYTHON $REPO_DIR/services/ticker_service.py --db $REPO_DIR/ships.db --esp32-port /dev/ttyAMA0
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=ships-ahoy.target
EOF

    info "Writing ships-ahoy.target..."
    sudo tee /etc/systemd/system/ships-ahoy.target > /dev/null <<EOF
[Unit]
Description=ShipsAhoy All Services
Wants=ships-ahoy-rtl-ais.service ships-ahoy-ais.service ships-ahoy-ticker.service ships-ahoy-enrichment.service ships-ahoy-web.service

[Install]
WantedBy=multi-user.target
EOF

    sudo systemctl daemon-reload
    sudo systemctl enable ships-ahoy.target
    sudo systemctl start ships-ahoy-rtl-ais ships-ahoy-enrichment ships-ahoy-web

    info "All services installed and enabled."
    info "ships-ahoy-rtl-ais, ships-ahoy-enrichment, ships-ahoy-web started now."
    info "ships-ahoy-ais and ships-ahoy-ticker will start automatically after reboot."
}
```

- [ ] **Step 2: Implement `phase_done`**

Replace the `phase_done() { :; }` stub with:

```bash
phase_done() {
    echo ""
    echo "============================================================"
    echo "  ShipsAhoy install complete!"
    echo "============================================================"
    echo ""
    echo "  Services started now:"
    echo "    ships-ahoy-rtl-ais    (SDR receiver)"
    echo "    ships-ahoy-enrichment (ship metadata scraper)"
    echo "    ships-ahoy-web        (web UI)"
    echo ""
    echo "  Services start after reboot (require UART):"
    echo "    ships-ahoy-ais        (AIS ingest)"
    echo "    ships-ahoy-ticker     (LED matrix display)"
    echo ""
    echo "  Web UI:  http://$(hostname).local:5000"
    echo ""
    echo "  A REBOOT IS REQUIRED to activate the UART and Bluetooth"
    echo "  changes needed for the ESP32 LED display."
    echo ""
    printf "  Reboot now? [y/N] "
    read -r REBOOT_ANSWER
    if [ "$REBOOT_ANSWER" = "y" ] || [ "$REBOOT_ANSWER" = "Y" ]; then
        sudo reboot
    else
        echo ""
        echo "  Reboot when ready:  sudo reboot"
        echo ""
    fi
}
```

- [ ] **Step 3: Verify final syntax**

```bash
bash -n install.sh
```

Expected: no output.

- [ ] **Step 4: Test service file generation against temp directory**

Run this to verify the heredoc substitution works correctly without writing to `/etc/systemd/system/`:

```bash
TMP=$(mktemp -d)
INSTALL_USER="testuser"
REPO_DIR="/home/testuser/ShipsAhoy"
RTLAIS_BIN="/usr/bin/rtl_ais"
PYTHON="$REPO_DIR/.venv/bin/python"

tee "$TMP/ships-ahoy-ais.service" > /dev/null <<EOF
[Unit]
Description=ShipsAhoy AIS ingest service
After=network.target ships-ahoy-rtl-ais.service
Wants=ships-ahoy-rtl-ais.service

[Service]
Type=simple
User=$INSTALL_USER
WorkingDirectory=$REPO_DIR
ExecStart=$PYTHON $REPO_DIR/services/ais_service.py --db $REPO_DIR/ships.db
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=ships-ahoy.target
EOF

cat "$TMP/ships-ahoy-ais.service"
# Verify substitution worked: no placeholder strings, paths are absolute
grep -c "testuser" "$TMP/ships-ahoy-ais.service"          # Expected: 1 (User=)
grep -c "/home/testuser/ShipsAhoy" "$TMP/ships-ahoy-ais.service"  # Expected: 2+
grep -c "ships-ahoy-rtl-ais" "$TMP/ships-ahoy-ais.service"        # Expected: 2
# Verify Wants= present (not Requires=)
grep "Wants=ships-ahoy-rtl-ais" "$TMP/ships-ahoy-ais.service"     # Expected: match
grep -c "Requires=" "$TMP/ships-ahoy-ais.service"                  # Expected: 0
# Verify [Install] section with WantedBy
grep "WantedBy=ships-ahoy.target" "$TMP/ships-ahoy-ais.service"   # Expected: match

rm -rf "$TMP"
```

- [ ] **Step 5: Make install.sh executable and verify it runs to preflight on dev machine**

```bash
chmod +x install.sh
./install.sh
```

Expected: runs through preflight (prints check results), then stubs out cleanly. If other phases are fully implemented, they will attempt to run — that is fine on a Linux dev machine up through `phase_python` (uv sync + pytest). Stop before `phase_uart` manually if not on a Pi.

- [ ] **Step 6: Commit**

```bash
git add install.sh
git commit -m "feat: implement phase_services and phase_done — install.sh complete"
```

---

### Task 6: Update `docs/raspberry-pi-setup.md`

Restructure the guide so the manual step-by-step content becomes an appendix, replaced at the top by a short prerequisites → install → verify flow. The spec table lists four top-level sections; the implementation adds Managing Services, Updating, and Troubleshooting as practical enhancements — these are additions beyond the spec table, not contradictions of it.

**Files:**
- Modify: `docs/raspberry-pi-setup.md`

- [ ] **Step 1: Replace file content with the new structure**

Write the following as the complete new content of `docs/raspberry-pi-setup.md`:

````markdown
# Raspberry Pi Setup Guide

This guide walks through installing ShipsAhoy on a Raspberry Pi.
The installer handles everything after you clone the repo.

---

## Prerequisites

Before running the installer, complete these steps manually:

### 1. Flash Raspberry Pi OS

Download [Raspberry Pi Imager](https://www.raspberrypi.com/software/) and flash
**Raspberry Pi OS (64-bit, Bookworm)** to a microSD card (16 GB+).
Enable SSH and set your username/password in the Imager settings before flashing.

### 2. Connect hardware

- Insert the microSD card and power on the Pi
- Connect via Ethernet or configure Wi-Fi
- Plug in the RTL-SDR dongle
- Connect the ESP32 to the Pi's UART pins (GPIO 14 TX → ESP32 RX, GPIO 15 RX → ESP32 TX)

### 3. Update and clone the repo

SSH into the Pi (or open a terminal on it) and run:

```bash
sudo apt-get update
sudo apt-get upgrade -y
sudo apt-get install -y git
git clone https://github.com/conradstorz/ShipsAhoy.git
cd ShipsAhoy
```

---

## Run the Installer

```bash
chmod +x install.sh
./install.sh
```

The installer will:

1. Check prerequisites (not root, Linux, sudo access, RTL-SDR dongle)
2. Install `rtl-ais` and `uv` (Python package manager)
3. Install Python dependencies and run all tests
4. Configure the Pi's hardware UART for the ESP32 (disables Bluetooth, frees `/dev/ttyAMA0`)
5. Write and activate all five systemd services
6. Offer to reboot immediately

**A reboot is required.** The UART changes that allow the ESP32 LED display to work do not take effect until the Pi restarts.

---

## After Reboot

Once the Pi has restarted:

### Check all services are running

```bash
systemctl status ships-ahoy.target
```

Check individual services:

```bash
sudo systemctl status ships-ahoy-rtl-ais
sudo systemctl status ships-ahoy-ais
sudo systemctl status ships-ahoy-enrichment
sudo systemctl status ships-ahoy-web
sudo systemctl status ships-ahoy-ticker
```

All five should show `active (running)`.

### View logs

```bash
# Live log for AIS ingest
sudo journalctl -u ships-ahoy-ais -f

# Live log for LED ticker
sudo journalctl -u ships-ahoy-ticker -f
```

### Open the web UI

In a browser on any device on your network:

```
http://<pi-hostname>.local:5000
```

Replace `<pi-hostname>` with the hostname you set in Raspberry Pi Imager (default: `raspberrypi`).

---

## Managing Services

```bash
# Stop all ShipsAhoy services
sudo systemctl stop ships-ahoy.target

# Start all ShipsAhoy services
sudo systemctl start ships-ahoy.target

# Restart a single service
sudo systemctl restart ships-ahoy-web
```

---

## Updating ShipsAhoy

```bash
cd ~/ShipsAhoy
git pull
uv sync
sudo systemctl restart ships-ahoy-ais ships-ahoy-enrichment ships-ahoy-web ships-ahoy-ticker
```

---

## Troubleshooting

### `rtl_test` shows no device

```bash
rtl_test -t
```

If "No supported devices found": try a different USB port, or run `lsusb | grep 0bda` to confirm the Pi sees the dongle.

### No ships appearing after several minutes

- Confirm rtl-ais is running: `sudo systemctl status ships-ahoy-rtl-ais`
- Check AIS ingest logs: `sudo journalctl -u ships-ahoy-ais -n 50`
- Move the antenna outdoors or higher — AIS is line-of-sight

### ESP32 LED display not working

- Confirm the Pi has been rebooted since install
- Check ticker logs: `sudo journalctl -u ships-ahoy-ticker -n 50`
- Verify wiring: Pi GPIO 14 (TX, pin 8) → ESP32 RX; Pi GPIO 15 (RX, pin 10) → ESP32 TX
- Confirm the ESP32 firmware is flashed — see [flashing-esp32.md](flashing-esp32.md)

### Web UI not reachable

- Confirm web service is running: `sudo systemctl status ships-ahoy-web`
- Try accessing by IP instead of hostname: `hostname -I` to find the Pi's address

---

## Appendix: Manual Installation

The steps below document what `install.sh` does internally.
Use these only if you need to install or debug a specific step by hand.

### A1 — Install rtl-ais

```bash
sudo apt-get install -y rtl-ais
```

If not available in your OS version, build from source:

```bash
sudo apt-get install -y build-essential cmake libusb-1.0-0-dev
git clone https://github.com/dgiardini/rtl-ais
cd rtl-ais && make && sudo make install
cd ..
```

### A2 — Install uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc
```

### A3 — Install Python dependencies

```bash
cd ~/ShipsAhoy
uv sync
```

### A4 — Configure UART

Edit `/boot/firmware/config.txt` (or `/boot/config.txt` on older OS) and add:

```
enable_uart=1
dtoverlay=disable-bt
```

Edit `/boot/firmware/cmdline.txt` and remove `console=serial0,115200` if present.

Add your user to the dialout group:

```bash
sudo usermod -aG dialout $USER
```

Reboot for changes to take effect.

### A5 — Running services manually (without systemd)

```bash
# Terminal 1
rtl_ais -n -T -p 0 -d 0 2>/dev/null &

# Terminal 2
cd ~/ShipsAhoy
uv run python services/ais_service.py

# Terminal 3
uv run python services/enrichment_service.py

# Terminal 4
uv run python services/web_service.py

# Terminal 5
uv run python services/ticker_service.py --esp32-port /dev/ttyAMA0
```

### A6 — Systemd service file reference

Service files are written to `/etc/systemd/system/` by `install.sh`.
Templates with placeholder syntax are in the repo's `systemd/` directory.

To manage services as a group:

```bash
sudo systemctl enable ships-ahoy.target
sudo systemctl start ships-ahoy.target
```
````

- [ ] **Step 2: Verify the file renders correctly**

```bash
# Check the file exists and has content
wc -l docs/raspberry-pi-setup.md
# Expected: ~170 lines
```

- [ ] **Step 3: Commit everything**

```bash
git add docs/raspberry-pi-setup.md
git commit -m "docs: restructure raspberry-pi-setup.md around install.sh"
```

---

### Task 7: Final verification and make install.sh executable in git

- [ ] **Step 1: Confirm install.sh is executable**

```bash
chmod +x install.sh
ls -la install.sh
# Expected: -rwxr-xr-x
```

- [ ] **Step 2: Confirm bash syntax one final time**

```bash
bash -n install.sh
```

Expected: no output.

- [ ] **Step 3: Confirm all files committed**

```bash
git status
```

Expected: clean working tree.

- [ ] **Step 4: Verify installer output matches repo templates**

The six files in `systemd/` are documentation templates. Confirm the key fields match what `install.sh` would generate by checking each template file:

```bash
# Each of these should show the .venv/bin/python pattern (not uv run)
grep "ExecStart" systemd/ships-ahoy-ais.service
grep "ExecStart" systemd/ships-ahoy-enrichment.service
grep "ExecStart" systemd/ships-ahoy-web.service
grep "ExecStart" systemd/ships-ahoy-ticker.service

# Confirm rtl-ais service exists and uses __RTLAIS_BIN__ placeholder
grep "ExecStart" systemd/ships-ahoy-rtl-ais.service

# Confirm ais has Wants= for rtl-ais (not Requires=)
grep "Wants=" systemd/ships-ahoy-ais.service
grep -c "Requires=" systemd/ships-ahoy-ais.service   # Expected: 0

# Confirm target lists all 5 services
grep "Wants=" systemd/ships-ahoy.target
```

- [ ] **Step 5: Final commit if anything remains staged**

```bash
git add install.sh
git commit -m "chore: ensure install.sh is executable"
```
