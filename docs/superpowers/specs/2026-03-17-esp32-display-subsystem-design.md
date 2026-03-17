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
- **Link:** UART over GPIO between Pi and ESP32 (921,600 baud, fixed deployment constant — not a live setting)
- **Wiring:** Multiple parallel WS2812 data lines from ESP32 (one per row or group of rows) to achieve adequate refresh rate. A single chain of 19,200 LEDs at 800 kHz yields <2 FPS; parallel chains bring this to ~55 FPS.
- **New Python dependency:** `pyserial` (add to `pyproject.toml`)

---

## Design Principle: Best-Effort Display

The Pi treats the ESP32 as a best-effort output sink, not a critical dependency. The ticker service continues — advancing the event queue, marking events displayed, running the idle loop — whether or not the ESP32 acknowledged a command. The `ESP32Driver` sends a command, waits briefly for an ACK, logs a warning on timeout or NACK, and always returns normally. Serial reconnection is attempted quietly on the next command.

"Best-effort" applies to **error recovery**, not to **timing**. `ESP32Driver.scroll_text()` still waits for the estimated scroll duration (calculated from text length and speed) before returning, preserving the same throttling behaviour the ticker service loop depends on. If the ESP32 is unreachable, the estimated duration sleep still occurs so the event queue drains at a predictable rate.

---

## Wire Protocol

### Physical Layer

UART at **921,600 baud** over Pi GPIO pins. This rate pushes a full 320×32 RGB frame (~30 KB) in under 300 ms, while text commands are near-instant. Baud rate is a fixed deployment constant; it is not stored in the settings table.

### Framing

All packets share a common binary frame:

```
[0xAA] [CMD] [LEN_HI] [LEN_LO] [PAYLOAD ...] [CRC8]
```

- `0xAA` — fixed start byte
- `CMD` — 1-byte command identifier
- `LEN` — 2-byte big-endian payload length
- `PAYLOAD` — variable-length command data (maximum 512 bytes total per packet)
- `CRC8` — computed over bytes CMD through end of PAYLOAD using the **CRC8/MAXIM (Dallas 1-Wire) polynomial 0x31**, initial value 0x00, no reflection

`MAX_PAYLOAD_BYTES = 512` is the limit on total payload length (all fields combined). Maximum UTF-8 text bytes per command: `SCROLL` = 512 − 2 (speed) − 3 (color) = **507 bytes**; `STATIC` = 512 − 4 (duration) − 3 (color) = **505 bytes**. `encode_packet` enforces these per-command limits and truncates with a `WARNING` log.

### Commands (Pi → ESP32)

| CMD  | Name         | Payload |
|------|--------------|---------|
| 0x01 | `SCROLL`     | speed_px_per_sec (2B, big-endian) + R G B (3B) + UTF-8 text (max 507 bytes) |
| 0x02 | `STATIC`     | duration_ms (4B, big-endian) + R G B (3B) + UTF-8 text (max 505 bytes) |
| 0x03 | `FRAME`      | width (2B) + height (2B) + raw RGB bytes (width × height × 3) |
| 0x04 | `CLEAR`      | *(none)* |
| 0x05 | `PING`       | *(none)* |
| 0x06 | `BRIGHTNESS` | level (1B, 0–255) |

### Responses (ESP32 → Pi)

| Byte | Meaning |
|------|---------|
| 0x00 | ACK — command accepted and queued |
| 0xFF | NACK — CRC failure, unknown command, oversized payload, or buffer full |

### Emoji and Sprite Encoding

The ESP32 holds a named sprite table in flash (ship, anchor, flag, wave, etc.). The Pi embeds sprite references inline in text using a two-byte escape sequence:

```
\x1E <sprite_id>
```

`ships_ahoy/esp32_protocol.py` contains the authoritative `SPRITES` dict mapping emoji characters and string names to 1-byte IDs. The `encode_text()` function substitutes all known emoji/names with their escape sequences before the text is packed into a command payload. Unknown emoji are stripped and logged at `DEBUG` level (not silently dropped).

---

## Pi-Side Architecture

### `ships_ahoy/esp32_protocol.py` (new)

Pure protocol encoding — no I/O, fully unit-testable without hardware.

- `CMD_SCROLL`, `CMD_STATIC`, `CMD_FRAME`, `CMD_CLEAR`, `CMD_PING`, `CMD_BRIGHTNESS` — integer constants
- `MAX_PAYLOAD_BYTES = 512` — maximum total payload length; per-command text limits derived as above
- `GLYPH_WIDTH_PX = 6` — pixels per character (5 px glyph + 1 px spacing); used by `ESP32Driver` to estimate scroll duration without a full render
- `SPRITES: dict[str, int]` — emoji/name → sprite ID mapping
- `crc8(data: bytes) -> int` — CRC8/MAXIM (polynomial 0x31, init 0x00)
- `encode_text(text: str) -> bytes` — substitutes known emoji with `\x1E` + sprite ID; logs unknown emoji at DEBUG; strips all non-ASCII characters not in SPRITES, guaranteeing single-byte-per-glyph output so that `len(encode_text(text))` gives a correct glyph count for scroll-duration estimation
- `encode_packet(cmd: int, payload: bytes) -> bytes` — builds the full framed packet

