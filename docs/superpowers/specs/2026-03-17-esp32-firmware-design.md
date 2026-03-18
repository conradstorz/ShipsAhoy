# ESP32 Ticker Firmware Design

**Date:** 2026-03-17
**Status:** Draft

---

## Goal

Implement Arduino firmware for an ESP32-S3-WROOM-1 that receives ship ticker commands from a Raspberry Pi over UART and drives a 320×8 WS2812B LED display (10 chained 32×8 panels, 2560 LEDs total).

---

## Hardware

| Component | Detail |
|-----------|--------|
| Microcontroller | ESP32-S3-WROOM-1 (dual-core 240 MHz, 512KB SRAM) |
| Display | 10× WS2812B 5V 32×8 panels, chained left-to-right |
| Total pixels | 320 wide × 8 tall = 2560 LEDs |
| LED order | GRB (WS2812B standard) |
| Data pin | GPIO 48 (configurable in `config.h`) |
| UART pins | Serial2: GPIO 17 (TX→Pi RX), GPIO 18 (RX←Pi TX) |
| Baud rate | 921,600 |

**Panel chaining:** all 10 panels wired in series on a single data line. LED index = `row * 320 + col`. FastLED drives the RMT peripheral automatically; `show()` for 2560 LEDs takes ~7.7ms.

---

## Architecture

Two FreeRTOS tasks pinned to separate cores. No shared memory — communication is exclusively via a FreeRTOS queue.

```
Pi UART TX ──► Serial2 RX
                   │
             [Core 0: uart_task]
             - ring buffer
             - state machine parser
             - CRC8 verify
             - push Command to queue
             - send ACK/NACK
                   │
              FreeRTOS queue (depth 8)
                   │
             [Core 1: display_task]
             - pop Command
             - render text / blit frame
             - scroll animation at 30 FPS
             - FastLED.show()
                   │
              GPIO 48 ──► WS2812B chain
```

### Core 0 — `uart_task`

Reads bytes from Serial2 at 921,600 baud into a 1KB ring buffer. Assembles packets using a state machine. On a valid packet, pushes a `Command` struct onto the queue and sends ACK (`0x00`). On CRC failure or timeout, sends NACK (`0xFF`) and resyncs.

### Core 1 — `display_task`

Pops `Command` structs from the queue. Maintains scroll state. Advances scroll offset each frame, copies the current 320-column window from the rendered canvas into the FastLED buffer, and calls `FastLED.show()`. Targets 30 FPS using elapsed-time tracking for smooth, speed-accurate scrolling.

---

## UART Protocol

Packet format (defined in `ships_ahoy/esp32_protocol.py` on the Pi side):

```
[0xAA][CMD][LEN_HI][LEN_LO][PAYLOAD 0–512 bytes][CRC8]
```

**CRC8:** non-reflected variant, polynomial 0x31, init 0x00. Computed over `CMD + LEN_HI + LEN_LO + PAYLOAD`. NOT CRC8/MAXIM-DOW (which uses bit reflection).

**Commands:**

| CMD | Value | Payload |
|-----|-------|---------|
| CMD_SCROLL | 0x01 | `[speed_hi][speed_lo][r][g][b][text bytes...]` — speed uint16 BE px/sec (clamped to ≥1); text is escape-encoded (see Sprite Escapes below) |
| CMD_STATIC | 0x02 | `[duration_ms: uint32 BE, 4 bytes][r][g][b][text bytes...]` — duration in milliseconds; text is escape-encoded |
| CMD_FRAME | 0x03 | `[w_hi][w_lo][h_hi][h_lo][pixels row-major]` — pixels are R,G,B bytes in that order (FastLED handles GRB reordering); validate `w*h*3 == remaining payload bytes`; clamp/crop to 320×8 if oversized |
| CMD_CLEAR | 0x04 | empty (zero-length payload; CRC still computed over `[0x04, 0x00, 0x00]`) |
| CMD_PING | 0x05 | empty (zero-length payload; CRC still computed over `[0x05, 0x00, 0x00]`) |
| CMD_BRIGHTNESS | 0x06 | `[0–255]` |

**ACK/NACK semantics:** `uart_task` sends ACK (`0x00`) immediately after CRC validation passes, before pushing to the display queue. ACK means "received and CRC valid", not "displayed". NACK (`0xFF`) means CRC failed or parse error — Pi may retransmit. The Pi's ACK timeout is 100ms; firmware must send ACK/NACK within that window.

**CRC over zero-payload packets:** for CMD_CLEAR and CMD_PING, CRC is computed over the 3-byte sequence `[CMD, 0x00, 0x00]` (no payload bytes). Do not skip CRC for empty packets.

