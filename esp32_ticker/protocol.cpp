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