### `ships_ahoy/renderer.py` (new)

Pure pixel rendering — no I/O, no serial, fully unit-testable.

- `BitmapFont` — built-in 5×8 pixel bitmap font; same font data shipped to the ESP32 firmware so Pi and ESP32 always agree on glyph layout
- `render_text(text: str, color: RGB, width: int, height: int) -> PixelGrid` — renders a string to a full-width pixel array
- `scroll_frame(pixels: PixelGrid, offset: int, display_width: int) -> PixelGrid` — slices the pixel grid at a given scroll offset to produce one display-sized frame

`RGB = tuple[int, int, int]`
`PixelGrid = list[list[RGB]]` (row-major, `[row][col]`)

### `ships_ahoy/matrix_driver.py` (modified)

The `MatrixDriver` ABC gains one new **concrete** (non-abstract) method with a no-op default body:

```python
def send_frame(self, pixels: bytes, width: int, height: int) -> None:
    """Send a pre-rendered pixel frame. No-op by default."""
```

This keeps `RGBMatrixDriver` and existing drivers unmodified — they inherit the no-op. `StubMatrixDriver` overrides it to log the call. `ESP32Driver` overrides it to encode and send a `FRAME` packet.

**Color parameters:** The existing `scroll_text(text, speed_px_per_sec)` and `show_static(text, duration_sec)` ABC signatures are unchanged. `ESP32Driver` uses white `(255, 255, 255)` as the default LED color. A future `color` parameter can be added to the ABC when multi-color support is needed.

**New `ESP32Driver` class:**

- Constructor: `ESP32Driver(port: str, baud: int = 921600, ack_timeout_sec: float = 0.1)`
- Opens `serial.Serial` on construction; catches and logs `SerialException` without raising; sets `_connected = False`
- `scroll_text(text, speed_px_per_sec)`:
  1. Encodes and sends `SCROLL` packet (if connected)
  2. Waits up to `ack_timeout_sec` for ACK; logs warning on NACK or timeout
  3. Sleeps for estimated scroll duration (`len(encode_text(text)) * GLYPH_WIDTH_PX / speed_px_per_sec`) regardless of ACK outcome — `GLYPH_WIDTH_PX` and `encode_text` are imported from `esp32_protocol`; no call to `renderer.py` is needed
  4. Returns normally
- `show_static(text, duration_sec)`:
  1. Encodes and sends `STATIC` packet (if connected)
  2. Waits up to `ack_timeout_sec` for ACK; logs warning on NACK or timeout
  3. Sleeps `duration_sec` regardless of ACK outcome
  4. Returns normally
- `send_frame(pixels, width, height)` — encodes and sends `FRAME` packet; waits for ACK; logs warning on failure; does not sleep
- `clear()` — encodes and sends `CLEAR` packet; waits for ACK; logs warning on failure; returns normally
- On serial disconnect mid-operation: sets `_connected = False`, logs error; next call to any method attempts `serial.Serial` reconnection once, logs outcome, proceeds into the send attempt or skips if reconnect failed

**New `PreviewDriver` class:**

- Implements the full `MatrixDriver` ABC
- On `scroll_text(text, speed_px_per_sec)` / `show_static(text, duration_sec)`: calls `renderer.render_text()`, stores the pixel grid and scroll parameters; returns immediately (no sleep)
- `get_current_frame(elapsed_sec: float) -> PixelGrid` — advances scroll position by `elapsed_sec × speed`, returns the current display-sized frame slice
- No hardware, no serial; safe to instantiate in any process

### Live Web Preview — Cross-Process Architecture

`ticker_service` and `web_service` are separate processes. They share state via SQLite, consistent with the rest of the system. The preview works as follows:

1. `ticker_service` writes the current display text and speed to a new `display_state` table (a single-row key-value table) on every `scroll_text()` / `show_static()` call, alongside a `display_updated_at` timestamp.
2. `web_service` maintains its own `PreviewDriver` instance. The SSE background thread polls `display_state` every 250 ms; when `display_updated_at` changes, it calls `PreviewDriver.scroll_text()` / `show_static()` to load the new content.
3. The SSE thread ticks `PreviewDriver.get_current_frame()` at ~30 FPS and pushes frames to connected clients.

This keeps the preview eventually consistent with the physical display (within ~250 ms) with no sockets, pipes, or shared memory.

**New `display_state` table** (added in `db.py`):

```sql
CREATE TABLE IF NOT EXISTS display_state (
    id           INTEGER PRIMARY KEY CHECK (id = 1),  -- single row
    text         TEXT,
    speed        REAL,
    mode         TEXT,   -- 'scroll' or 'static'
    duration_ms  INTEGER,
    updated_at   DATETIME
)
```

New db functions: `write_display_state(conn, text, speed, mode, duration_ms)` — implemented as `INSERT OR REPLACE INTO display_state (id, ...) VALUES (1, ...)` to guarantee the single-row constraint on both first and subsequent calls; and `get_display_state(conn) -> Row | None`.

