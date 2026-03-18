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

    // Current display state — start with a standby scroll so the display
    // shows it is powered on before the Pi sends any commands.
    static const uint8_t STANDBY_TEXT[] =
        "  \x1E\x02 ShipsAhoy \x1E\x01  ";  // ship emoji, name, anchor emoji
    build_col_map(STANDBY_TEXT, sizeof(STANDBY_TEXT) - 1);

    DisplayMode current_mode = MODE_SCROLL;
    float       scroll_offset  = -(float)DISPLAY_WIDTH;  // enter from right
    float       scroll_speed   = 30.0f;  // px/sec — gentle standby pace
    uint8_t     color_r = 0, color_g = 180, color_b = 180;  // dim cyan
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
