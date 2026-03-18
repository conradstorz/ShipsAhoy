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
