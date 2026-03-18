# ESP32 Ticker Firmware Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Arduino C++ firmware for an ESP32-S3-WROOM-1 that receives UART commands from a Raspberry Pi and drives a 320×8 WS2812B LED ticker display.

**Architecture:** Two FreeRTOS tasks on separate cores — `uart_task` (Core 0) parses binary packets from Serial2 and pushes decoded `Command` structs onto a FreeRTOS queue; `display_task` (Core 1) pops commands, builds a column bitmask map from text, and renders scrolling frames into the FastLED buffer at 30 FPS.

**Tech Stack:** Arduino framework, FastLED ≥ 3.6, ESP32-S3-WROOM-1 (Arduino ESP32 core ≥ 2.0), arduino-cli for command-line build verification.

**Memory note:** The spec describes a full RGB canvas (73KB worst-case). This plan uses a `col_map[]` approach instead: one `uint8_t` per pixel column storing the 8-row bitmask. Rendering applies the command color on-the-fly. Max size: 3072 bytes (512 chars × 6 px). Functionally identical output, 24× less SRAM.

**Spec:** `docs/superpowers/specs/2026-03-17-esp32-firmware-design.md`

---

## Prerequisites

Install arduino-cli and the ESP32 core once before starting:

```bash
# Install arduino-cli (https://arduino.github.io/arduino-cli/latest/installation/)
arduino-cli core update-index
arduino-cli core install esp32:esp32

# Install FastLED library
arduino-cli lib install "FastLED"
```

Compile check command (run from repo root, no hardware required):
```bash
arduino-cli compile --fqbn esp32:esp32:esp32s3 esp32_ticker
```

Expected output: `Sketch uses ... bytes` — no errors.

Upload command (requires hardware connected):
```bash
arduino-cli upload -p /dev/ttyUSB0 --fqbn esp32:esp32:esp32s3 esp32_ticker
arduino-cli monitor -p /dev/ttyUSB0 -c baudrate=115200
```

---

## Chunk 1: Foundation — Scaffold, Config, Font, Sprites

### Task 1: Project scaffold and config.h

**Files:**
- Create: `esp32_ticker/esp32_ticker.ino`
- Create: `esp32_ticker/config.h`

- [ ] **Step 1.1: Create `esp32_ticker/esp32_ticker.ino`** (stub — will be filled in Task 8)

```cpp
// esp32_ticker.ino — main sketch entry point
// All work is done in FreeRTOS tasks defined in protocol.cpp and display.cpp.
// setup() starts those tasks; loop() is empty.

#include "config.h"
#include "protocol.h"
#include "display.h"

void setup() {
    Serial.begin(115200);
    Serial.println("[esp32_ticker] booting");
}

void loop() {
    // Tasks own all execution. loop() never runs meaningful code.
    vTaskDelay(portMAX_DELAY);
}
```

- [ ] **Step 1.2: Create `esp32_ticker/config.h`**

```cpp
#pragma once

// ── Display ──────────────────────────────────────────────────────────────────
#define DISPLAY_WIDTH    320      // LEDs per row (10 panels × 32)
#define DISPLAY_HEIGHT   8        // LED rows
#define NUM_LEDS         (DISPLAY_WIDTH * DISPLAY_HEIGHT)  // 2560
#define DATA_PIN         38       // WS2812B data line (GPIO 38; change if needed)
                                  // Note: GPIO 48 is the onboard RGB LED on devkits
                                  //       — use a different pin on custom PCBs.

// ── UART ─────────────────────────────────────────────────────────────────────
#define UART_BAUD        921600
#define UART_RX_PIN      18       // Serial2 RX ← Pi TX
#define UART_TX_PIN      17       // Serial2 TX → Pi RX

// ── Protocol ─────────────────────────────────────────────────────────────────
#define PKT_START        0xAA
#define CMD_SCROLL       0x01
#define CMD_STATIC       0x02
#define CMD_FRAME        0x03
#define CMD_CLEAR        0x04
#define CMD_PING         0x05
#define CMD_BRIGHTNESS   0x06
#define ACK_BYTE         0x00
#define NACK_BYTE        0xFF
#define MAX_PAYLOAD      512
#define PKT_TIMEOUT_MS   100      // reset parser if no byte arrives within this window

// ── Text rendering ────────────────────────────────────────────────────────────
#define GLYPH_W          5        // pixel columns per font glyph
#define GLYPH_H          8        // pixel rows per font glyph (= DISPLAY_HEIGHT)
#define GLYPH_SPACING    1        // blank columns between glyphs
#define GLYPH_PITCH      (GLYPH_W + GLYPH_SPACING)  // 6 px per character
#define SPRITE_ESCAPE    0x1E     // escape byte preceding a sprite ID in text payloads
#define MAX_TEXT_COLS    (MAX_PAYLOAD * GLYPH_PITCH)  // 3072 — worst-case col_map width

// ── FreeRTOS ─────────────────────────────────────────────────────────────────
#define CMD_QUEUE_DEPTH  8
#define FRAME_MS         33       // ~30 FPS
```

- [ ] **Step 1.3: Verify compile**

```bash
arduino-cli compile --fqbn esp32:esp32:esp32s3 esp32_ticker
```

Expected: compiles with no errors (only the stub .ino, no tasks yet).

- [ ] **Step 1.4: Commit**

```bash
git add esp32_ticker/
git commit -m "feat: scaffold esp32_ticker project with config.h"
```

---

### Task 2: font.h — 5×8 bitmap font

