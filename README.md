# ShipsAhoy

Monitor shipping traffic nearby using their automated radio tagging broadcasts.

ShipsAhoy uses a small computer (such as a Raspberry Pi) paired with an
inexpensive **Software Defined Radio (SDR)** dongle and a marine VHF antenna to
receive **AIS (Automatic Identification System)** broadcasts from ships in your
area.  Every vessel over 300 GT and all passenger ships is required by
international law to transmit AIS data, including identity, position, speed,
heading, and more.  Range depends on the broadcast power of nearby ships and
your antenna height; inland and coastal ships within ~20–40 nautical miles are
typically receivable.

---

## Hardware requirements

| Component | Example / notes |
|-----------|-----------------|
| Computer | Raspberry Pi 4, any Linux/macOS/Windows PC |
| SDR dongle | RTL-SDR v3 (RTL2832U chipset, ~$25 USD) |
| Antenna | Marine VHF whip tuned for 162 MHz (AIS channels 87B / 88B) |

---

## Software dependencies

### System tool — `rtl_ais`

`rtl_ais` drives the SDR hardware and outputs decoded AIS NMEA sentences over
a network socket.  Install it on the same machine as the dongle:

```bash
# Debian / Ubuntu / Raspberry Pi OS
sudo apt-get install rtl-ais

# or build from source
git clone https://github.com/dgiardini/rtl-ais
cd rtl-ais && make && sudo make install
```

### Python packages

```bash
pip install -r requirements.txt
```

---

## Installation

```bash
git clone https://github.com/conradstorz/ShipsAhoy.git
cd ShipsAhoy
pip install -r requirements.txt
```

---

## Usage

### 1. Start the SDR receiver

In one terminal, start `rtl_ais` so that it listens on the default TCP port
(10110):

```bash
rtl_ais -n -T -p 0 -d 0 2>/dev/null
```

Flag reference:

| Flag | Meaning |
|------|---------|
| `-n` | Do not correct frequency automatically |
| `-T` | Output to TCP (default port 10110) |
| `-p 0` | PPM correction (0 = none; tune as needed for your dongle) |
| `-d 0` | Use the first SDR device |

### 2. Start ShipsAhoy

In a second terminal:

```bash
python main.py
```

The display refreshes every 2 seconds and shows all ships heard so far.

### Command-line options

```
usage: ships_ahoy [-h] [--host HOST] [--port PORT] [--udp] [--refresh SECONDS] [--verbose]

options:
  --host HOST        Hostname or IP of the AIS data source (default: localhost)
  --port PORT        Port of the AIS data source (default: 10110)
  --udp              Use UDP instead of TCP to receive AIS data
  --refresh SECONDS  Display refresh interval in seconds (default: 2.0)
  --verbose          Enable verbose/debug logging
```

### Example output

```
=======================================================
  ⚓  ShipsAhoy — AIS Ship Tracker
  2024-07-04 14:32:01   Ships tracked: 3
=======================================================

MMSI : 366053242
  Name    : GOLDEN GATE FERRY
  Position: 37.80212° N  -122.42357° E
  Speed   : 12.4 knots
  Heading : 220°
  Course  : 219.3°
  Status  : Under way (engine)
  Type    : Passenger
  Last seen: 14:32:00

MMSI : 338234567
  Name    : TUG PACIFIC
  Position: 37.79100° N  -122.41000° E
  Speed   : 3.1 knots
  Status  : Engaged in fishing
  Type    : Towing
  Last seen: 14:31:58
```

---

## Project structure

```
ShipsAhoy/
├── main.py                  # CLI entry point
├── requirements.txt         # Python dependencies
├── ships_ahoy/
│   ├── __init__.py
│   ├── ais_receiver.py      # Connects to rtl_ais via TCP/UDP; yields decoded AIS messages
│   ├── ship_tracker.py      # Maintains a live registry of tracked ships
│   └── display.py           # Terminal display / formatting
└── tests/
    ├── test_ais_receiver.py
    ├── test_display.py
    └── test_ship_tracker.py
```

---

## Running tests

```bash
pip install pytest
python -m pytest tests/ -v
```

---

## License

GNU Affero General Public License v3.0 (AGPL-3.0) — see [LICENSE](LICENSE).

