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