**Files:**
- Create: `esp32_ticker/font.h`

The font data is copied verbatim from `ships_ahoy/renderer.py` (`_FONT_DATA`). Each entry is 5 column bytes for ASCII 32–126. Column-major encoding: bit 0 = top row, bit 7 = bottom row. Stored in flash with `PROGMEM` to save SRAM.

- [ ] **Step 2.1: Create `esp32_ticker/font.h`**

```cpp
#pragma once
#include <Arduino.h>
#include <pgmspace.h>

// 5×8 bitmap font, ASCII 32–126 (95 glyphs).
// Column-major: each byte is one pixel column, bit 0 = top row.
// Identical to ships_ahoy/renderer.py _FONT_DATA.
static const uint8_t FONT_DATA[95][5] PROGMEM = {
    {0x00,0x00,0x00,0x00,0x00},  // 32  space
    {0x00,0x00,0x5F,0x00,0x00},  // 33  !
    {0x00,0x07,0x00,0x07,0x00},  // 34  "
    {0x14,0x7F,0x14,0x7F,0x14},  // 35  #
    {0x24,0x2A,0x7F,0x2A,0x12},  // 36  $
    {0x23,0x13,0x08,0x64,0x62},  // 37  %
    {0x36,0x49,0x55,0x22,0x50},  // 38  &
    {0x00,0x05,0x03,0x00,0x00},  // 39  '
    {0x00,0x1C,0x22,0x41,0x00},  // 40  (
    {0x00,0x41,0x22,0x1C,0x00},  // 41  )
    {0x08,0x2A,0x1C,0x2A,0x08},  // 42  *
    {0x08,0x08,0x3E,0x08,0x08},  // 43  +
    {0x00,0x50,0x30,0x00,0x00},  // 44  ,
    {0x08,0x08,0x08,0x08,0x08},  // 45  -
    {0x00,0x60,0x60,0x00,0x00},  // 46  .
    {0x20,0x10,0x08,0x04,0x02},  // 47  /
    {0x3E,0x51,0x49,0x45,0x3E},  // 48  0
    {0x00,0x42,0x7F,0x40,0x00},  // 49  1
    {0x42,0x61,0x51,0x49,0x46},  // 50  2
    {0x21,0x41,0x45,0x4B,0x31},  // 51  3
    {0x18,0x14,0x12,0x7F,0x10},  // 52  4
    {0x27,0x45,0x45,0x45,0x39},  // 53  5
    {0x3C,0x4A,0x49,0x49,0x30},  // 54  6
    {0x01,0x71,0x09,0x05,0x03},  // 55  7
    {0x36,0x49,0x49,0x49,0x36},  // 56  8
    {0x06,0x49,0x49,0x29,0x1E},  // 57  9
    {0x00,0x36,0x36,0x00,0x00},  // 58  :
    {0x00,0x56,0x36,0x00,0x00},  // 59  ;
    {0x00,0x08,0x14,0x22,0x41},  // 60  <
    {0x14,0x14,0x14,0x14,0x14},  // 61  =
    {0x41,0x22,0x14,0x08,0x00},  // 62  >
    {0x02,0x01,0x51,0x09,0x06},  // 63  ?
    {0x32,0x49,0x79,0x41,0x3E},  // 64  @
    {0x7E,0x11,0x11,0x11,0x7E},  // 65  A
    {0x7F,0x49,0x49,0x49,0x36},  // 66  B
    {0x3E,0x41,0x41,0x41,0x22},  // 67  C
    {0x7F,0x41,0x41,0x22,0x1C},  // 68  D
    {0x7F,0x49,0x49,0x49,0x41},  // 69  E
    {0x7F,0x09,0x09,0x09,0x01},  // 70  F
    {0x3E,0x41,0x49,0x49,0x7A},  // 71  G
    {0x7F,0x08,0x08,0x08,0x7F},  // 72  H
    {0x00,0x41,0x7F,0x41,0x00},  // 73  I
    {0x20,0x40,0x41,0x3F,0x01},  // 74  J
    {0x7F,0x08,0x14,0x22,0x41},  // 75  K
    {0x7F,0x40,0x40,0x40,0x40},  // 76  L
    {0x7F,0x02,0x04,0x02,0x7F},  // 77  M
    {0x7F,0x04,0x08,0x10,0x7F},  // 78  N
    {0x3E,0x41,0x41,0x41,0x3E},  // 79  O
    {0x7F,0x09,0x09,0x09,0x06},  // 80  P
    {0x3E,0x41,0x51,0x21,0x5E},  // 81  Q
    {0x7F,0x09,0x19,0x29,0x46},  // 82  R
    {0x46,0x49,0x49,0x49,0x31},  // 83  S
    {0x01,0x01,0x7F,0x01,0x01},  // 84  T
    {0x3F,0x40,0x40,0x40,0x3F},  // 85  U
    {0x1F,0x20,0x40,0x20,0x1F},  // 86  V
    {0x3F,0x40,0x38,0x40,0x3F},  // 87  W
    {0x63,0x14,0x08,0x14,0x63},  // 88  X
    {0x07,0x08,0x70,0x08,0x07},  // 89  Y
    {0x61,0x51,0x49,0x45,0x43},  // 90  Z
    {0x00,0x7F,0x41,0x41,0x00},  // 91  [
    {0x02,0x04,0x08,0x10,0x20},  // 92  backslash
    {0x00,0x41,0x41,0x7F,0x00},  // 93  ]
    {0x04,0x02,0x01,0x02,0x04},  // 94  ^
    {0x40,0x40,0x40,0x40,0x40},  // 95  _
    {0x00,0x01,0x02,0x04,0x00},  // 96  `
    {0x20,0x54,0x54,0x54,0x78},  // 97  a
    {0x7F,0x48,0x44,0x44,0x38},  // 98  b
    {0x38,0x44,0x44,0x44,0x20},  // 99  c
    {0x38,0x44,0x44,0x48,0x7F},  // 100 d
    {0x38,0x54,0x54,0x54,0x18},  // 101 e
    {0x08,0x7E,0x09,0x01,0x02},  // 102 f
    {0x0C,0x52,0x52,0x52,0x3E},  // 103 g
    {0x7F,0x08,0x04,0x04,0x78},  // 104 h
    {0x00,0x44,0x7D,0x40,0x00},  // 105 i
    {0x20,0x40,0x44,0x3D,0x00},  // 106 j
    {0x7F,0x10,0x28,0x44,0x00},  // 107 k
    {0x00,0x41,0x7F,0x40,0x00},  // 108 l
    {0x7C,0x04,0x18,0x04,0x78},  // 109 m
    {0x7C,0x08,0x04,0x04,0x78},  // 110 n
    {0x38,0x44,0x44,0x44,0x38},  // 111 o
    {0x7C,0x14,0x14,0x14,0x08},  // 112 p
    {0x08,0x14,0x14,0x18,0x7C},  // 113 q
    {0x7C,0x08,0x04,0x04,0x08},  // 114 r
    {0x48,0x54,0x54,0x54,0x20},  // 115 s
    {0x04,0x3F,0x44,0x40,0x20},  // 116 t
    {0x3C,0x40,0x40,0x20,0x7C},  // 117 u
    {0x1C,0x20,0x40,0x20,0x1C},  // 118 v
    {0x3C,0x40,0x30,0x40,0x3C},  // 119 w
    {0x44,0x28,0x10,0x28,0x44},  // 120 x
    {0x0C,0x50,0x50,0x50,0x3C},  // 121 y
    {0x44,0x64,0x54,0x4C,0x44},  // 122 z
    {0x00,0x08,0x36,0x41,0x00},  // 123 {
    {0x00,0x00,0x7F,0x00,0x00},  // 124 |
    {0x00,0x41,0x36,0x08,0x00},  // 125 }
    {0x08,0x08,0x2A,0x1C,0x08},  // 126 ~
};

