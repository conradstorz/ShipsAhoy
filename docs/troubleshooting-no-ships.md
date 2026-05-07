# Troubleshooting: No Ships Detected

**Date:** 2026-05-07  
**System:** Raspberry Pi running ShipsAhoy with RTL-SDR dongle (Fitipower FC0013 tuner)

---

## Observed Symptoms

- All five ShipsAhoy services started and are running
- `ships.db` contains **0 ship records** after 9+ minutes of operation
- No NMEA sentences logged by `rtl_ais` despite the `-n` (log-to-console) flag being set
- Ticker service logging `[Errno 2] No such file or directory: '/dev/ttyUSB0'` every 4 seconds

---

## Service Health Summary

| Service | Status | Notes |
|---|---|---|
| `ships-ahoy-rtl-ais` | Running | Dongle found, tuned to 162 MHz, TCP on port 10110 |
| `ships-ahoy-ais` | Running | Connected to TCP localhost:10110, waiting for data |
| `ships-ahoy-enrichment` | Running | Normal |
| `ships-ahoy-web` | Running | Normal |
| `ships-ahoy-ticker` | Running (errors) | `/dev/ttyUSB0` not found — ESP32 not connected |

The pipeline from SDR → TCP → AIS ingest → database is correctly wired. The failure is entirely upstream: **`rtl_ais` is not decoding any AIS messages**.

---

## Root Cause Analysis

### 1. Fitipower FC0013 Tuner (Low Sensitivity)

The dongle contains a **Fitipower FC0013** tuner. This is a lower-quality chip compared to the common R820T2 found in most purpose-built SDR receivers.

The installed service was launched with `-g 50` (requesting 50 dB gain), but the FC0013 **hardware maximum is approximately 19.70 dB**. `rtl_ais` silently clamps the gain:

```
Tuner gain set to 19.70 dB.
```

This significantly reduces receive sensitivity compared to an R820T2-based dongle which supports up to ~49 dB.

**Recommendation:** Upgrade to an R820T2-based RTL-SDR dongle (e.g. RTL-SDR Blog v3/v4) for substantially better sensitivity on the 162 MHz marine band.

---

### 2. PPM Crystal Frequency Offset

The service runs with `-p 0` (zero PPM correction). Cheap RTL-SDR dongles almost universally have a crystal oscillator with meaningful frequency error — commonly anywhere from 10 to 100+ PPM. On 162 MHz, even 30 PPM of drift is ~4.9 kHz off-frequency, which can cause the decoder to miss both AIS channels entirely (161.975 MHz and 162.025 MHz).

**How to measure your dongle's PPM offset:**

```bash
# Run for at least 5 minutes with a known-good signal source (e.g. FM broadcast)
rtl_test -p
```

Look for the line:
```
real sample rate: 2048000 current PPM: 42 cumulative PPM: 41
```

Then update the service's `ExecStart` line:

```
/usr/bin/rtl_ais -n -T -p 42 -d 0 -g 50
```

Replace `42` with whatever cumulative PPM `rtl_test` reports.

**To apply the change:**

```bash
sudo nano /etc/systemd/system/ships-ahoy-rtl-ais.service
sudo systemctl daemon-reload
sudo systemctl restart ships-ahoy-rtl-ais.service
```

---

### 3. Antenna

AIS signals are in the marine VHF band (161–163 MHz). A standard DVB-T TV antenna (typically tuned for 470–860 MHz) will receive very poorly at 162 MHz. Required:

- A **VHF whip antenna** cut for ~162 MHz (ideal quarter-wave length ≈ 46 cm / 18 inches)
- Or a **dedicated marine VHF antenna** (e.g. Shakespeare, Glomex) mounted with a clear view toward the water
- Keep coax run as short as practical — loss at VHF is significant over long runs of cheap coax

---

### 4. No Ships in Range

