# AIS Monitoring as a Hobby

A practical guide to receiving, decoding, and exploring Automatic Identification System data from ships using a Raspberry Pi and low-cost SDR hardware.

> **Key reference:** Gary C. Kessler's excellent paper [AIS Research Using a Raspberry Pi (2026 Update)](https://www.garykessler.net/library/ais_pi.html) is the primary source for much of the hardware and software guidance in this document. It is updated regularly and recommended reading for anyone going deeper into this hobby. It originally appeared in 2019 and was substantially updated in 2022 and again in April 2026.

---

## What is AIS?

The Automatic Identification System (AIS) is a VHF radio transponder system mandated on commercial vessels over 300 gross tonnes, all passenger vessels regardless of size, and most vessels engaged in international voyages. It broadcasts a vessel's identity (MMSI number and name), position, speed, heading, vessel type, dimensions, destination, and more — typically every few seconds to a few minutes depending on speed.

AIS uses two VHF maritime channels:
- **AIS1:** 161.975 MHz (VHF channel 87B / 2087)
- **AIS2:** 162.025 MHz (VHF channel 88B / 2088)

A satellite-AIS (S-AIS) variant also exists on 156.775 MHz (AIS3) and 156.825 MHz (AIS4), used by LEO satellites to receive transmissions over open ocean where shore stations cannot reach.

The raw messages are NMEA 0183 sentences beginning with `!AIVDM` (incoming from other vessels) or `!AIVDO` (your own outgoing transmissions). A comprehensive reference for decoding the payload is Eric Raymond's [AIVDM/AIVDO protocol decoding](https://gpsd.gitlab.io/gpsd/AIVDM.html) page.

---

## Why is this an interesting hobby?

- **You can see real ships** — cargo vessels, tankers, ferries, fishing boats, tugboats, and recreational vessels — moving in real time on a map, with full identity and voyage data, just by pointing an antenna at the sky.
- **Low entry cost** — a working receive station can be built for under $100 using hardware you likely already have (Raspberry Pi) plus a cheap SDR dongle and a basic antenna.
- **No licence required** — you are only receiving, not transmitting. AIS data is broadcast openly and unencrypted.
- **Educational value** — AIS decoding touches RF engineering, digital signal processing, NMEA protocol parsing, database design, and web development. ShipsAhoy itself is an example of all of these in a single Python project.
- **Research value** — AIS data is used by maritime security researchers, port authorities, environmental agencies, and journalists. Collected datasets can reveal patterns in maritime traffic, suspicious behavior (e.g. transponder spoofing), or ecological impacts on shipping lanes.

---

## Recommended Hardware

### The Receiver

You have two main options:

#### Option A — dAISy HAT (Recommended for Raspberry Pi)

The **dAISy HAT** (Hardware Attached on Top), designed by Wegmatt, is a 2-channel AIS receiver in daughterboard form that plugs directly into the Raspberry Pi's 40-pin GPIO header. It is the primary hardware recommended by Gary Kessler's guide and widely regarded as the most reliable and convenient option for a Pi-based station.

