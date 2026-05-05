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
or as an all-in-one command;
git clone https://github.com/conradstorz/ShipsAhoy.git && cd ShipsAhoy && bash setup.sh

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
