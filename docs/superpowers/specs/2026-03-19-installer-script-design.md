# ShipsAhoy Installer Script — Design

**Date:** 2026-03-19
**Status:** Approved

---

## Overview

A single `install.sh` bash script at the repo root automates the complete ShipsAhoy setup on a Raspberry Pi from the point of cloning the repository. The installer assumes:

- Raspberry Pi OS (64-bit, Bookworm or later) — with fallback detection for older paths
- RTL-SDR dongle attached via USB
- ESP32 connected directly to the Pi's hardware UART GPIO pins (GPIO 14 TX, GPIO 15 RX)
- LED matrix driven by the ESP32 (always installed; not optional)
- The user has sudo access and is not running the script as root

---

## Script Location and Invocation

```
ShipsAhoy/
└── install.sh       # executable, run from repo root
```

Invocation after cloning:

```bash
cd ShipsAhoy
chmod +x install.sh
./install.sh
```

The script detects its own location with `REPO_DIR="$(cd "$(dirname "$0")" && pwd)"` so it works regardless of where the repo was cloned.

---

## Phases

### Phase 1 — Preflight Checks

Runs before any system changes are made. Aborts with a clear error message if any check fails.

| Check | Pass condition | Failure message |
|-------|---------------|-----------------|
| Not running as root | `$EUID != 0` | "Run as your normal user, not root. sudo will be called internally." |
| Linux OS | `uname` returns `Linux` | "This installer is for Linux / Raspberry Pi OS only." |
| sudo available | `sudo -n true` or user confirms sudo works | "sudo is required. Make sure your user has sudo privileges." |
| RTL-SDR dongle | `lsusb` contains `0bda` (Realtek vendor ID) | Warning only — prints "No RTL-SDR dongle detected. Continuing anyway; plug it in before starting services." |

The RTL-SDR check is a warning, not an abort, since the dongle may be plugged in after install.

---

### Phase 2 — System Dependencies

```bash
sudo apt-get update
sudo apt-get install -y rtl-ais curl
```

Install `uv` if not already present:

```bash
if ! command -v uv &>/dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    source "$HOME/.bashrc"
fi
```

---

### Phase 3 — Python Environment and Tests

```bash
cd "$REPO_DIR"
uv sync
uv run pytest tests/ -v
```

If `pytest` exits non-zero, the script prints:

```
Tests failed. Fix the errors above before completing the install.
```

and exits. This gate ensures a known-good state before writing any system files.

---

### Phase 4 — UART Configuration

Configures the Pi's hardware UART for direct ESP32 communication at 921600 baud.

**Config file detection:**

```bash
if [ -f /boot/firmware/config.txt ]; then
    CONFIG=/boot/firmware/config.txt      # Bookworm+
else
    CONFIG=/boot/config.txt               # older Raspberry Pi OS
fi
```

**Changes to `$CONFIG`** (each only added if not already present):

```
enable_uart=1
dtoverlay=disable-bt
```

`dtoverlay=disable-bt` frees the full hardware UART from Bluetooth. After this, `/dev/ttyAMA0` is the full-speed UART (capable of 921600 baud reliably).

**Changes to `/boot/cmdline.txt`** (or `/boot/firmware/cmdline.txt` on Bookworm):

Remove `console=serial0,115200` if present — frees the UART from the Linux serial console.

**Group membership:**

```bash
sudo usermod -aG dialout "$USER"
```

Grants serial port access without sudo.

All UART changes take effect after the reboot prompted at the end of the script.

---

### Phase 5 — Systemd Service Files

Five unit files written to `/etc/systemd/system/`. All use:
- `User=<detected $USER>`
- `WorkingDirectory=<REPO_DIR>`
- `ExecStart=<REPO_DIR>/.venv/bin/python ...` (the venv created by `uv sync`)
- `Restart=on-failure`
- `RestartSec=5`

#### `shipsahoy-rtl-ais.service`

```ini
[Unit]
Description=ShipsAhoy RTL-AIS SDR receiver
After=network.target

[Service]
Type=simple
User=<USER>
ExecStart=/usr/bin/rtl_ais -n -T -p 0 -d 0
StandardError=null
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

#### `shipsahoy-ais.service`

```ini
[Unit]
Description=ShipsAhoy AIS ingest service
After=shipsahoy-rtl-ais.service
Requires=shipsahoy-rtl-ais.service

[Service]
Type=simple
User=<USER>
WorkingDirectory=<REPO_DIR>
ExecStart=<REPO_DIR>/.venv/bin/python -m services.ais_service
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

#### `shipsahoy-enrichment.service`

```ini
[Unit]
Description=ShipsAhoy ship enrichment service
After=network.target

[Service]
Type=simple
User=<USER>
WorkingDirectory=<REPO_DIR>
ExecStart=<REPO_DIR>/.venv/bin/python -m services.enrichment_service
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

#### `shipsahoy-web.service`

```ini
[Unit]
Description=ShipsAhoy web UI
After=network.target

[Service]
Type=simple
User=<USER>
WorkingDirectory=<REPO_DIR>
ExecStart=<REPO_DIR>/.venv/bin/python -m services.web_service
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

#### `shipsahoy-ticker.service`

```ini
[Unit]
Description=ShipsAhoy LED matrix ticker
After=shipsahoy-ais.service

[Service]
Type=simple
User=<USER>
WorkingDirectory=<REPO_DIR>
ExecStart=<REPO_DIR>/.venv/bin/python -m services.ticker_service --esp32-port /dev/ttyAMA0
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

After writing all five files:

```bash
sudo systemctl daemon-reload
sudo systemctl enable shipsahoy-rtl-ais shipsahoy-ais shipsahoy-enrichment shipsahoy-web shipsahoy-ticker
sudo systemctl start shipsahoy-enrichment shipsahoy-web
# ais and ticker not started yet — UART reboot required first
```

`shipsahoy-ais` and `shipsahoy-ticker` are enabled but not started before reboot, since they depend on the UART being available.

---

### Phase 6 — Completion Summary

The script prints:

```
============================================================
  ShipsAhoy install complete!
============================================================

  Services enabled:
    shipsahoy-rtl-ais    (starts after reboot)
    shipsahoy-ais        (starts after reboot)
    shipsahoy-enrichment (running now)
    shipsahoy-web        (running now)
    shipsahoy-ticker     (starts after reboot)

  Web UI:  http://<hostname>.local:5000

  A REBOOT IS REQUIRED to activate the UART and Bluetooth
  changes needed for the ESP32 LED display.

  Reboot now? [y/N]
============================================================
```

If the user answers `y`, the script runs `sudo reboot`. Otherwise it exits and reminds them to reboot manually.

---

## Updated `raspberry-pi-setup.md`

The guide is restructured as:

1. **Prerequisites** — flash Raspberry Pi OS, connect hardware, update packages, clone repo
2. **Run the installer** — `./install.sh`, one section
3. **After reboot** — open browser, verify services with `systemctl status`
4. **Appendix: Manual install** — existing step-by-step content moved here for reference

---

## File Changes

| File | Change |
|------|--------|
| `install.sh` | New file — the installer script |
| `docs/raspberry-pi-setup.md` | Restructured: prerequisites → installer → post-reboot verification → manual appendix |

---

## Out of Scope

- PPM correction tuning for the RTL-SDR dongle
- Wi-Fi configuration
- Firewall setup
- HTTPS / reverse proxy for the web UI
- Updating an existing install (the script is for fresh installs only)
