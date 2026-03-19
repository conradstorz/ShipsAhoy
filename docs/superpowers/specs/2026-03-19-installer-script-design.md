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

The script detects its own location with:

```bash
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
```

So it works regardless of where the repo was cloned.

---

## Phases

### Phase 1 — Preflight Checks

Runs before any system changes are made. Aborts with a clear error message if any hard check fails. The RTL-SDR check is a warning only.

| Check | Method | On failure |
|-------|--------|-----------|
| Not running as root | `[ "$EUID" -ne 0 ]` | Abort: "Run as your normal user, not root." |
| Linux OS | `uname -s` returns `Linux` | Abort: "This installer is for Linux / Raspberry Pi OS only." |
| sudo available | `sudo -v` (prompts for password; caches credentials for subsequent sudo calls) | Abort: "sudo is required. Make sure your user has sudo privileges." |
| RTL-SDR dongle | `lsusb \| grep -q "0bda:2838" \|\| true` | Warning only: "No RTL-SDR dongle detected. Plug it in before starting services." |

The RTL-SDR check uses `|| true` to prevent `set -e` from aborting the script when no dongle is found — grep exits 1 on no match, which would otherwise trigger an immediate exit.

`sudo -v` is used instead of `sudo -n true` because `-n` fails non-interactively if credentials are not already cached.

---

### Phase 2 — System Dependencies

```bash
sudo apt-get update
sudo apt-get install -y rtl-ais curl
```

Install `uv` if not already present, then make it available for the rest of the script without restarting the shell:

```bash
if ! command -v uv &>/dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"
```

`export PATH` is always run (harmless if uv was already installed) so subsequent commands in the script can find `uv` reliably.

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

Configures the Pi's hardware UART for direct ESP32 communication at 921600 baud. Disables Bluetooth to free the full hardware UART (`/dev/ttyAMA0`).

**Config file detection:**

```bash
if [ -f /boot/firmware/config.txt ]; then
    CONFIG=/boot/firmware/config.txt      # Bookworm+
    CMDLINE=/boot/firmware/cmdline.txt
else
    CONFIG=/boot/config.txt               # older Raspberry Pi OS
    CMDLINE=/boot/cmdline.txt
fi
```

**Changes to `$CONFIG`** (each only appended if not already present):

```
enable_uart=1
dtoverlay=disable-bt
```

`dtoverlay=disable-bt` moves Bluetooth off the full UART, making `/dev/ttyAMA0` available at full speed.

**Changes to `$CMDLINE`:**

Remove `console=serial0,115200` if present — frees the UART from the Linux serial console so the ESP32 can use it exclusively.

Implementation uses `sed -i` to strip the token in place. The pattern handles both mid-line (trailing space) and end-of-line positions:

```bash
sudo sed -i 's/console=serial0,[0-9]*[ ]*//g' "$CMDLINE"
```

**Group membership:**

```bash
sudo usermod -aG dialout "$USER"
```

Grants serial port access without requiring sudo at runtime. Takes effect after next login (the reboot at the end covers this).

All UART changes take effect after the reboot prompted in Phase 6.

---

### Phase 5 — Systemd Service Files

The installer writes six unit files to `/etc/systemd/system/`, using the existing `ships-ahoy-*` naming convention already established in the repo's `systemd/` directory:

- `ships-ahoy-rtl-ais.service` — new; runs the `rtl_ais` system binary
- `ships-ahoy-ais.service` — updates existing with correct absolute paths
- `ships-ahoy-enrichment.service` — updates existing with correct absolute paths
- `ships-ahoy-web.service` — updates existing with correct absolute paths
- `ships-ahoy-ticker.service` — updates existing with correct absolute paths + ESP32 port
- `ships-ahoy.target` — updates existing to include `ships-ahoy-rtl-ais.service`

**ExecStart pattern:** All Python services use the venv python with direct file path. This replaces the `uv run python` pattern in the existing `systemd/` files — `uv` is not guaranteed to be on `PATH` inside systemd's environment, whereas the venv path is absolute and reliable:

```
<REPO_DIR>/.venv/bin/python <REPO_DIR>/services/<name>.py --db <REPO_DIR>/ships.db
```

Variables substituted at write time from `$USER` and `$REPO_DIR`.

---

**rtl_ais binary path detection:**

The `rtl_ais` binary may be at `/usr/bin/rtl_ais` (apt install) or `/usr/local/bin/rtl_ais` (built from source). The installer resolves the actual path after Phase 2 installs it:

```bash
RTLAIS_BIN="$(command -v rtl_ais)"
```

This value is substituted into the `ExecStart` of `ships-ahoy-rtl-ais.service`.

**`static/photos` directory:**

The installer creates the photos directory before starting services:

```bash
mkdir -p "$REPO_DIR/static/photos"
```

This ensures enrichment service does not fail on startup due to a missing directory.

---

#### `ships-ahoy-rtl-ais.service` (new)

```ini
[Unit]
Description=ShipsAhoy RTL-AIS SDR receiver
After=network.target

[Service]
Type=simple
User=<USER>
ExecStart=<RTLAIS_BIN> -n -T -p 0 -d 0
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=ships-ahoy.target
```

#### `ships-ahoy-ais.service`

