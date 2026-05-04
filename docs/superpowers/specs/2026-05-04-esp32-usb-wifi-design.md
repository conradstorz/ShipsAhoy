---
date: 2026-05-04
topic: ESP32 USB-C input + WiFi debug/OTA
status: approved
---

# ESP32 USB-C Input and WiFi Debug/OTA — Design Spec

## Context

Replaces the three-wire GPIO UART connection between the Raspberry Pi and the
ESP32 ticker with a single USB-C cable. Simultaneously replaces the USB serial
debug monitor with a password-protected WiFi soft-AP that serves a live
three-column debug web page and accepts OTA firmware uploads.

The packet protocol (framing, CRC8, commands) is **unchanged**. Only the
transport layer and debug channel change.

---

## Architecture

### Before

```
Pi GPIO TX/RX ──(jumper wires)──▶ ESP32 Serial2 (GPIO 17/18, 921600 baud)
ESP32 USB port ──────────────────▶ PC Serial monitor (debug, 115200)
arduino-cli ─────────────────────▶ ESP32 USB port (flash)
```

### After

```
Pi USB-C ────────────────────────▶ ESP32 USB-UART chip / Serial (921600)
Laptop/phone WiFi ───────────────▶ ESP32 soft-AP "ShipsAhoy-Debug" (debug web page)
arduino-cli (first flash) ───────▶ ESP32 USB port (unchanged)
arduino-cli (updates) ───────────▶ ESP32 soft-AP over WiFi OTA
```

---

## Firmware — New Files

### `esp32_ticker/debug_log.h` / `debug_log.cpp`

Three public functions used throughout the firmware in place of `Serial.printf`:

```cpp
void dbg_info (const char* fmt, ...);
void dbg_warn (const char* fmt, ...);
void dbg_error(const char* fmt, ...);
```

**Behaviour per call:**
1. Format the message (vsnprintf into a stack buffer).
2. Timestamp it with `millis()` (ms since boot).
3. Append to the fixed-size ring buffer for that level (sizes from `config.h`).
4. If any SSE client is connected, push a JSON event immediately:
   `data: {"l":"info","t":12450,"m":"[uart] started"}\n\n`
5. Return immediately — never blocks.

**Ring buffers** — one per level, sizes set in `config.h`:
- `DBG_BUF_INFO` messages for info (default 80)
- `DBG_BUF_WARN` messages for warnings (default 40)
- `DBG_BUF_ERROR` messages for errors (default 20)

**Ring buffer replay** — when a browser first connects to `/events`, the server
replays all retained messages from all three buffers in timestamp order before
switching to live events. Latecomers see recent history.

**Thread safety** — ring buffers protected by a FreeRTOS mutex. `dbg_*` may be
called from any task.

---

### `esp32_ticker/wifi_manager.h` / `wifi_manager.cpp`

Called once from `setup()` via `wifi_manager_init()`.

**Startup sequence:**
1. `WiFi.softAP(WIFI_AP_SSID, WIFI_AP_PASSWORD, WIFI_AP_CHANNEL, 0, WIFI_AP_MAX_CONN)`
2. ArduinoOTA: set hostname (`OTA_HOSTNAME`), password (`OTA_PASSWORD`), port
   (`OTA_PORT`); register `onStart`/`onError` callbacks → `dbg_info`/`dbg_error`;
   call `ArduinoOTA.begin()`.
3. AsyncWebServer: register routes, call `server.begin()`.
4. Start `wifi_task` FreeRTOS task on Core 0.

**Web server routes:**

| Route | Response |
|-------|----------|
| `GET /` | Embedded HTML debug page |
| `GET /events` | SSE stream (replayed history + live events) |
| `GET /status` | JSON: uptime_ms, free_heap, display_mode, wifi_clients |

**`wifi_task` (Core 0, alongside `uart_task`):**
```
loop:
    ArduinoOTA.handle()
    vTaskDelay(10ms)
```
AsyncWebServer is event-driven; no explicit polling needed for HTTP/SSE.

**Debug web page** (embedded HTML string in firmware, no filesystem):
- Three columns: **Info** | **Warnings** | **Errors**
- Connects to `/events` via `EventSource`
- Each event parsed by level (`l` field), timestamped row appended to matching column
- Each column scrolls independently; newest entries at the bottom
- Header bar shows connection status: `● Connected` / `○ Reconnecting…`
- Auto-reconnects if SSE stream drops
- No external dependencies — all CSS and JS inline

---

## Firmware — Modified Files

### `config.h`

Remove the `UART` section entirely. Add:

