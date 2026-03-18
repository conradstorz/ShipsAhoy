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