### `ships_ahoy/console_preview.py` (new)

Standalone development utility, not a service. Always uses `PreviewDriver` — never opens the serial port or conflicts with a running `ticker_service`.

- Accepts `--text`, `--speed`, `--width`, `--height` CLI args
- Instantiates `PreviewDriver`, renders the given text in a loop
- Uses ANSI 256-color escape codes + Unicode half-block characters (`▀` / `▄`) to render 2 LED rows per terminal line (32 rows → 16 terminal lines)
- Invoked as: `uv run python -m ships_ahoy.console_preview [--text "..."] [--speed N]`

### `services/ticker_service.py` (modified)

- Adds `--esp32-port` CLI argument (default: `None`)
- Driver selection at startup:
  - `--esp32-port` provided → `ESP32Driver(port)`
  - No port, Pi library available → `RGBMatrixDriver`
  - Otherwise → `StubMatrixDriver`
- After every `driver.scroll_text()` / `driver.show_static()` call, writes current display text to `display_state` via `write_display_state()`
- No other changes to the service loop

### `services/web_service.py` (modified)

- New route `GET /ticker/preview` — Server-Sent Events stream (`Content-Type: text/event-stream`)
- Background thread:
  1. Polls `get_display_state()` every 250 ms; on change, calls `preview_driver.scroll_text()` or `show_static()` to update content
  2. Ticks `preview_driver.get_current_frame(elapsed)` at ~30 FPS
  3. Pushes frame as SSE event: `data: {"pixels": [[r,g,b], ...], "width": W, "height": H}\n\n` (pixels flattened row-major)
- New template `templates/ticker_preview.html` — `<canvas>` element + JavaScript:
  - Connects to `/ticker/preview` via `EventSource`
  - Draws each LED as a 3×3 px colored rectangle with a 1 px gap → 4 px per LED pitch
  - Canvas: `width × 4 - 1` px wide, `height × 4 - 1` px tall (no trailing gap on last row/col)

### Config (settings table)

One new key added to `_DEFAULT_SETTINGS` in `db.py`:

| Key | Default | Description |
|-----|---------|-------------|
| `esp32_port` | `""` | UART device path, e.g. `/dev/ttyAMA0` |

`esp32_baud` is a fixed deployment constant (`921600`) in `esp32_protocol.py`, not a live setting, to prevent Pi/ESP32 baud mismatch from silently breaking the link.

---

## Error Handling

| Condition | `ESP32Driver` behaviour | Ticker service behaviour |
|-----------|------------------------|--------------------------|
| ACK timeout | Log WARNING, complete duration sleep | Continue normally |
| NACK received | Log WARNING, complete duration sleep | Continue normally |
| Serial port not found at startup | Log ERROR, `_connected = False` | Continue normally |
| Serial disconnect mid-session | Log ERROR, attempt reconnect on next call | Continue normally |
| CRC mismatch (ESP32 sends NACK) | Log WARNING | Continue normally |
| Oversized text payload | Truncate, log WARNING, send truncated | Continue normally |
| Unknown emoji in text | Strip character, log DEBUG | Continue normally |

The Pi never stalls on display errors. Events are marked as displayed after the command is sent, not after ACK is confirmed.

---

## Testing

| Unit | Test approach |
|------|--------------|
| `esp32_protocol.py` | Pure unit tests: packet encoding, CRC8/MAXIM correctness against known vectors, emoji substitution, unknown emoji logging, oversized text truncation |
| `renderer.py` | Unit tests: known string → expected pixel array, scroll offset arithmetic, frame bounds |
| `ESP32Driver` | Tests with a mock `serial.Serial`: correct bytes sent, ACK/NACK/timeout handling, duration sleep verified, reconnect logic, best-effort return on all error paths |
| `PreviewDriver` | Unit tests: frame advance, scroll position, pixel grid dimensions |
| `display_state` db functions | Unit tests with `:memory:` DB: write/read round-trip, single-row constraint |
| `console_preview.py` | Manual / smoke test only |
| Web SSE route | Flask test client: verify `Content-Type: text/event-stream`, frame JSON structure |

---

## File Summary

| File | Status |
|------|--------|
| `ships_ahoy/esp32_protocol.py` | New |
| `ships_ahoy/renderer.py` | New |
| `ships_ahoy/console_preview.py` | New |
| `ships_ahoy/matrix_driver.py` | Modified — concrete `send_frame()` on ABC, new `ESP32Driver`, new `PreviewDriver` |
| `ships_ahoy/db.py` | Modified — `display_state` table, `write_display_state()`, `get_display_state()`, one new settings key |
| `services/ticker_service.py` | Modified — `--esp32-port` arg, `write_display_state()` after each display call |
| `services/web_service.py` | Modified — SSE route, `PreviewDriver` background thread, canvas preview template |
| `templates/ticker_preview.html` | New |
| `pyproject.toml` | Modified — add `pyserial` dependency |
