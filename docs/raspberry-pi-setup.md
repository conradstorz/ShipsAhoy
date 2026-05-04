# Raspberry Pi Setup Guide

This guide walks through installing and running ShipsAhoy on a Raspberry Pi from scratch.
No prior Linux or Raspberry Pi experience is assumed.

---

## What You Need

### Hardware

- **Raspberry Pi 4** (2 GB RAM or more recommended) with power supply
- **microSD card** (16 GB or larger) with Raspberry Pi OS installed
- **RTL-SDR dongle** (RTL2832U chipset, e.g. RTL-SDR Blog v3, ~$25 USD)
- **Marine VHF antenna** tuned for 162 MHz (AIS channels 87B / 88B)
- **Network connection** (Ethernet or Wi-Fi) for installation and web UI access
- *(optional)* **ESP32 board + LED matrix** — see [`flashing-esp32.md`](flashing-esp32.md) for setup

### Software

- **Raspberry Pi OS** (64-bit, Bookworm or later recommended)
  — download and flash using [Raspberry Pi Imager](https://www.raspberrypi.com/software/)

---

## Part 1 — Prepare the Raspberry Pi

### Step 1.1 — Boot and update

Open a terminal on the Pi (or SSH into it) and update the package list:

```bash
sudo apt-get update
sudo apt-get upgrade -y
```

### Step 1.2 — Install system dependencies

```bash
sudo apt-get install -y git curl
```

---

## Part 2 — Install rtl_ais

`rtl_ais` drives the SDR dongle and streams decoded AIS NMEA sentences over a
local network socket.

### Step 2.1 — Install from package manager

```bash
sudo apt-get install -y rtl-ais
```

If the package is not found (older Raspberry Pi OS versions), build from source:

```bash
sudo apt-get install -y build-essential cmake libusb-1.0-0-dev
git clone https://github.com/dgiardini/rtl-ais
cd rtl-ais
make
sudo make install
cd ..
```

### Step 2.2 — Verify the install

```bash
rtl_ais --help
```

You should see usage information. If you see `command not found`, the install did not complete — check for errors in the previous step.

### Step 2.3 — Plug in the SDR dongle

Connect the RTL-SDR dongle to a USB port on the Pi, then confirm the Pi can see it:

```bash
rtl_test -t
```

Expected output includes a line like:
```
Found 1 device(s):
  0:  Realtek, RTL2838UHIDIR, SN: ...
```

If you see `No supported devices found`, try a different USB port or check that the dongle is not already in use by another process.

---

## Part 3 — Install uv (Python package manager)

ShipsAhoy uses `uv` to manage its Python environment.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

After installation, reload your shell so the `uv` command is available:

```bash
source ~/.bashrc
```

Verify:

```bash
uv --version
```

---

## Part 4 — Clone the Repository

```bash
git clone https://github.com/conradstorz/ShipsAhoy.git
cd ShipsAhoy
```

---

## Part 5 — Install Python Dependencies

```bash
uv sync
```

This creates a virtual environment and installs all required packages. It only needs to run once (or again after pulling updates).

---

## Part 6 — Test the Installation

Run the test suite to confirm everything is working:

```bash
uv run pytest tests/ -v
```

All tests should pass. If any fail, check that `uv sync` completed without errors.

---

## Part 7 — Run the Services

Each service runs as a separate process. For initial testing, open four terminal
windows (or use `tmux`) and run one service per window.

### Terminal 1 — SDR receiver

```bash
rtl_ais -n -T -p 0 -d 0 2>/dev/null
```

Leave this running. It streams AIS data to TCP port 10110 on localhost.

| Flag | Meaning |
|------|---------|
| `-n` | Do not auto-correct frequency |
| `-T` | Output over TCP (default port 10110) |
| `-p 0` | PPM frequency correction — tune this if reception is poor |
| `-d 0` | Use the first SDR device |

### Terminal 2 — AIS ingest service

```bash
cd ~/ShipsAhoy
uv run python -m services.ais_service
```

This reads from `rtl_ais` and writes ship positions and events to `ships.db`.

Options:

| Flag | Default | Description |
|------|---------|-------------|
| `--host HOST` | `localhost` | Hostname of the `rtl_ais` stream |
| `--port PORT` | `10110` | TCP port of the `rtl_ais` stream |
| `--udp` | off | Use UDP instead of TCP |
| `--db PATH` | `ships.db` | Path to the SQLite database |
| `--verbose` | off | Enable debug logging |

### Terminal 3 — Enrichment service

```bash
cd ~/ShipsAhoy
uv run python -m services.enrichment_service
```

This scrapes ship metadata (name, flag, IMO, photo) from public maritime registries
and stores results in the database. It runs continuously in the background.

Options:

| Flag | Default | Description |
|------|---------|-------------|
| `--db PATH` | `ships.db` | Path to the SQLite database |
| `--photos-dir DIR` | `static/photos` | Directory to save downloaded photos |
| `--verbose` | off | Enable debug logging |

### Terminal 4 — Web UI

```bash
cd ~/ShipsAhoy
uv run python -m services.web_service
```

Open a browser and go to `http://<pi-ip-address>:5000` to view the web interface.

To find your Pi's IP address:

```bash
hostname -I
```

Options:

| Flag | Default | Description |
|------|---------|-------------|
| `--db PATH` | `ships.db` | Path to the SQLite database |
| `--port PORT` | `5000` | HTTP port for the web UI |
| `--verbose` | off | Enable debug logging |

### Terminal 5 (optional) — LED matrix ticker

If you have an ESP32 with LED matrix connected via USB serial:

```bash
cd ~/ShipsAhoy
uv run python -m services.ticker_service --esp32-port /dev/ttyUSB0
```

Replace `/dev/ttyUSB0` with the actual serial device. To find it, run `ls /dev/ttyUSB*` or `ls /dev/ttyACM*` before and after plugging in the ESP32.

Options:

| Flag | Default | Description |
|------|---------|-------------|
| `--db PATH` | `ships.db` | Path to the SQLite database |
| `--esp32-port PORT` | none | Serial device for the ESP32 |
| `--verbose` | off | Enable debug logging |

---

## Part 8 — Run as System Services (Auto-start on Boot)

The `setup.sh` installer automates everything from Parts 1–7. Run it on your Pi after cloning:

```bash
git clone https://github.com/conradstorz/ShipsAhoy.git
cd ShipsAhoy
bash setup.sh
```

The installer logs everything to `setup/install.log`. If it stops, fix the issue it reports and re-run `bash setup.sh` — completed phases are skipped automatically.

### What the installer does

| Phase | Script | What it does |
|-------|--------|--------------|
| 01 | `setup/01-preflight.sh` | Verifies OS, user, sudo, git repo |
| 02 | `setup/02-system-deps.sh` | apt update, git, curl, rtl-ais |
| 03 | `setup/03-python.sh` | uv install, uv sync |
| 04 | `setup/04-uart.sh` | dialout group for serial/UART |
| 05 | `setup/05-services.sh` | systemd unit install, enable, start |
| 06 | `setup/06-verify.sh` | health checks, web UI ping |

Each phase can be re-run in isolation for debugging:
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

---

## Part 9 — Updating ShipsAhoy

To pull the latest code and restart:

```bash
cd ~/ShipsAhoy
git pull
uv sync
sudo systemctl restart ships-ahoy-ais ships-ahoy-enrichment ships-ahoy-web
```

---

## Troubleshooting

### `rtl_test` shows "No supported devices found"
- Try a different USB port.
- Run `lsusb` and look for a device with vendor ID `0bda` (Realtek). If it appears, the OS sees the dongle but the driver is missing — run `sudo apt-get install rtl-sdr`.
- If another program is using the dongle, kill it first: `sudo systemctl stop rtl_fm` or similar.

### No ships appearing after several minutes
- Confirm `rtl_ais` is running: `pgrep -a rtl_ais`
- Check that the AIS service is connected: `sudo journalctl -u ships-ahoy-ais -n 50`
- Try moving the antenna outdoors or to a higher location. AIS is line-of-sight; a few metres of height makes a large difference.
- Check your PPM correction. Run `rtl_test -p` for a few minutes to estimate your dongle's PPM offset, then pass it with `-p <value>` to `rtl_ais`.

### Web UI not reachable from another device
- Confirm the service is running: `sudo systemctl status ships-ahoy-web`
- Check the Pi's firewall: `sudo ufw status`. If active, allow port 5000: `sudo ufw allow 5000/tcp`
- Make sure you are using the Pi's IP address, not `localhost`.

### RTL-SDR dongle not detected by rtl_ais

The DVB-T kernel driver (`dvb_usb_rtl28xxu`) may have claimed the device before `rtl_ais` can open it. Blacklist it permanently:

```bash
echo 'blacklist dvb_usb_rtl28xxu' | sudo tee /etc/modprobe.d/rtl-sdr-blacklist.conf
sudo reboot
```

After rebooting, `rtl_test -t` should show the device.

### ESP32 serial port not found
- Run `ls /dev/ttyUSB* /dev/ttyACM*` before and after plugging in the ESP32 to identify the device.
- If the port exists but access is denied, add your user to the `dialout` group: `sudo usermod -aG dialout pi` then log out and back in.

---

## Appendix: Manual service setup (reference)

The installer in `setup/` handles all of this automatically. The steps below are
provided for reference if you need to customise the service configuration.

### Create service files

Create `/etc/systemd/system/shipsahoy-ais.service`:

```ini
[Unit]
Description=ShipsAhoy AIS ingest service
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/ShipsAhoy
ExecStartPre=/bin/bash -c 'rtl_ais -n -T -p 0 -d 0 2>/dev/null &'
ExecStart=/home/pi/ShipsAhoy/.venv/bin/python -m services.ais_service
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

> **Note:** If you prefer to manage `rtl_ais` as its own unit, remove the
> `ExecStartPre` line and create a separate `rtl-ais.service` with
> `ExecStart=/usr/bin/rtl_ais -n -T -p 0 -d 0` and add `After=rtl-ais.service`.

Create `/etc/systemd/system/shipsahoy-enrichment.service`:

```ini
[Unit]
Description=ShipsAhoy enrichment service
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/ShipsAhoy
ExecStart=/home/pi/ShipsAhoy/.venv/bin/python -m services.enrichment_service
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Create `/etc/systemd/system/shipsahoy-web.service`:

```ini
[Unit]
Description=ShipsAhoy web UI
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/ShipsAhoy
ExecStart=/home/pi/ShipsAhoy/.venv/bin/python -m services.web_service
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Create `/etc/systemd/system/shipsahoy-ticker.service` (only if using ESP32):

```ini
[Unit]
Description=ShipsAhoy LED matrix ticker
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/ShipsAhoy
ExecStart=/home/pi/ShipsAhoy/.venv/bin/python -m services.ticker_service --esp32-port /dev/ttyUSB0
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### Enable and start the services

```bash
sudo systemctl daemon-reload

sudo systemctl enable shipsahoy-ais
sudo systemctl enable shipsahoy-enrichment
sudo systemctl enable shipsahoy-web
# sudo systemctl enable shipsahoy-ticker  # if using ESP32

sudo systemctl start shipsahoy-ais
sudo systemctl start shipsahoy-enrichment
sudo systemctl start shipsahoy-web
# sudo systemctl start shipsahoy-ticker   # if using ESP32
```

### Check service status

```bash
sudo systemctl status shipsahoy-ais
sudo systemctl status shipsahoy-enrichment
sudo systemctl status shipsahoy-web
```

Each should show `active (running)`. To see logs:

```bash
sudo journalctl -u shipsahoy-ais -f
```