// Return the 5 column bytes for ASCII character ch.
// ch must be in range 32–126; returns blank glyph otherwise.
inline void font_get_cols(char ch, uint8_t out[5]) {
    uint8_t idx = (uint8_t)ch;
    if (idx >= 32 && idx <= 126) {
        memcpy_P(out, FONT_DATA[idx - 32], 5);
    } else {
        memset(out, 0, 5);
    }
}
```

- [ ] **Step 2.2: Verify compile**

```bash
arduino-cli compile --fqbn esp32:esp32:esp32s3 esp32_ticker
```

Expected: compiles with no errors.

- [ ] **Step 2.3: Commit**

```bash
git add esp32_ticker/font.h
git commit -m "feat: add 5x8 bitmap font array (PROGMEM)"
```

---

### Task 3: sprites.h — emoji sprite bitmaps

**Files:**
- Create: `esp32_ticker/sprites.h`

Each sprite is 5 columns × 8 rows (same pitch as font glyphs, 6 px including spacing). Column-major encoding matches the font: bit 0 = top row. Sprite IDs match `ships_ahoy/esp32_protocol.py` SPRITES dict.

- [ ] **Step 3.1: Create `esp32_ticker/sprites.h`**

```cpp
#pragma once
#include <Arduino.h>
#include <pgmspace.h>
#include "config.h"

// Sprite bitmaps: 5 columns × 8 rows, column-major (bit 0 = top row).
// Same pitch as font glyphs (5 data cols + 1 blank spacing = 6 px total).
// Sprite IDs match ships_ahoy/esp32_protocol.py SPRITES dict.
//
// ID 0x01 = ⚓  ID 0x02 = 🚢  ID 0x03 = 🏴  ID 0x04 = 🌊

#define NUM_SPRITES 4

static const uint8_t SPRITE_DATA[NUM_SPRITES][5] PROGMEM = {
    // 0x01 ⚓ anchor
    // Row layout (. = off, X = on):
    //  Col:  0    1    2    3    4
    // Row0:  .    X    X    X    .
    // Row1:  X    .    .    .    X
    // Row2:  .    X    X    X    .
    // Row3:  .    .    X    .    .
    // Row4:  X    .    X    .    X
    // Row5:  .    X    X    X    .
    // Row6:  .    .    X    .    .
    // Row7:  .    .    .    .    .
    {0x12, 0x25, 0x7D, 0x25, 0x12},

    // 0x02 🚢 ship
    // Row layout:
    //  Col:  0    1    2    3    4
    // Row0:  .    .    .    .    .
    // Row1:  .    .    X    .    .
    // Row2:  .    X    X    X    .
    // Row3:  X    X    X    X    X
    // Row4:  X    X    X    X    X
    // Row5:  .    X    X    X    .
    // Row6:  .    .    .    .    .
    // Row7:  .    .    .    .    .
    {0x18, 0x3C, 0x3E, 0x3C, 0x18},

    // 0x03 🏴 flag
    // Row layout:
    //  Col:  0    1    2    3    4
    // Row0:  X    .    .    .    .
    // Row1:  X    X    X    X    .
    // Row2:  X    X    X    X    .
    // Row3:  X    X    X    X    .
    // Row4:  X    .    .    .    .
    // Row5:  X    .    .    .    .
    // Row6:  X    .    .    .    .
    // Row7:  X    .    .    .    .
    {0xFF, 0x0E, 0x0E, 0x0E, 0x00},

    // 0x04 🌊 wave
    // Row layout:
    //  Col:  0    1    2    3    4
    // Row0:  .    .    .    .    .
    // Row1:  X    .    .    .    X
    // Row2:  X    X    .    X    X
    // Row3:  .    X    X    X    .
    // Row4:  .    .    .    .    .
    // Row5:  X    .    .    .    X
    // Row6:  X    X    .    X    X
    // Row7:  .    X    X    X    .
    {0x66, 0xCC, 0x88, 0xCC, 0x66},
};

