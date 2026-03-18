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
