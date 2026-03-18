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