// Return the 5 column bytes for sprite ID (1-based).
// Returns false if ID is unknown; out[] is zeroed in that case.
inline bool sprite_get_cols(uint8_t id, uint8_t out[5]) {
    if (id < 1 || id > NUM_SPRITES) {
        memset(out, 0, 5);
        return false;
    }
    memcpy_P(out, SPRITE_DATA[id - 1], 5);
    return true;
}
```

- [ ] **Step 3.2: Verify compile**

```bash
arduino-cli compile --fqbn esp32:esp32:esp32s3 esp32_ticker
```

- [ ] **Step 3.3: Commit**

```bash
git add esp32_ticker/sprites.h
git commit -m "feat: add sprite bitmaps for anchor, ship, flag, wave"
```

---

## Chunk 2: Protocol Layer

### Task 4: protocol.h/.cpp — CRC8 and Command struct

**Files:**
- Create: `esp32_ticker/protocol.h`
- Create: `esp32_ticker/protocol.cpp`

- [ ] **Step 4.1: Create `esp32_ticker/protocol.h`**

```cpp
#pragma once
#include <Arduino.h>
#include "config.h"

// ── Command struct ────────────────────────────────────────────────────────────

enum DisplayMode { MODE_SCROLL, MODE_STATIC, MODE_FRAME, MODE_CLEAR, MODE_BRIGHTNESS };

struct Command {
    DisplayMode mode;
    uint16_t    speed;          // px/sec (CMD_SCROLL)
    uint32_t    duration_ms;    // (CMD_STATIC)
    uint8_t     r, g, b;       // text color
    uint8_t     brightness;    // (CMD_BRIGHTNESS)
    uint8_t     text[MAX_PAYLOAD];  // escape-encoded text bytes
    uint16_t    text_len;
    uint8_t     frame[MAX_PAYLOAD]; // raw RGB pixel bytes (CMD_FRAME)
    uint16_t    frame_w, frame_h;
};

// ── CRC8 ──────────────────────────────────────────────────────────────────────
// Non-reflected CRC8, polynomial 0x31, init 0x00.
// Matches ships_ahoy/esp32_protocol.py crc8().
uint8_t crc8(const uint8_t* data, uint16_t len);

// ── UART task ─────────────────────────────────────────────────────────────────
// FreeRTOS task pinned to Core 0. Reads Serial2, parses packets,
// pushes Commands onto cmd_queue, sends ACK/NACK.
extern QueueHandle_t cmd_queue;
void uart_task(void* pvParameters);
void protocol_init();  // call from setup() to create queue and start task
```

- [ ] **Step 4.2: Create `esp32_ticker/protocol.cpp`** (CRC8 only for now)

```cpp
#include "protocol.h"

QueueHandle_t cmd_queue = nullptr;

// Non-reflected CRC8: poly=0x31, init=0x00.
// Verified: crc8({0x01}, 1) == 0x31
//           crc8({0xAA, 0xAA}, 2) == 0x36
uint8_t crc8(const uint8_t* data, uint16_t len) {
    uint8_t crc = 0x00;
    for (uint16_t i = 0; i < len; i++) {
        crc ^= data[i];
        for (uint8_t j = 0; j < 8; j++) {
            if (crc & 0x80) {
                crc = (crc << 1) ^ 0x31;
            } else {
                crc <<= 1;
            }
        }
    }
    return crc;
}
```

- [ ] **Step 4.3: Add CRC8 self-test to `esp32_ticker.ino` setup() temporarily**

Open `esp32_ticker.ino` and add to `setup()`:

```cpp
#include "protocol.h"

void setup() {
    Serial.begin(115200);
    delay(1000);

    // CRC8 self-test — remove after verification
    uint8_t v1[] = {0x01};
    uint8_t v2[] = {0xAA, 0xAA};
    Serial.printf("crc8(0x01)       = 0x%02X (expect 0x31)\n", crc8(v1, 1));
    Serial.printf("crc8(0xAA,0xAA)  = 0x%02X (expect 0x36)\n", crc8(v2, 2));
}
```

- [ ] **Step 4.4: Flash and verify CRC8 via Serial Monitor**

```bash
arduino-cli compile --fqbn esp32:esp32:esp32s3 esp32_ticker
arduino-cli upload -p /dev/ttyUSB0 --fqbn esp32:esp32:esp32s3 esp32_ticker
arduino-cli monitor -p /dev/ttyUSB0 -c baudrate=115200
```

Expected Serial Monitor output:
```
crc8(0x01)       = 0x31 (expect 0x31)
crc8(0xAA,0xAA)  = 0x36 (expect 0x36)
```

- [ ] **Step 4.5: Remove the CRC8 self-test lines from setup()**

Revert `setup()` to the stub from Task 1 (just `Serial.begin` and the boot message).

- [ ] **Step 4.6: Commit**

```bash
git add esp32_ticker/protocol.h esp32_ticker/protocol.cpp esp32_ticker/esp32_ticker.ino
git commit -m "feat: add Command struct and CRC8 implementation"
```

---

### Task 5: uart_task — packet parser state machine

**Files:**
- Modify: `esp32_ticker/protocol.cpp`

Add `uart_task()` and `protocol_init()` to `protocol.cpp`:

- [ ] **Step 5.1: Add uart_task to `protocol.cpp`**

Append below the `crc8` function:

```cpp
// ── Parser state machine ──────────────────────────────────────────────────────