- Purpose-built for AIS — no SDR software required
- Dual-channel: receives both AIS1 and AIS2 simultaneously
- Presents as a serial port (`/dev/ttyS0` or `/dev/serial0`) at 38400 baud
- Available from [Tindie](https://www.tindie.com/products/astuder/daisy-hat-ais-receiver-for-raspberry-pi/)
- A protective case is available and recommended

A USB version (**dAISy 2+**) is also available for setups where the HAT form factor is not convenient. It appears as `/dev/ttyACM0` on Linux.

> **Antenna connector note:** Check the terminating connector before buying an antenna for the dAISy HAT. The HAT uses a female BNC jack. Marine VHF antennas typically terminate with a male PL-259 (UHF Male) — you will need a PL-259 to BNC adapter. The SO-239 pigtail or BNC-to-SO-239 adapter is the right thing to buy alongside the HAT.

#### Option B — RTL-SDR Dongle + rtl_ais Software

A general-purpose RTL-SDR dongle running the `rtl_ais` software is a lower-cost alternative that works well with a good dongle and proper antenna. This is the approach used by ShipsAhoy.

**Important:** Not all RTL-SDR dongles are equal. Avoid cheap generic DVB-T sticks with the **Fitipower FC0013** tuner — maximum gain is only ~19.70 dB, which severely limits sensitivity. Use:

| Dongle | Tuner | Max Gain | TCXO | ~Price |
|---|---|---|---|---|
| RTL-SDR Blog V3 | R860 (R820T2) | ~49 dB | 1 PPM | $35–50 |
| RTL-SDR Blog V4 | R828D | ~49 dB | 1 PPM | $40–50 |
| Nooelec NESDR Smart v5 | R820T2 | ~49 dB | ~0.5 PPM | $30–40 |

The built-in 1 PPM TCXO (Temperature Compensated Crystal Oscillator) on these units eliminates the frequency-offset problem that plagues cheap dongles, where a 30+ PPM error on 162 MHz can shift the received frequency by 5 kHz or more — causing the decoder to miss AIS messages entirely.

To start `rtl_ais`:
```bash
# TCP output on port 10110, log sentences to console, PPM auto-correct
rtl_ais -n -T -p 0 -d 0
```

If you have a generic dongle and need to find the PPM offset:
```bash
# Run for at least 5 minutes
rtl_test -p
```
Note the "cumulative PPM" value and pass it as `-p VALUE` to `rtl_ais`.

### The Raspberry Pi

Any current Raspberry Pi works. The guide was written and tested on a **Raspberry Pi 3 Model B+** and is confirmed to work on the **Raspberry Pi 5**. The Pi 3 B+ is sufficient for a dedicated AIS receive station; the Pi 4 or Pi 5 are better if you also intend to run a charting application like OpenCPN.

Required accessories:
- 32 GB or 64 GB microSD card (Class 10 / A1 rated)
- 5V power supply rated for your Pi model (the Pi 4/5 requires USB-C; the Pi 3 requires Micro-USB)
- Optional: case that accommodates the dAISy HAT (Wegmatt sells one)

### The Antenna

This is the most commonly overlooked part of an AIS receive station and the most common reason for receiving no ships.

- AIS operates at ~162 MHz. A standard DVB-T TV antenna (tuned for 470–862 MHz) will perform very poorly.
- You need a **VHF antenna** tuned for the marine band. Any antenna labelled "VHF marine antenna" is appropriate.
- A simple quarter-wave monopole cut for 162 MHz has an ideal length of **46 cm (18 inches)**.
- Reception range is directly proportional to antenna height. Even 5–10 metres of elevation above surrounding terrain makes an enormous difference.
- Use low-loss coax (RG-8, LMR-400, or RG-6) and keep runs as short as practical. RG-58 and the thin RG-174 included with most antenna kits have significant loss at VHF.
- If your coax run is long (>5 m), a **low-noise amplifier (LNA)** near the antenna can compensate for cable loss.

---

## Operating System Setup

Gary Kessler's guide covers this in detail for the standard Raspberry Pi OS path. Two shortcuts worth knowing:

### Pre-built images with everything included

- **[OpenPlotter](https://openmarine.net/openplotter)** — Raspberry Pi OS image with SignalK Server and OpenCPN pre-installed. The fastest path to a working AIS chartplotter station.
- **[BBN Marine OS](https://bareboat-necessities.wixsite.com/my-bareboat)** — Raspberry Pi OS image with OpenCPN and many marine utilities pre-installed.

### Standard Raspberry Pi OS path

1. Download and install the **[Raspberry Pi Imager v2.0+](https://www.raspberrypi.com/software/)**
2. Flash Raspberry Pi OS (64-bit for Pi 4/5; 32-bit works fine for Pi 3)
3. Use the Imager's **customization step** to pre-set hostname, SSH, Wi-Fi credentials, username, and locale — this enables headless (no-keyboard) first boot
4. After boot, SSH in and run `sudo raspi-config`:
   - Enable the **Serial Port** (required for dAISy HAT)
   - Enable **VNC** if you want a remote desktop
5. Reboot

```bash
sudo raspi-config
# → Interface Options → Serial Port → Enable
# → Interface Options → VNC → Enable
```

---

## Software Stack

### For dAISy HAT users

The dAISy HAT needs no additional drivers. After enabling the serial port in `raspi-config`, data flows immediately to `/dev/ttyS0` (or `/dev/serial0`) at 38400 baud.

Verify you're receiving data:
```bash
cat /dev/serial0
# You should see lines like:
# !AIVDM,1,1,,A,15NaEn0P00G?Uo`H@H8rM2CP0<0f,0*21
```

### For RTL-SDR / rtl_ais users

```bash
# Install rtl-sdr tools
sudo apt-get install rtl-sdr

# Install rtl_ais
sudo apt-get install rtl-ais
# or build from source: https://github.com/dgiardini/rtl-ais

# Run (produces TCP stream on port 10110)
rtl_ais -n -T -p 0 -d 0
```

### OpenCPN — Chartplotter

[OpenCPN](https://opencpn.org/) is free, open-source chartplotter software that runs on Linux, macOS, Windows, Android, and Raspberry Pi. It displays AIS targets on navigational charts in real time.

```bash
sudo apt-get update
sudo apt-get install opencpn
```

**Configure a data connection in OpenCPN:**

*For dAISy HAT (serial):*
- Options → Connections → Add Connection
- Type: Serial
- DataPort: `/dev/ttyS0` or `/dev/serial0`
- Baudrate: 38400

*For rtl_ais or other TCP source:*
- Options → Connections → Add Connection
- Type: Network → TCP
- IP: `localhost` (or remote IP)
- Port: `10110`

**Download NOAA ENC charts:**
- Options → Charts → Chart Downloader → Add Catalog → USA - NOAA & Inland charts
- Select by state, download the relevant charts

OpenCPN can also act as a data **server**: configure an output connection (Network → TCP → address `0.0.0.0`) and any application can connect to it with `nc` or `telnet` to read the raw NMEA stream.

### AIS Dispatcher (AISHub)

[AIS Dispatcher](https://www.aishub.net/ais-dispatcher) from AISHub is an alternative pipeline for the Raspberry Pi that feeds data to the AISHub aggregation network — giving you access to global AIS data in return for sharing your local feed.

### ShipsAhoy

The project in this repository is a Python-based AIS monitoring stack specifically designed for Raspberry Pi. It:
- Receives NMEA sentences via TCP (from `rtl_ais` or any compatible source)
- Decodes and stores ship data in a SQLite database
- Enriches ship records with photos and vessel metadata
- Drives an ESP32-based LED matrix ticker display
- Exposes a web UI for browsing nearby ships

See the main [README.md](../README.md) and [QUICKSTART.md](QUICKSTART.md) for setup instructions.

---

## Working With Raw AIS Data

### Capturing data

Use `netcat` or `telnet` to capture raw NMEA sentences from any TCP source:
```bash
nc localhost 10110
# or
telnet localhost 10110
```

To save to a file with timestamps (Gary Kessler's `timestamp_data` Perl tool):
```bash
# Download from https://www.garykessler.net/software/index.html#timestamp
perl timestamp_data.pl -h localhost -p 10110 -t 3600 -o capture.txt
```
Output format: `UNIX_EPOCH|HUMAN_TIMESTAMP|NMEA_SENTENCE`

### Replaying captured data

Feed a previously captured file back into OpenCPN in relative real-time using Gary Kessler's `play_ais` tool:
```bash
cat FILENAME | { while read line; do sleep 1; echo "$line" > /dev/tcp/localhost/PORT; done; }
```
Or use `play_ais` which respects the timestamps written by `timestamp_data`.

### Parsing NMEA sentences

Online parsers for decoding raw `!AIVDM` sentences:
- [AIS VDM/VDO Decoder — Maritec Solutions](https://www.maritec.co.za/tools/aisvdmvdodecoding/)
- [AIVDM & AIVDO decoder — RL.SE](https://rl.se/aivdm)
- [AIS online decoder — AGG Software](https://www.aggsoft.com/ais-decoder.htm)
- [AisDecoder — Neal Arundale](https://arundaleais.github.io/docs/ais/ais_decoder.html)

The canonical reference for the message format is Eric Raymond's [AIVDM/AIVDO protocol decoding](https://gpsd.gitlab.io/gpsd/AIVDM.html).

Gary Kessler also provides a set of **Perl-based AIS tools** (parser, capture, replay, message creator) at his [software page](https://www.garykessler.net/software/index.html#ais).

### Sources of real AIS data (without hardware)

If you want to explore AIS data before your hardware arrives, or test software against known-good feeds:

| Source | Access |
|---|---|
| [AISHub](https://www.aishub.net/) | Free data sharing network; share your feed, get global data |
| [aisstream.io](https://aisstream.io/) | WebSocket API for real-time global AIS data |
| Embry-Riddle AIS feed (Daytona Beach area) | `telnet ssia-ais.erau.edu 4000` |
| Norwegian Coastal Administration | `nc 153.44.253.27 5631` or via [kart.kystverket.no](https://kart.kystverket.no/share/9220e0e277e4) |
| [Spire Global](https://spire.com/maritime/) | Historical data available on request |
| [MarineTraffic](https://www.marinetraffic.com/) | Web-based viewer; useful for confirming ships are in your area |

---

## Troubleshooting: No Ships Received

See [troubleshooting-no-ships.md](troubleshooting-no-ships.md) for a detailed diagnosis guide based on a real ShipsAhoy session. The short checklist:

1. **Confirm ships exist in your area** — check MarineTraffic before blaming hardware
2. **Check your dongle** — FC0013-based sticks are limited to ~19.70 dB gain; upgrade to an R820T2/R828D dongle
3. **Correct PPM offset** — run `rtl_test -p` for 5 minutes and apply the cumulative PPM value with `-p VALUE`
4. **Fix your antenna** — a DVB-T TV antenna will not work well at 162 MHz; use a proper VHF whip
5. **Raise the antenna** — even a few metres of height dramatically increases range
6. **Consider the dAISy HAT** — eliminates all SDR/PPM issues entirely; factory-tuned for AIS

---

## Going Further

### NMEA 2000

For deeper integration with marine electronics, [CANboat](https://github.com/canboat/canboat/wiki) is the project to know — it handles NMEA 2000 binary (CAN bus) data, which is the modern backbone network on larger vessels.

### AIS Security Research

AIS is an unauthenticated, unencrypted system. Messages can be spoofed. Gary Kessler's work includes research on AIS spoofing and anomaly detection. The DEF CON 32 ICS Village talk ["Don't Ship Your Bridges!"](https://github.com/liberasinc/dc32-ics-ais/blob/main/DC32_AIS_Talk_V3.pdf) (Kessler, Haltmeyer, Woodbury) covers SDR transmission of spoofed AIS using HackRF and is essential reading for understanding the security implications.

The [MAIANA™ Open Source AIS Transponder](https://github.com/peterantypas/maiana) project provides an open-hardware Class B AIS transponder if you need to both receive and transmit.

### OpenPlotter / MacArthur HAT

[OpenPlotter](https://openmarine.net/openplotter) is a full navigational toolkit for Raspberry Pi, and the [MacArthur HAT](https://github.com/OpenMarine/MacArthur-HAT) is an add-on board for running OpenPlotter on small and medium boats.

### NMEASimulator

[panaaj's NMEASimulator](https://github.com/panaaj/nmeasimulator) is a graphical NMEA sentence generator (position, speed, heading, AIS) that runs on Linux, macOS, Raspberry Pi, and Windows. Useful for testing OpenCPN or ShipsAhoy without live traffic.

---

## Further Reading

- **Gary C. Kessler — [AIS Research Using a Raspberry Pi (2026 Update)](https://www.garykessler.net/library/ais_pi.html)** — The definitive hobbyist guide; covers hardware, OS setup, dAISy HAT, OpenCPN, and data analysis in detail. Updated April 2026.
- **Rae Baker — [Creating an AIS Pi for Maritime Research](https://wondersmithrae.medium.com/creating-an-ais-pi-for-maritime-research-5e6f754e541c)** — Companion blog post with a practical walkthrough.
- **Rae Baker — [How to Install OpenCPN on Your AIS Raspberry Pi](https://wondersmithrae.medium.com/how-to-install-opencpn-on-your-ais-raspberry-pi-for-maritime-research-c6d3da5eb5a6)** — OpenCPN installation guide for Raspberry Pi.
- **USCG Navigation Center — [AIS Overview](https://www.navcen.uscg.gov/automatic-identification-system-overview)** — Official US government reference.
- **IALA — [An Overview of AIS (Edition 2)](https://www.navcen.uscg.gov/sites/default/files/pdf/IALA_Guideline_1082_An_Overview_of_AIS.pdf)** — International standard body's guide to the AIS system.
- **Eric Raymond — [AIVDM/AIVDO Protocol Decoding](https://gpsd.gitlab.io/gpsd/AIVDM.html)** — The technical reference for the message format.
- **Gary C. Kessler — [Build A Raspberry AIS](https://www.youtube.com/watch?v=6el_W4rQHDQ)** — DEF CON 28 Hack The Sea 2.0 talk (2020), available on YouTube.
