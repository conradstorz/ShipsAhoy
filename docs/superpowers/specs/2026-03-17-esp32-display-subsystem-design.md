# ShipsAhoy — ESP32 Display Subsystem Design

**Date:** 2026-03-17
**Status:** Approved

---

## Overview

The LED ticker display is offloaded from the Raspberry Pi to an ESP32 microcontroller. The ESP32 owns all hardware-timing-critical work: driving WS2812 LEDs, font rendering, and scrolling animation. The Pi sends high-level display commands over UART and treats the display as a best-effort output channel — it continues all its normal responsibilities regardless of whether the ESP32 is responsive.

---

## Hardware Target

- **Display:** WS2812 addressable LEDs, approximately 32 rows × 600 columns (≈19,200 LEDs)
- **Controller:** ESP32 microcontroller
- **Link:** UART over GPIO between Pi and ESP32 (921,600 baud)
- **Wiring:** Multiple parallel WS2812 data lines from ESP32 (one per row or group of rows) to achieve adequate refresh rate. A single chain of 19,200 LEDs at 800 kHz yields <2 FPS; parallel chains of 32 bring this to ~55 FPS.

---

## Design Principle: Best-Effort Display

The Pi treats the ESP32 as a best-effort output sink, not a critical dependency. The ticker service continues — advancing the event queue, marking events displayed, running the idle loop — whether or not the ESP32 acknowledged a command. The `ESP32Driver` sends a command, waits briefly for an ACK, logs a warning on timeout or NACK, and always returns normally. Reconnection is attempted quietly in the background on the next command.

---

## Wire Protocol

### Physical Layer

UART at **921,600 baud** over Pi GPIO pins. This rate pushes a full 320×32 RGB frame (~30 KB) in under 300 ms, while text commands are near-instant.

### Framing

All packets share a common binary frame:

```
[0xAA] [CMD] [LEN_HI] [LEN_LO] [PAYLOAD ...] [CRC8]
```

- `0xAA` — fixed start byte
- `CMD` — 1-byte command identifier
- `LEN` — 2-byte big-endian payload length
- `PAYLOAD` — variable-length command data
- `CRC8` — computed over bytes CMD through end of PAYLOAD

### Commands (Pi → ESP32)

| CMD  | Name         | Payload |
|------|--------------|---------|
| 0x01 | `SCROLL`     | speed_px_per_sec (2B, big-endian) + R G B (3B) + UTF-8 text |
| 0x02 | `STATIC`     | duration_ms (4B, big-endian) + R G B (3B) + UTF-8 text |
| 0x03 | `FRAME`      | width (2B) + height (2B) + raw RGB bytes (width × height × 3) |
| 0x04 | `CLEAR`      | *(none)* |
| 0x05 | `PING`       | *(none)* |
| 0x06 | `BRIGHTNESS` | level (1B, 0–255) |

### Responses (ESP32 → Pi)

| Byte | Meaning |
|------|---------|
| 0x00 | ACK — command accepted and queued |
| 0xFF | NACK — CRC failure, unknown command, or buffer full |

### Emoji and Sprite Encoding

The ESP32 holds a named sprite table in flash (ship, anchor, flag, wave, etc.). The Pi embeds sprite references inline in text using a two-byte escape sequence:

```
\x1E <sprite_id>
```

`ships_ahoy/esp32_protocol.py` contains the authoritative `SPRITES` dict mapping emoji characters and string names to 1-byte IDs. The `encode_text()` function substitutes all known emoji/names with their escape sequences before the text is packed into a command payload. Unknown emoji are stripped silently.

---

## Pi-Side Architecture

### `ships_ahoy/esp32_protocol.py` (new)

Pure protocol encoding — no I/O, fully unit-testable without hardware.

- `CMD_SCROLL`, `CMD_STATIC`, `CMD_FRAME`, `CMD_CLEAR`, `CMD_PING`, `CMD_BRIGHTNESS` — integer constants
- `SPRITES: dict[str, int]` — emoji/name → sprite ID mapping
- `crc8(data: bytes) -> int` — CRC8 over a byte sequence
- `encode_text(text: str) -> bytes` — substitutes emoji with `\x1E` + sprite ID escapes
- `encode_packet(cmd: int, payload: bytes) -> bytes` — builds the full framed packet

### `ships_ahoy/renderer.py` (new)

Pure pixel rendering — no I/O, no serial, fully unit-testable.

- `BitmapFont` — built-in 5×8 pixel bitmap font; same font data shipped to the ESP32 firmware so Pi and ESP32 always agree on layout
- `render_text(text: str, color: RGB, width: int, height: int) -> PixelGrid` — renders a string to a full-width pixel array
- `scroll_frame(pixels: PixelGrid, offset: int, display_width: int) -> PixelGrid` — slices the pixel grid at a given scroll offset to produce one display-sized frame

`RGB = tuple[int, int, int]`
`PixelGrid = list[list[RGB]]` (row-major, `[row][col]`)

### `ships_ahoy/matrix_driver.py` (modified)

The `MatrixDriver` ABC gains one new method:

```python
def send_frame(self, pixels: bytes, width: int, height: int) -> None: ...
```