enum ParseState {
    WAIT_START,
    WAIT_CMD,
    WAIT_LEN_HI,
    WAIT_LEN_LO,
    WAIT_PAYLOAD,
    WAIT_CRC,
};

static bool read_byte_timeout(uint8_t* out, uint32_t timeout_ms) {
    uint32_t start = millis();
    while (!Serial2.available()) {
        if (millis() - start >= timeout_ms) return false;
        vTaskDelay(1);
    }
    *out = (uint8_t)Serial2.read();
    return true;
}

void uart_task(void* pvParameters) {
    static uint8_t payload_buf[MAX_PAYLOAD];
    ParseState state = WAIT_START;
    uint8_t    cmd = 0;
    uint16_t   payload_len = 0;
    uint16_t   bytes_read = 0;
    uint8_t    b;

    for (;;) {
        switch (state) {

        case WAIT_START:
            if (!read_byte_timeout(&b, portMAX_DELAY)) break;
            if (b == PKT_START) state = WAIT_CMD;
            break;

        case WAIT_CMD:
            if (!read_byte_timeout(&b, PKT_TIMEOUT_MS)) { state = WAIT_START; break; }
            cmd = b;
            state = WAIT_LEN_HI;
            break;

        case WAIT_LEN_HI:
            if (!read_byte_timeout(&b, PKT_TIMEOUT_MS)) { state = WAIT_START; break; }
            payload_len = (uint16_t)b << 8;
            state = WAIT_LEN_LO;
            break;

        case WAIT_LEN_LO:
            if (!read_byte_timeout(&b, PKT_TIMEOUT_MS)) { state = WAIT_START; break; }
            payload_len |= b;
            if (payload_len > MAX_PAYLOAD) {
                Serial.printf("[uart] oversized payload %u — dropping\n", payload_len);
                state = WAIT_START;
                break;
            }
            bytes_read = 0;
            state = (payload_len > 0) ? WAIT_PAYLOAD : WAIT_CRC;
            break;

        case WAIT_PAYLOAD:
            if (!read_byte_timeout(&b, PKT_TIMEOUT_MS)) { state = WAIT_START; break; }
            payload_buf[bytes_read++] = b;
            if (bytes_read >= payload_len) state = WAIT_CRC;
            break;

        case WAIT_CRC: {
            if (!read_byte_timeout(&b, PKT_TIMEOUT_MS)) { state = WAIT_START; break; }
            uint8_t rx_crc = b;

            // Compute CRC over [cmd, len_hi, len_lo, payload...]
            uint8_t crc_buf[3 + MAX_PAYLOAD];
            crc_buf[0] = cmd;
            crc_buf[1] = (uint8_t)(payload_len >> 8);
            crc_buf[2] = (uint8_t)(payload_len & 0xFF);
            memcpy(crc_buf + 3, payload_buf, payload_len);
            uint8_t expected = crc8(crc_buf, 3 + payload_len);

            if (rx_crc != expected) {
                Serial.printf("[uart] CRC fail cmd=0x%02X got=0x%02X exp=0x%02X\n",
                              cmd, rx_crc, expected);
                Serial2.write(NACK_BYTE);
                state = WAIT_START;
                break;
            }

            // ── Decode payload into Command ───────────────────────────────
            Command c;
            memset(&c, 0, sizeof(c));

            bool valid = true;
            switch (cmd) {
            case CMD_SCROLL:
                if (payload_len < 5) { valid = false; break; }
                c.mode  = MODE_SCROLL;
                c.speed = ((uint16_t)payload_buf[0] << 8) | payload_buf[1];
                if (c.speed < 1) c.speed = 1;
                c.r = payload_buf[2]; c.g = payload_buf[3]; c.b = payload_buf[4];
                c.text_len = payload_len - 5;
                memcpy(c.text, payload_buf + 5, c.text_len);
                break;

            case CMD_STATIC:
                if (payload_len < 7) { valid = false; break; }
                c.mode = MODE_STATIC;
                c.duration_ms = ((uint32_t)payload_buf[0] << 24) |
                                ((uint32_t)payload_buf[1] << 16) |
                                ((uint32_t)payload_buf[2] <<  8) |
                                 (uint32_t)payload_buf[3];
                c.r = payload_buf[4]; c.g = payload_buf[5]; c.b = payload_buf[6];
                c.text_len = payload_len - 7;
                memcpy(c.text, payload_buf + 7, c.text_len);
                break;

            case CMD_FRAME: {
                if (payload_len < 4) { valid = false; break; }
                c.frame_w = ((uint16_t)payload_buf[0] << 8) | payload_buf[1];
                c.frame_h = ((uint16_t)payload_buf[2] << 8) | payload_buf[3];
                // Reject frames that exceed display dimensions (cropping would corrupt stride)
                if (c.frame_w > DISPLAY_WIDTH || c.frame_h > DISPLAY_HEIGHT) {
                    Serial.printf("[uart] FRAME too large %ux%u — NACK\n", c.frame_w, c.frame_h);
                    valid = false; break;
                }
                uint32_t expected_px = (uint32_t)c.frame_w * c.frame_h * 3;
                uint16_t actual_px   = payload_len - 4;
                if (expected_px != actual_px) { valid = false; break; }
                c.mode = MODE_FRAME;
                memcpy(c.frame, payload_buf + 4, min((uint32_t)MAX_PAYLOAD, expected_px));
                break;
            }

            case CMD_CLEAR:
                c.mode = MODE_CLEAR;
                break;

            case CMD_PING:
                // ACK-only. No queue push needed.
                Serial2.write(ACK_BYTE);
                state = WAIT_START;
                valid = false;  // skip the queue-send path below
                break;

            case CMD_BRIGHTNESS:
                if (payload_len < 1) { valid = false; break; }
                c.mode = MODE_BRIGHTNESS;  // dedicated mode — does NOT clear display
                c.brightness = payload_buf[0];
                // brightness=0 means "no change" — display_task checks > 0
                break;

            default:
                Serial.printf("[uart] unknown cmd=0x%02X — ignoring\n", cmd);
                valid = false;
                break;
            }

            if (!valid) {
                // CMD_PING already sent ACK; everything else gets NACK
                if (cmd != CMD_PING) {
                    Serial2.write(NACK_BYTE);
                }
                state = WAIT_START;
                break;
            }

            Serial2.write(ACK_BYTE);
            xQueueSend(cmd_queue, &c, 0);  // non-blocking; drop if queue full
            state = WAIT_START;
            break;
        }

        } // switch
    }
}