### Parser State Machine

1. Wait for start byte `0xAA`
2. Read CMD byte
3. Read LEN_HI + LEN_LO → payload length (0–512)
4. Read exactly `length` payload bytes into static buffer
5. Read CRC8 byte; verify
6. Pass → push Command, send ACK; Fail → send NACK, return to step 1

**Robustness:** 100ms per-packet timeout resets the parser to step 1. Resync by scanning for next `0xAA` after any error.

---

## Font & Text Rendering

The 5×8 bitmap font is shared between Pi (`ships_ahoy/renderer.py`) and firmware (`font.h`). The font array is copied verbatim — both sides agree on glyph layout by construction.

- 95 glyphs, ASCII 32–126
- Column-major encoding: 5 bytes per glyph, bit 0 = top row, bit 7 = bottom row
- 1 blank column spacing between glyphs → 6 px per character

**Sprite escapes:** the Pi's `encode_text()` encodes known emoji as a two-byte escape sequence: escape byte `0x1E` (ASCII Record Separator) followed by a one-byte sprite ID. The firmware detects `0x1E` in the text payload and substitutes the corresponding 8×8 sprite bitmap from `sprites.h`. All text payloads in CMD_SCROLL and CMD_STATIC use this encoding — plain ASCII characters pass through unchanged; only emoji are escaped.

| Sprite ID | Emoji |
|-----------|-------|
| 0x01 | ⚓ |
| 0x02 | 🚢 |
| 0x03 | 🏴 |
| 0x04 | 🌊 |

**Rendering pipeline:**
1. Walk text bytes; build `canvas` pixel buffer in SRAM (width = text_pixel_width, height = 8, 3 bytes RGB per pixel)
2. Vertically centre 8-row glyphs in the 8-row display (no padding needed — exact fit)
3. For `CMD_SCROLL`: advance `scroll_offset` each frame by `speed_px_per_sec × elapsed_sec`; copy 320-column window from canvas into FastLED buffer
4. For `CMD_STATIC`: render once, hold for `duration_ms`, then clear

**Memory:** worst-case 512-byte payload → ~512 × 6 × 8 × 3 ≈ 73KB canvas. Fits comfortably in the S3's 512KB SRAM.

---

## FastLED Integration

```cpp
#define NUM_LEDS     2560
#define DATA_PIN     48
#define LED_TYPE     WS2812B
#define COLOR_ORDER  GRB
```

FastLED uses the ESP32 RMT peripheral automatically. `FastLED.show()` for 2560 LEDs takes ~7.7ms, leaving ~25ms slack per 33ms frame for queue polling and scroll math.

`CMD_BRIGHTNESS` calls `FastLED.setBrightness(value)` — effective on next `show()`.

---

## File Structure

```
esp32_ticker/
├── esp32_ticker.ino       # setup(), loop() (loop is empty — tasks own everything)
├── config.h               # pin assignments, baud rate, queue depth, NUM_LEDS
├── protocol.h / .cpp      # Command struct, packet parser, CRC8, ACK/NACK
├── font.h                 # 5×8 bitmap font (copied from renderer.py)
├── sprites.h              # 8×8 sprite bitmaps for ⚓ 🚢 🏴 🌊
├── renderer.h / .cpp      # render_text(), scroll animation helpers
└── display.h / .cpp       # display_task(), FastLED integration, CMD handlers
```

**Arduino dependencies:**
- FastLED ≥ 3.6 (Arduino Library Manager)

**Build target:** ESP32-S3-WROOM-1, Arduino ESP32 core ≥ 2.0

---

## Validation

No automated tests — the Pi-side protocol tests cover encoding. Firmware validated by:

1. Flash firmware; run `uv run python -m ships_ahoy.console_preview` to confirm ACK/NACK round-trips over Serial2
2. Send `CMD_SCROLL` with known text; verify scrolling on physical display
3. Send `CMD_FRAME` with a test pattern; verify pixel layout matches expected column/row mapping
4. Send `CMD_BRIGHTNESS 0` then `CMD_BRIGHTNESS 255`; verify display dims and brightens
5. Disconnect Pi mid-packet; verify parser resyncs cleanly on reconnect

---

## Open Questions

- Exact GPIO for DATA_PIN: GPIO 48 is the onboard RGB LED on devkit boards — may conflict. Recommend using GPIO 38 or any free non-strapping pin on the production board.
- Power supply: 2560 LEDs at full white ≈ 15A at 5V. Recommend dedicated 5V PSU with common ground to ESP32.
- Panel-to-panel connector type: not specified here — physical wiring is out of scope for this firmware spec.
