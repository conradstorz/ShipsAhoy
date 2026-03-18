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