void protocol_init() {
    cmd_queue = xQueueCreate(CMD_QUEUE_DEPTH, sizeof(Command));
    Serial2.begin(UART_BAUD, SERIAL_8N1, UART_RX_PIN, UART_TX_PIN);
    xTaskCreatePinnedToCore(uart_task, "uart_task", 8192, nullptr, 1, nullptr, 0);
    Serial.println("[protocol] uart_task started on Core 0");
}
```

- [ ] **Step 5.2: Verify compile**

```bash
arduino-cli compile --fqbn esp32:esp32:esp32s3 esp32_ticker
```

Expected: no errors.

- [ ] **Step 5.3: Commit**

```bash
git add esp32_ticker/protocol.cpp
git commit -m "feat: add uart_task packet parser state machine"
```

---

## Chunk 3: Renderer, Display Task, Final Integration

### Task 6: renderer.h/.cpp — column map builder

**Files:**
- Create: `esp32_ticker/renderer.h`
- Create: `esp32_ticker/renderer.cpp`

The renderer walks escape-encoded text bytes, looks up font/sprite column bitmasks, and writes them into a global `col_map[]` array (one `uint8_t` per pixel column). `render_to_leds()` reads `col_map` at a given scroll offset and writes directly into the FastLED `leds[]` buffer.

- [ ] **Step 6.1: Create `esp32_ticker/renderer.h`**

```cpp
#pragma once
#include <Arduino.h>
#include <FastLED.h>
#include "config.h"

extern CRGB leds[NUM_LEDS];

// col_map[i] is the 8-row bitmask for pixel column i (bit 0 = top row).
// Built by build_col_map(). Valid columns: 0 .. col_map_width-1.
extern uint8_t  col_map[MAX_TEXT_COLS];
extern uint16_t col_map_width;  // number of valid columns

// Build col_map from escape-encoded text. Call once per CMD_SCROLL/CMD_STATIC.
void build_col_map(const uint8_t* text, uint16_t len);

// Write the 320-column window starting at pixel column `offset` into leds[].
// Lit pixels use color (r,g,b); dark pixels use black.
void render_to_leds(int32_t offset, uint8_t r, uint8_t g, uint8_t b);
```

- [ ] **Step 6.2: Create `esp32_ticker/renderer.cpp`**

```cpp
#include "renderer.h"
#include "font.h"
#include "sprites.h"

CRGB leds[NUM_LEDS];

uint8_t  col_map[MAX_TEXT_COLS];
uint16_t col_map_width = 0;

void build_col_map(const uint8_t* text, uint16_t len) {
    uint16_t col = 0;
    uint8_t  cols[5];

    for (uint16_t i = 0; i < len && col + GLYPH_PITCH <= MAX_TEXT_COLS; ) {
        uint8_t b = text[i++];

        if (b == SPRITE_ESCAPE && i < len) {
            // Sprite escape: next byte is sprite ID
            uint8_t id = text[i++];
            if (!sprite_get_cols(id, cols)) {
                memset(cols, 0, 5);
            }
        } else if (b >= 32 && b <= 126) {
            font_get_cols((char)b, cols);
        } else {
            // Unknown byte — render as blank glyph
            memset(cols, 0, 5);
        }

        // Write 5 data columns then 1 blank spacing column
        for (uint8_t c = 0; c < GLYPH_W; c++) {
            col_map[col++] = cols[c];
        }
        col_map[col++] = 0x00;  // spacing
    }

    col_map_width = col;
}

