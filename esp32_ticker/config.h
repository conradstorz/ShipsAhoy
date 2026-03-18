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
