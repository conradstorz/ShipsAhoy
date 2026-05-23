# ShipsAhoy

See ships near you using their radio broadcasts — no internet required.

Ships are required by law to continuously broadcast their identity, position,
speed, and heading over radio. ShipsAhoy picks up those signals using an
inexpensive USB dongle and displays live maritime traffic in your browser.

---

## What it does

- Receives live AIS ship broadcasts via an RTL-SDR USB dongle
- Shows a live ship list in your web browser — name, position, speed, status
- Automatically looks up each ship's details (flag, type, photo) from public registries
- *(optional)* Scrolls ship arrivals and departures on an RGB LED matrix display

---

## What you need

| Item | Details |
|------|---------|
| Computer | Raspberry Pi 4, or any Linux/macOS/Windows PC |
| USB dongle | RTL-SDR v3 (~$25) — search "RTL-SDR Blog v3" |
| Antenna | Marine VHF antenna for 162 MHz — often included with the dongle |
| *(optional)* ESP32 + LED panel | For the scrolling ticker display; connects to the Pi via USB-C cable |

---

## Getting started

Full step-by-step instructions are in the setup guides:

| Guide | What it covers |
|-------|---------------|
| [Raspberry Pi Setup](docs/raspberry-pi-setup.md) | Install everything on a Pi, run as background services |
| [ESP32 Flashing](docs/flashing-esp32.md) | Load the LED matrix firmware onto an ESP32 (Windows) |

---

## Quick start

### Raspberry Pi (automated installer)

```bash
git clone https://github.com/conradstorz/ShipsAhoy.git
cd ShipsAhoy
bash setup.sh
```

or as an all-in-one command:

```bash
git clone https://github.com/conradstorz/ShipsAhoy.git && cd ShipsAhoy && bash setup.sh
```

The installer handles everything: system packages, `rtl_ais`, Python environment,
and systemd services that start automatically on boot. Open
`http://<pi-ip>:5000` when it completes.

### Development / manual setup

```bash
# Install rtl_ais (receives AIS radio signals)
sudo apt-get install rtl-ais

# Clone and install
git clone https://github.com/conradstorz/ShipsAhoy.git
cd ShipsAhoy
uv sync

# Start the SDR receiver
rtl_ais -n -T -p 0 -d 0 2>/dev/null &

# Start the services
uv run python -m services.ais_service &
uv run python -m services.enrichment_service &
uv run python -m services.web_service
```

Then open `http://localhost:5000` in your browser.

---

## Uninstalling

To remove ShipsAhoy from a machine:

```bash
bash uninstall.sh
```

The script stops and removes all systemd services, then interactively prompts before removing the `rtl-ais` binary, the `uv` package manager, the dialout group membership, and the repo directory itself.

| Flag | Effect |
|------|--------|
| *(none)* | Interactive — prompts for each optional step |
| `--yes` | Non-interactive — removes everything automatically |
| `--keep-repo` | Skip deletion of the repo directory (even with `--yes`) |

The uninstaller reads `setup/.state` (written during installation) to know exactly what was installed and which user to clean up for. If that file is missing it falls back to safe defaults.

---

## Updating

After pulling new code on the Pi, re-run the service installer to apply any changes
to the systemd unit files:

```bash
git pull
bash setup/05-services.sh
```

> **Why?** The service files in `systemd/` are templates containing placeholders
> like `__USER__` and `__RTLAIS_BIN__`. `setup/05-services.sh` substitutes your
> actual username and binary path before writing to `/etc/systemd/system/`. Copying
> the repo file directly — or running `daemon-reload` without re-running the
> installer — leaves the placeholders in place and the service will fail to start.

---

## Troubleshooting

### Service fails with `status=217/USER` and `spawning __RTLAIS_BIN__`

```
ships-ahoy-rtl-ais.service: Failed at step USER spawning __RTLAIS_BIN__: No such process
ships-ahoy-rtl-ais.service: Main process exited, code=exited, status=217/USER
```

**Cause:** The installed service file still contains the raw template placeholders
(`__USER__`, `__RTLAIS_BIN__`). This happens when the file is updated from git
without going through the installer's substitution step.

**Fix:**

```bash
# Verify the state file from the original install is present
cat setup/.state          # should show INSTALL_USER=, RTLAIS_BIN=, etc.

# Re-install the service files with substitutions applied
bash setup/05-services.sh
```

If `setup/.state` is missing or incomplete, re-run the full installer:

```bash
bash setup.sh
```

---

## How it works

```
SDR dongle → rtl_ais → AIS service ─────────────────┐
                                                     ↓
                        Enrichment service ──→ database ──→ Web UI (browser)
                        Ticker service ←────────────┘    ──→ ESP32 → LED matrix (optional)
```

Four background services share a local SQLite database. The AIS service writes ship positions; enrichment adds names and photos; the web UI and ticker read from it. The ticker sends display commands to the ESP32 over USB-C; a built-in WiFi debug page is available at `http://192.168.4.1` when connected to the `ShipsAhoy-Debug` hotspot.

---

## License

ShipsAhoy is dual-licensed:

- **Open-source:** [AGPL-3.0](LICENSE) for community use
- **Commercial:** contact the author for a paid license — see [LICENSE-COMMERCIAL.md](LICENSE-COMMERCIAL.md)