`StubMatrixDriver` logs the call. `RGBMatrixDriver` is unchanged.

**New `ESP32Driver` class:**

- Constructor: `ESP32Driver(port: str, baud: int = 921600, ack_timeout_sec: float = 0.1)`
- Opens `serial.Serial` on construction; catches and logs `SerialException` without raising
- `scroll_text(text, speed_px_per_sec)` → encodes + sends `SCROLL` packet → waits up to `ack_timeout_sec` for ACK → logs warning on NACK/timeout → returns normally
- `show_static(text, duration_sec)` → same pattern with `STATIC`
- `send_frame(pixels, width, height)` → same pattern with `FRAME`
- `clear()` → same pattern with `CLEAR`
- On serial disconnect: logs error, sets internal `_connected = False`; next command attempts `serial.Serial` reconnection, logs outcome, proceeds regardless

**New `PreviewDriver` class:**

- Implements the full `MatrixDriver` ABC
- On `scroll_text()` / `show_static()`: calls `renderer.render_text()`, stores pixel grid and scroll state
- `get_current_frame(elapsed_sec: float) -> PixelGrid` — advances scroll position by `elapsed_sec × speed`, returns the current display-sized frame slice
- No hardware, no serial; safe to instantiate anywhere

### `ships_ahoy/console_preview.py` (new)

Standalone development utility, not a service.

- Instantiates `PreviewDriver`, renders a configurable text string in a loop
- Uses ANSI 256-color escape codes + Unicode half-block characters (`▀` / `▄`) to render 2 LED rows per terminal line (32 rows → 16 terminal lines)
- Invoked as: `uv run python -m ships_ahoy.console_preview [--text "..."] [--speed N] [--width N]`

### `services/ticker_service.py` (modified)

- Adds `--esp32-port` CLI argument (default: `None`)
- Driver selection at startup:
  - `--esp32-port` provided → `ESP32Driver(port, baud=921600)`
  - No port, Pi library available → `RGBMatrixDriver`
  - Otherwise → `StubMatrixDriver`
- A `PreviewDriver` instance is always created alongside the primary driver and kept in sync. Web SSE stream reads from it.
- No other changes to the service loop — best-effort display is already the natural behaviour given `ESP32Driver` never raises

### `services/web_service.py` (modified)

- New route `GET /ticker/preview` — Server-Sent Events stream
- A background thread ticks `PreviewDriver.get_current_frame()` at ~30 FPS and pushes each frame as:
  ```
  data: {"pixels": [[r,g,b], ...], "width": W, "height": H}\n\n
  ```
  (pixels flattened row-major)
- New template partial `templates/ticker_preview.html` — `<canvas>` element + JavaScript that consumes the SSE stream and draws each LED as a 3×3 px colored rectangle with a 1 px gap (simulating the physical grid)
- Canvas dimensions: `width × 4` px wide, `height × 4` px tall (4 px per LED including gap)

### Config (settings table)

Two new keys added to `_DEFAULT_SETTINGS` in `db.py`:

| Key | Default | Description |
|-----|---------|-------------|
| `esp32_port` | `""` | UART device path, e.g. `/dev/ttyAMA0` |
| `esp32_baud` | `"921600"` | UART baud rate |

Exposed in the web settings form so the port can be changed without a service restart (ticker service re-reads config on each loop iteration).

---

## Error Handling

| Condition | `ESP32Driver` behaviour | Ticker service behaviour |
|-----------|------------------------|--------------------------|
| ACK timeout | Log warning | Continue normally |
| NACK received | Log warning | Continue normally |
| Serial port not found | Log error, `_connected = False` | Continue normally |
| Serial disconnect mid-session | Log error, attempt reconnect on next command | Continue normally |
| CRC mismatch (ESP32 sends NACK) | Log warning | Continue normally |

The Pi never stalls on display errors. Events are marked as displayed after the command is sent, not after ACK is confirmed.

---

## Testing

| Unit | Test approach |
|------|--------------|
| `esp32_protocol.py` | Pure unit tests: packet encoding, CRC8 correctness, emoji substitution, round-trip decode |
| `renderer.py` | Unit tests: known string → expected pixel array, scroll offset arithmetic |
| `ESP32Driver` | Tests with a mock `serial.Serial`: verify correct bytes sent, ACK/NACK/timeout handling, reconnect logic |
| `PreviewDriver` | Unit tests: frame advance, scroll position, pixel grid dimensions |
| `console_preview.py` | Manual / smoke test only |
| Web SSE route | Flask test client: verify `Content-Type: text/event-stream`, frame JSON structure |

---

## File Summary

| File | Status |
|------|--------|
| `ships_ahoy/esp32_protocol.py` | New |
| `ships_ahoy/renderer.py` | New |
| `ships_ahoy/console_preview.py` | New |
| `ships_ahoy/matrix_driver.py` | Modified — add `send_frame()` to ABC, add `ESP32Driver`, add `PreviewDriver` |
| `services/ticker_service.py` | Modified — `--esp32-port` arg, dual-driver (primary + preview) |
| `services/web_service.py` | Modified — SSE route, canvas preview template |
| `ships_ahoy/db.py` | Modified — two new default settings keys |
| `templates/ticker_preview.html` | New |
