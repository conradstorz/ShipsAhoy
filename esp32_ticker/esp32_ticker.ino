// esp32_ticker.ino
// Receives binary USB commands from a Raspberry Pi and drives a
// 320×8 WS2812B LED ticker display.
//
// Core 0: uart_task, wifi_task — packet parsing and WiFi/OTA/debug
// Core 1: display_task         — renders text/frames at 30 FPS via FastLED
//
// See docs/superpowers/specs/2026-05-04-esp32-usb-wifi-design.md

#include "config.h"
#include "debug_log.h"
#include "wifi_manager.h"
#include "protocol.h"
#include "display.h"

void setup() {
    wifi_manager_init();   // soft-AP + OTA + debug web server; must be first
    dbg_info("[esp32_ticker] booting");
    dbg_info("  Display: %d x %d (%d LEDs) on GPIO %d",
             DISPLAY_WIDTH, DISPLAY_HEIGHT, NUM_LEDS, DATA_PIN);

    display_init();        // starts display_task on Core 1
    protocol_init();       // opens Serial at PI_BAUD; starts uart_task on Core 0

    dbg_info("[esp32_ticker] ready");
}

void loop() {
    // All work is in FreeRTOS tasks. loop() never executes meaningful code.
    vTaskDelay(portMAX_DELAY);
}