```ini
[Unit]
Description=ShipsAhoy AIS ingest service
After=network.target ships-ahoy-rtl-ais.service
Wants=ships-ahoy-rtl-ais.service

[Service]
Type=simple
User=<USER>
WorkingDirectory=<REPO_DIR>
ExecStart=<REPO_DIR>/.venv/bin/python <REPO_DIR>/services/ais_service.py --db <REPO_DIR>/ships.db
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=ships-ahoy.target
```

`Wants=` (not `Requires=`) matches the existing ticker pattern: AIS ingest degrades gracefully if rtl-ais temporarily dies rather than the whole service chain stopping.

#### `ships-ahoy-enrichment.service`

```ini
[Unit]
Description=ShipsAhoy ship enrichment service
After=network.target

[Service]
Type=simple
User=<USER>
WorkingDirectory=<REPO_DIR>
ExecStart=<REPO_DIR>/.venv/bin/python <REPO_DIR>/services/enrichment_service.py --db <REPO_DIR>/ships.db --photos-dir <REPO_DIR>/static/photos
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=ships-ahoy.target
```

#### `ships-ahoy-web.service`

```ini
[Unit]
Description=ShipsAhoy web UI
After=network.target

[Service]
Type=simple
User=<USER>
WorkingDirectory=<REPO_DIR>
ExecStart=<REPO_DIR>/.venv/bin/python <REPO_DIR>/services/web_service.py --db <REPO_DIR>/ships.db --port 5000
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=ships-ahoy.target
```

#### `ships-ahoy-ticker.service`

```ini
[Unit]
Description=ShipsAhoy LED matrix ticker
# After= is a startup ordering hint only; ticker runs independently once ships.db exists.
After=ships-ahoy-ais.service

[Service]
Type=simple
User=<USER>
WorkingDirectory=<REPO_DIR>
ExecStart=<REPO_DIR>/.venv/bin/python <REPO_DIR>/services/ticker_service.py --db <REPO_DIR>/ships.db --esp32-port /dev/ttyAMA0
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=ships-ahoy.target
```

#### `ships-ahoy.target`

```ini
[Unit]
Description=ShipsAhoy All Services
Wants=ships-ahoy-rtl-ais.service ships-ahoy-ais.service ships-ahoy-ticker.service ships-ahoy-enrichment.service ships-ahoy-web.service

[Install]
WantedBy=multi-user.target
```

---

**After writing all six files:**

```bash
sudo systemctl daemon-reload
sudo systemctl enable ships-ahoy.target
sudo systemctl start ships-ahoy-rtl-ais ships-ahoy-enrichment ships-ahoy-web
# ships-ahoy-ais and ships-ahoy-ticker not started before reboot
# (UART not yet available until reboot activates dtoverlay=disable-bt)
```

`ships-ahoy-rtl-ais` uses USB (not UART) so it can start immediately. AIS ingest and ticker depend on the UART being free, so they start automatically after reboot via the target.

---

### Phase 6 — Completion Summary

```
============================================================
  ShipsAhoy install complete!
============================================================

  Services started now:
    ships-ahoy-rtl-ais    (SDR receiver, running)
    ships-ahoy-enrichment (running)
    ships-ahoy-web        (running)

  Services start after reboot:
    ships-ahoy-ais        (requires UART — active after reboot)
    ships-ahoy-ticker     (requires UART — active after reboot)

  Web UI:  http://<hostname>.local:5000

  A REBOOT IS REQUIRED to activate the UART changes needed
  for the ESP32 LED display.

  Reboot now? [y/N]
============================================================
```

The `<hostname>` is substituted with the output of `hostname`. If the user answers `y`, the script runs `sudo reboot`. Otherwise it exits with a reminder to reboot manually.

---

## Updated `docs/raspberry-pi-setup.md` Structure

| Section | Content |
|---------|---------|
| Prerequisites | Flash Raspberry Pi OS; connect hardware; update packages; clone repo |
| Run the installer | `./install.sh` — one command does everything |
| After reboot | Open browser; verify services with `systemctl status ships-ahoy.target` |
| Appendix: Manual install | Existing step-by-step content preserved for reference |

---

## File Changes

| File | Change |
|------|--------|
| `install.sh` | New file — the installer script (executable) |
| `systemd/ships-ahoy-rtl-ais.service` | New file — unit file template for rtl_ais |
| `systemd/ships-ahoy-ais.service` | Updated — absolute venv paths; ExecStart changed from `uv run python` to `.venv/bin/python`; `After` and `Wants` for `ships-ahoy-rtl-ais.service` added |
| `systemd/ships-ahoy-enrichment.service` | Updated — absolute paths + explicit `--photos-dir` |
| `systemd/ships-ahoy-web.service` | Updated — absolute paths |
| `systemd/ships-ahoy-ticker.service` | Updated — absolute paths + `--esp32-port /dev/ttyAMA0` |
| `systemd/ships-ahoy.target` | Updated — add `ships-ahoy-rtl-ais.service` to `Wants=` |
| `docs/raspberry-pi-setup.md` | Restructured — prerequisites → installer → post-reboot → manual appendix |

---

## Out of Scope

- PPM correction tuning for the RTL-SDR dongle
- Wi-Fi configuration
- Firewall / UFW setup
- HTTPS / reverse proxy for the web UI
- Updating an existing install (script is for fresh installs only)
- Running without an ESP32 (ticker is always installed)