void render_to_leds(int32_t offset, uint8_t r, uint8_t g, uint8_t b) {
    for (uint16_t display_col = 0; display_col < DISPLAY_WIDTH; display_col++) {
        int32_t src = offset + (int32_t)display_col;
        uint8_t mask = (src >= 0 && src < (int32_t)col_map_width)
                       ? col_map[src] : 0x00;
        for (uint16_t row = 0; row < DISPLAY_HEIGHT; row++) {
            uint16_t idx = row * DISPLAY_WIDTH + display_col;
            if ((mask >> row) & 1) {
                leds[idx] = CRGB(r, g, b);
            } else {
                leds[idx] = CRGB::Black;
            }
        }
    }
}
```

- [ ] **Step 6.3: Verify compile**

```bash
arduino-cli compile --fqbn esp32:esp32:esp32s3 esp32_ticker
```

- [ ] **Step 6.4: Commit**

```bash
git add esp32_ticker/renderer.h esp32_ticker/renderer.cpp
git commit -m "feat: add column-map renderer and render_to_leds"
```

---

### Task 7: display.h/.cpp — display_task

**Files:**
- Create: `esp32_ticker/display.h`
- Create: `esp32_ticker/display.cpp`

- [ ] **Step 7.1: Create `esp32_ticker/display.h`**

```cpp
#pragma once

void display_init();  // call from setup() — starts display_task on Core 1
```

- [ ] **Step 7.2: Create `esp32_ticker/display.cpp`**

```cpp
#include "display.h"
#include <FastLED.h>
#include "config.h"
#include "protocol.h"
#include "renderer.h"

static void display_task(void* pvParameters) {
    FastLED.addLeds<WS2812B, DATA_PIN, GRB>(leds, NUM_LEDS);
    FastLED.setBrightness(64);  // start at ~25% — safe for initial power-on
    FastLED.clear(true);

    Serial.println("[display] display_task started on Core 1");

    // Current display state
    DisplayMode current_mode = MODE_CLEAR;
    float       scroll_offset  = 0.0f;
    float       scroll_speed   = 40.0f;  // px/sec
    uint8_t     color_r = 255, color_g = 255, color_b = 255;
    uint32_t    static_until_ms = 0;

    // Frame timing
    uint32_t last_ms = millis();

    Command cmd;

    for (;;) {
        uint32_t now = millis();
        float elapsed = (now - last_ms) / 1000.0f;
        last_ms = now;

        // ── Check for new command ─────────────────────────────────────────
        if (xQueueReceive(cmd_queue, &cmd, 0) == pdTRUE) {
            switch (cmd.mode) {
            case MODE_BRIGHTNESS:
                // brightness=0 means "no change" (sent when field is unused)
                if (cmd.brightness > 0) {
                    FastLED.setBrightness(cmd.brightness);
                    Serial.printf("[display] BRIGHTNESS %u\n", cmd.brightness);
                }
                break;  // does NOT fall through; display content is unchanged
            default:
                break;
            }

            switch (cmd.mode) {
            case MODE_SCROLL:
                build_col_map(cmd.text, cmd.text_len);
                scroll_offset = 0.0f;
                scroll_speed  = (float)cmd.speed;
                color_r = cmd.r; color_g = cmd.g; color_b = cmd.b;
                current_mode  = MODE_SCROLL;
                Serial.printf("[display] SCROLL speed=%u len=%u\n", cmd.speed, cmd.text_len);
                break;

            case MODE_STATIC:
                build_col_map(cmd.text, cmd.text_len);
                scroll_offset = 0.0f;
                color_r = cmd.r; color_g = cmd.g; color_b = cmd.b;
                static_until_ms = millis() + cmd.duration_ms;
                current_mode = MODE_STATIC;
                Serial.printf("[display] STATIC duration=%ums\n", cmd.duration_ms);
                break;

            case MODE_FRAME: {
                // Blit raw RGB frame directly into leds[]
                uint16_t w = cmd.frame_w;
                uint16_t h = cmd.frame_h;
                for (uint16_t row = 0; row < h && row < DISPLAY_HEIGHT; row++) {
                    for (uint16_t col = 0; col < w && col < DISPLAY_WIDTH; col++) {
                        uint32_t px_idx  = (row * w + col) * 3;
                        uint16_t led_idx = row * DISPLAY_WIDTH + col;
                        leds[led_idx] = CRGB(cmd.frame[px_idx],
                                             cmd.frame[px_idx + 1],
                                             cmd.frame[px_idx + 2]);
                    }
                }
                FastLED.show();
                current_mode = MODE_CLEAR;  // don't animate after raw frame
                Serial.printf("[display] FRAME %ux%u\n", w, h);
                break;
            }

            case MODE_CLEAR:
                FastLED.clear(true);
                col_map_width = 0;
                scroll_offset = 0.0f;
                current_mode  = MODE_CLEAR;
                Serial.println("[display] CLEAR");
                break;
            }
        }

        // ── Animate current mode ─────────────────────────────────────────
        switch (current_mode) {
        case MODE_SCROLL:
            scroll_offset += scroll_speed * elapsed;
            // Wrap when text has fully scrolled off-screen
            if (col_map_width > 0 && (int32_t)scroll_offset >= (int32_t)col_map_width) {
                scroll_offset = -(float)DISPLAY_WIDTH;  // restart from right edge
            }
            render_to_leds((int32_t)scroll_offset, color_r, color_g, color_b);
            FastLED.show();
            break;

        case MODE_STATIC:
            if (millis() >= static_until_ms) {
                FastLED.clear(true);
                current_mode = MODE_CLEAR;
            } else {
                render_to_leds(0, color_r, color_g, color_b);
                FastLED.show();
            }
            break;

        case MODE_FRAME:
        case MODE_CLEAR:
        case MODE_BRIGHTNESS:
            // Nothing to animate
            break;
        }

        vTaskDelay(pdMS_TO_TICKS(FRAME_MS));
    }
}