```c
// ── Input (USB-C to Pi) ───────────────────────────────────────────────────────
#define PI_BAUD          921600

// ── WiFi debug AP ─────────────────────────────────────────────────────────────
#define WIFI_AP_SSID     "ShipsAhoy-Debug"
#define WIFI_AP_PASSWORD "ticker1234"      // change before deployment
#define WIFI_AP_CHANNEL  6
#define WIFI_AP_MAX_CONN 2

// ── OTA ───────────────────────────────────────────────────────────────────────
#define OTA_HOSTNAME     "shipsahoy-ticker"
#define OTA_PASSWORD     "ota-ticker1234"  // change before deployment
#define OTA_PORT         3232

// ── Debug log ring buffers ────────────────────────────────────────────────────
#define DBG_BUF_INFO     80
#define DBG_BUF_WARN     40
#define DBG_BUF_ERROR    20
```

All other sections (Display, Protocol constants, Text rendering, FreeRTOS)
remain unchanged.

---

### `protocol.cpp` / `protocol.h`

Six mechanical substitutions:

| Old | New |
|-----|-----|
| `Serial2.begin(UART_BAUD, SERIAL_8N1, UART_RX_PIN, UART_TX_PIN)` | `Serial.begin(PI_BAUD)` |
| `Serial2.available()` | `Serial.available()` |
| `Serial2.read()` | `Serial.read()` |
| `Serial2.write(ACK_BYTE)` | `Serial.write(ACK_BYTE)` |
| `Serial2.write(NACK_BYTE)` | `Serial.write(NACK_BYTE)` |
| `Serial.printf("[uart] ...")` | `dbg_info/warn/error("[uart] ...")` |

The last substitution applies to seven debug prints in `protocol.cpp`:
CRC failure, oversized payload, unknown command, FRAME too-large, CMD_PING
path, and two startup prints in `protocol_init()`.

`protocol.h` — remove `#include`s or references specific to Serial2 if any.

---

### `display.cpp`

Replace all `Serial.printf(...)` debug calls with `dbg_info`/`dbg_warn`/`dbg_error`
equivalents. No logic changes.

---

### `esp32_ticker.ino`

- Remove `Serial.begin(115200)` and the two `Serial.println` / `Serial.printf`
  startup prints.
- Add `#include "wifi_manager.h"` and `#include "debug_log.h"`.
- Add `wifi_manager_init()` call in `setup()` before `display_init()` and
  `protocol_init()`.
- Replace removed startup prints with `dbg_info(...)` calls (these will appear
  in the debug web page once WiFi is up).

---

## Pi-Side Changes

### `systemd/ships-ahoy-ticker.service`

```ini
# Before:
ExecStart=... --esp32-port /dev/ttyAMA0

# After:
ExecStart=... --esp32-port /dev/ttyUSB0
```

### `setup/04-uart.sh`

No change. The `dialout` group covers `/dev/ttyUSB0` on Raspberry Pi OS.

### Python (`ships_ahoy/matrix_driver.py`)

No change. `ESP32Driver` opens whatever port `--esp32-port` names.

---

## Documentation Changes

### `docs/raspberry-pi-setup.md`

Replace the wiring paragraph (three jumper wires between GPIO pins) with:
"Connect a USB-C cable from any USB port on the Pi to the ESP32."

### `docs/flashing-esp32.md`

- Add a note near the top: "The first flash requires a USB cable. Subsequent
  firmware updates use WiFi OTA — see Part 5."
- Add **Part 5 — OTA updates**:
  1. Connect laptop to `ShipsAhoy-Debug` WiFi (password in `config.h`)
  2. Run:
     ```bash
     arduino-cli upload \
       --fqbn esp32:esp32:esp32s3 \
       --port shipsahoy-ticker \
       --protocol network \
       esp32_ticker/
     ```
  3. The ESP32 reboots; WiFi AP returns within a few seconds.

---

## OTA Workflow

The initial flash always uses USB (arduino-cli over the UART chip port,
unchanged from the current flashing guide). After that:

```
Developer machine connects to "ShipsAhoy-Debug" WiFi
  → arduino-cli discovers device as "shipsahoy-ticker" via mDNS
  → upload sent over WiFi, OTA password checked
  → ESP32 flashes new firmware, reboots
  → WiFi AP resumes automatically
```

---

## Library Dependencies

| Library | Source | Already present? |
|---------|--------|-----------------|
| FastLED | Arduino library manager | Yes |
| ArduinoOTA | Bundled with ESP32 Arduino core | Yes |
| ESPAsyncWebServer | Arduino library manager | **No — add** |
| AsyncTCP | Required by ESPAsyncWebServer | **No — add** |

`ESPAsyncWebServer` and `AsyncTCP` must be added to the arduino-cli library
install instructions in `docs/flashing-esp32.md`.

---

## What Is Not In Scope

- WPA2-Enterprise or captive portal for the WiFi AP
- Log persistence across reboots
- Remote control of the display via the debug web page
- mDNS resolution from the Pi (Pi uses `/dev/ttyUSB0`, not the network)
- Any change to the packet protocol, CRC, or command set