AIS Class A transceivers (cargo ships, tankers) typically have a reception range of 20–50 nautical miles line-of-sight from a shore receiver. Reception is highly sensitive to:

- Elevation of the antenna (higher = more range)
- Obstructions (buildings, hills) between the antenna and the water
- Distance from active maritime traffic lanes

If the system is inland or not near a navigable waterway, there may genuinely be no AIS traffic to receive. Cross-check against a reference like [MarineTraffic](https://www.marinetraffic.com) or [AISHub](https://www.aishub.net) to confirm whether vessels are present in your area before further hardware debugging.

---

## Separate Issue: ESP32 Ticker (`/dev/ttyUSB0` Not Found)

The ticker service expects the ESP32 LED matrix display to be connected on `/dev/ttyUSB0`. It is currently absent and logging an error every 4 seconds. This does **not** affect AIS reception or ship tracking.

**To silence the errors** until the ESP32 is connected, stop the service:

```bash
sudo systemctl stop ships-ahoy-ticker.service
sudo systemctl disable ships-ahoy-ticker.service
```

Re-enable it once the ESP32 is plugged in:

```bash
sudo systemctl enable --now ships-ahoy-ticker.service
```

---

## Commercial AIS Receiver Options (as of May 2026)

The current setup uses a generic DVB-T dongle repurposed as an SDR. Below is an overview of the commercially available alternatives, from budget DIY to purpose-built professional receivers.

---

### Tier 1 — Improved RTL-SDR Dongles (DIY SDR, drop-in replacement)

These are direct drop-in replacements for the current FC0013-based dongle. They work with `rtl_ais` exactly as-is and represent the lowest-cost upgrade path.

| Product | Tuner | TCXO | Approx. Price | Notes |
|---|---|---|---|---|
| **RTL-SDR Blog V3** (with dipole kit) | R860 (R820T2) | 1 PPM | ~$45–50 | Best overall value; SMA connector, bias tee, aluminum case |
| **RTL-SDR Blog V3** (dongle only) | R860 (R820T2) | 1 PPM | ~$35–40 | Same hardware, no antenna included |
| **RTL-SDR Blog V4** (with dipole kit) | R828D | 1 PPM | ~$50 | Newer design; adds triplexed input filter, HF upconverter, improved front-end |
| **RTL-SDR Blog V4** (dongle only) | R828D | 1 PPM | ~$40 | USB-C variant also available at same price |
| **Nooelec NESDR Smart v5** | R820T2 | ~0.5 PPM TCXO | ~$30–40 | Similar to V3; widely available on Amazon |

**Key improvements over the current FC0013 dongle:**
- R820T2/R828D tuner: up to ~49 dB gain (vs 19.70 dB max on FC0013)
- 1 PPM TCXO: essentially eliminates frequency offset errors without needing `-p` correction
- SMA port: lower loss than MCX/PAL adapters; broader antenna compatibility
- Better EMI shielding and lower internal noise floor

Available from: [rtl-sdr.com](https://www.rtl-sdr.com/buy-rtl-sdr-dvb-t-dongles/), Amazon, AliExpress, eBay.

> **Note:** The V4 requires updated `librtlsdr` drivers. Confirm `rtl_ais` compatibility before purchasing if you are running an older OS image.

---

### Tier 2 — Dedicated Single-Purpose USB AIS Receivers

These devices contain hardware tuned and filtered specifically for the 161–163 MHz AIS band. They do **not** use `rtl_ais` — they present as a serial (COM) port and output NMEA 0183 sentences directly. ShipsAhoy would need to be pointed at the serial port rather than a TCP socket, or a serial-to-TCP bridge (e.g. `socat`) used.

| Product | Channels | Interface | Approx. Price | Notes |
|---|---|---|---|---|
| **Digital Yacht AIS100** | Single | USB → serial (NMEA 0183) | ~$130–160 | Established product; wide software support |
| **Digital Yacht AIS100PRO** | Dual | USB → serial (NMEA 0183) | ~$160–200 | Dual-channel improves message capture rate significantly |
| **ShipXplorer AIS Dongle** | Dual | USB → serial | ~$50–80 | Lower cost; popular with AIS aggregation networks (AISHub, MarineTraffic) |
| **Generic Dual-Channel USB AIS** (various) | Dual | USB → serial | ~$30–60 | No-name Chinese units on Amazon; quality varies; include a folding stainless whip antenna |

**Advantages over SDR approach:**
- No PPM calibration needed — hardware is factory-tuned to AIS frequencies
- No `rtl_ais` software layer — simpler, more reliable pipeline
- Dual-channel models receive both AIS channels (161.975 + 162.025 MHz) simultaneously, doubling message capture rate
- Much less sensitive to nearby RF interference

**Disadvantage:** Single-purpose only — cannot be reused for other SDR applications.

---

### Tier 3 — Standalone Networked AIS Receivers

These are self-contained units that connect to your LAN and expose AIS data over TCP/UDP — the same way `rtl_ais` does, and compatible with ShipsAhoy out of the box.

| Product | Channels | Interface | Approx. Price | Notes |
|---|---|---|---|---|
| **Vesper Marine XB-8000** | Dual | Ethernet / Wi-Fi / NMEA 2000 | ~$350–450 | High-end; Class B transponder + receiver; also transmits your vessel's position |
| **Comar SLR350Ni** | Dual | Ethernet (TCP/IP NMEA) | ~$250–350 | Dedicated receive-only; outputs NMEA 0183 over TCP — direct ShipsAhoy compatible |
| **Garmin AIS 800** | Dual | NMEA 2000 / serial | ~$400–500 | Marine-grade; primarily targets onboard chartplotter integration |
| **dAISy 2+** (by Wegmatt) | Dual | USB → serial | ~$65–80 | Compact, low-power; highly regarded in DIY AIS communities; HAT form factor also available for Raspberry Pi |

The **dAISy 2+** is particularly relevant for a Raspberry Pi-based setup: it consumes very little power, is plug-and-play on Linux (appears as `/dev/ttyACM0`), and has a Raspberry Pi HAT variant that mounts directly on GPIO headers.

---

### Summary Recommendation for ShipsAhoy

| Goal | Recommended Product | Est. Cost |
|---|---|---|
| Minimal cost fix, keep SDR flexibility | RTL-SDR Blog V3 or V4 (dongle only) | ~$35–40 |
| Most reliable AIS reception, simplest setup | dAISy 2+ USB receiver | ~$65–80 |
| Production/permanent installation | Comar SLR350Ni or Vesper XB-8000 | ~$250–450 |

For a shore-based monitoring station like ShipsAhoy, the **dAISy 2+** or an **RTL-SDR Blog V4 + proper VHF antenna** offers the best balance of cost, reliability, and compatibility with the existing software stack.

---

## Recommended Diagnostic Sequence

1. **Confirm maritime traffic exists nearby** — check MarineTraffic for your area
2. **Measure PPM offset** with `rtl_test -p` and update the service
3. **Verify antenna** — substitute a proper VHF whip if using a DVB-T antenna
4. **Upgrade dongle** — replace FC0013-based stick with an R820T2 (RTL-SDR Blog v3/v4) if steps 1–3 don't resolve the issue
5. **Validate the pipeline** — once `rtl_ais` starts logging NMEA sentences to `journalctl`, verify they flow into the database:

```bash
# Watch for NMEA messages in real time
sudo journalctl -u ships-ahoy-rtl-ais.service -f

# Check ship count in the database
python3 -c "
import sqlite3
conn = sqlite3.connect('/home/conrad/ShipsAhoy/ships.db')
cur = conn.cursor()
cur.execute('SELECT COUNT(*) FROM ships')
print('Total ships:', cur.fetchone()[0])
conn.close()
"
```