void display_init() {
    xTaskCreatePinnedToCore(display_task, "display_task", 8192, nullptr, 1, nullptr, 1);
    Serial.println("[display] display_task queued on Core 1");
}
```

- [ ] **Step 7.3: Verify compile**

```bash
arduino-cli compile --fqbn esp32:esp32:esp32s3 esp32_ticker
```

- [ ] **Step 7.4: Commit**

```bash
git add esp32_ticker/display.h esp32_ticker/display.cpp
git commit -m "feat: add display_task with scroll, static, frame, and clear handlers"
```

---

### Task 8: Wire everything together and integration test

**Files:**
- Modify: `esp32_ticker/esp32_ticker.ino`

- [ ] **Step 8.1: Update `esp32_ticker/esp32_ticker.ino`**

```cpp
// esp32_ticker.ino
// Receives binary UART commands from a Raspberry Pi and drives a
// 320×8 WS2812B LED ticker display.
//
// Core 0: uart_task  — parses packets, sends ACK/NACK
// Core 1: display_task — renders text/frames at 30 FPS via FastLED
//
// See docs/superpowers/specs/2026-03-17-esp32-firmware-design.md

#include "config.h"
#include "protocol.h"
#include "display.h"

void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println("[esp32_ticker] booting");
    Serial.printf("  Display: %d x %d (%d LEDs) on GPIO %d\n",
                  DISPLAY_WIDTH, DISPLAY_HEIGHT, NUM_LEDS, DATA_PIN);
    Serial.printf("  UART: %d baud on RX=%d TX=%d\n",
                  UART_BAUD, UART_RX_PIN, UART_TX_PIN);

    display_init();   // starts display_task on Core 1 (also inits FastLED)
    protocol_init();  // starts uart_task on Core 0 (also opens Serial2)

    Serial.println("[esp32_ticker] ready");
}

void loop() {
    // All work is in FreeRTOS tasks. loop() never executes meaningful code.
    vTaskDelay(portMAX_DELAY);
}
```

- [ ] **Step 8.2: Final compile**

```bash
arduino-cli compile --fqbn esp32:esp32:esp32s3 esp32_ticker
```

Expected: no errors, binary size reported.

- [ ] **Step 8.3: Flash and boot test**

```bash
arduino-cli upload -p /dev/ttyUSB0 --fqbn esp32:esp32:esp32s3 esp32_ticker
arduino-cli monitor -p /dev/ttyUSB0 -c baudrate=115200
```

Expected Serial Monitor output:
```
[esp32_ticker] booting
  Display: 320 x 8 (2560 LEDs) on GPIO 38
  UART: 921600 baud on RX=18 TX=17
[display] display_task started on Core 1
[protocol] uart_task started on Core 0
[esp32_ticker] ready
```

- [ ] **Step 8.4: Send CMD_SCROLL from Pi**

On the Pi, with the ESP32 connected via USB-serial (set `--esp32-port` to the correct port):

```bash
uv run python services/ticker_service.py --esp32-port /dev/ttyUSB0 --verbose
```

Expected: ticker_service starts, sends idle message, ESP32 Serial Monitor shows:
```
[display] SCROLL speed=40 len=XX
```
And the physical display scrolls white text.

- [ ] **Step 8.5: Send CMD_FRAME from console_preview**

```bash
uv run python -m ships_ahoy.console_preview --text "TEST 123" --speed 30
```

This drives the Pi-side PreviewDriver (no serial), so verify the terminal preview renders correctly. Then separately test the ESP32 `CMD_FRAME` path by using a simple Pi-side script:

```python
# quick_frame_test.py — run on Pi
import serial, struct
from ships_ahoy.esp32_protocol import encode_packet, CMD_FRAME

port = serial.Serial('/dev/ttyUSB0', 921600, timeout=0.5)
# Send an all-red 8×8 frame in the top-left corner
w, h = 8, 8
pixels = bytes([255, 0, 0] * (w * h))
payload = struct.pack('>HH', w, h) + pixels
pkt = encode_packet(CMD_FRAME, payload)
port.write(pkt)
ack = port.read(1)
print('ACK' if ack == b'\x00' else f'NACK or timeout: {ack.hex()}')
port.close()
```

Expected: ACK received, top-left 8×8 LEDs glow red.

- [ ] **Step 8.6: Final commit**

```bash
git add esp32_ticker/esp32_ticker.ino
git commit -m "feat: wire up setup() and complete esp32_ticker firmware"
```

---

## Summary

| Task | File(s) | What it does |
|------|---------|--------------|
| 1 | `esp32_ticker.ino`, `config.h` | Scaffold, all constants |
| 2 | `font.h` | 5×8 PROGMEM font array |
| 3 | `sprites.h` | 4 emoji sprite bitmaps |
| 4 | `protocol.h/.cpp` | CRC8, Command struct |
| 5 | `protocol.cpp` | uart_task state machine |
| 6 | `renderer.h/.cpp` | build_col_map, render_to_leds |
| 7 | `display.h/.cpp` | display_task, FastLED |
| 8 | `esp32_ticker.ino` | setup() integration + hardware test |
