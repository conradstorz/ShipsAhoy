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

// ── Parser state machine ──────────────────────────────────────────────────────

enum ParseState {
    WAIT_START,
    WAIT_CMD,
    WAIT_LEN_HI,
    WAIT_LEN_LO,
    WAIT_PAYLOAD,
    WAIT_CRC,
};

static bool read_byte_timeout(uint8_t* out, uint32_t timeout_ms) {
    uint32_t start = millis();
    while (!Serial2.available()) {
        if (millis() - start >= timeout_ms) return false;
        vTaskDelay(1);
    }
    *out = (uint8_t)Serial2.read();
    return true;
}

void uart_task(void* pvParameters) {
    static uint8_t payload_buf[MAX_PAYLOAD];
    ParseState state = WAIT_START;
    uint8_t    cmd = 0;
    uint16_t   payload_len = 0;
    uint16_t   bytes_read = 0;
    uint8_t    b;

    for (;;) {
        switch (state) {

        case WAIT_START:
            if (!read_byte_timeout(&b, portMAX_DELAY)) break;
            if (b == PKT_START) state = WAIT_CMD;
            break;

        case WAIT_CMD:
            if (!read_byte_timeout(&b, PKT_TIMEOUT_MS)) { state = WAIT_START; break; }
            cmd = b;
            state = WAIT_LEN_HI;
            break;

        case WAIT_LEN_HI:
            if (!read_byte_timeout(&b, PKT_TIMEOUT_MS)) { state = WAIT_START; break; }
            payload_len = (uint16_t)b << 8;
            state = WAIT_LEN_LO;
            break;

        case WAIT_LEN_LO:
            if (!read_byte_timeout(&b, PKT_TIMEOUT_MS)) { state = WAIT_START; break; }
            payload_len |= b;
            if (payload_len > MAX_PAYLOAD) {
                Serial.printf("[uart] oversized payload %u — dropping\n", payload_len);
                state = WAIT_START;
                break;
            }
            bytes_read = 0;
            state = (payload_len > 0) ? WAIT_PAYLOAD : WAIT_CRC;
            break;

        case WAIT_PAYLOAD:
            if (!read_byte_timeout(&b, PKT_TIMEOUT_MS)) { state = WAIT_START; break; }
            payload_buf[bytes_read++] = b;
            if (bytes_read >= payload_len) state = WAIT_CRC;
            break;

        case WAIT_CRC: {
            if (!read_byte_timeout(&b, PKT_TIMEOUT_MS)) { state = WAIT_START; break; }
            uint8_t rx_crc = b;

            // Compute CRC over [cmd, len_hi, len_lo, payload...]
            uint8_t crc_buf[3 + MAX_PAYLOAD];
            crc_buf[0] = cmd;
            crc_buf[1] = (uint8_t)(payload_len >> 8);
            crc_buf[2] = (uint8_t)(payload_len & 0xFF);
            memcpy(crc_buf + 3, payload_buf, payload_len);
            uint8_t expected = crc8(crc_buf, 3 + payload_len);

            if (rx_crc != expected) {
                Serial.printf("[uart] CRC fail cmd=0x%02X got=0x%02X exp=0x%02X\n",
                              cmd, rx_crc, expected);
                Serial2.write(NACK_BYTE);
                state = WAIT_START;
                break;
            }

            // ── Decode payload into Command ───────────────────────────────
            Command c;
            memset(&c, 0, sizeof(c));

            bool valid = true;
            switch (cmd) {
            case CMD_SCROLL:
                if (payload_len < 5) { valid = false; break; }
                c.mode  = MODE_SCROLL;
                c.speed = ((uint16_t)payload_buf[0] << 8) | payload_buf[1];
                if (c.speed < 1) c.speed = 1;
                c.r = payload_buf[2]; c.g = payload_buf[3]; c.b = payload_buf[4];
                c.text_len = payload_len - 5;
                memcpy(c.text, payload_buf + 5, c.text_len);
                break;

            case CMD_STATIC:
                if (payload_len < 7) { valid = false; break; }
                c.mode = MODE_STATIC;
                c.duration_ms = ((uint32_t)payload_buf[0] << 24) |
                                ((uint32_t)payload_buf[1] << 16) |
                                ((uint32_t)payload_buf[2] <<  8) |
                                 (uint32_t)payload_buf[3];
                c.r = payload_buf[4]; c.g = payload_buf[5]; c.b = payload_buf[6];
                c.text_len = payload_len - 7;
                memcpy(c.text, payload_buf + 7, c.text_len);
                break;

            case CMD_FRAME: {
                if (payload_len < 4) { valid = false; break; }
                c.frame_w = ((uint16_t)payload_buf[0] << 8) | payload_buf[1];
                c.frame_h = ((uint16_t)payload_buf[2] << 8) | payload_buf[3];
                // Reject frames that exceed display dimensions (cropping would corrupt stride)
                if (c.frame_w > DISPLAY_WIDTH || c.frame_h > DISPLAY_HEIGHT) {
                    Serial.printf("[uart] FRAME too large %ux%u — NACK\n", c.frame_w, c.frame_h);
                    valid = false; break;
                }
                uint32_t expected_px = (uint32_t)c.frame_w * c.frame_h * 3;
                uint16_t actual_px   = payload_len - 4;
                if (expected_px != actual_px) { valid = false; break; }
                c.mode = MODE_FRAME;
                memcpy(c.frame, payload_buf + 4, min((uint32_t)MAX_PAYLOAD, expected_px));
                break;
            }

            case CMD_CLEAR:
                c.mode = MODE_CLEAR;
                break;

            case CMD_PING:
                // ACK-only. No queue push needed.
                Serial2.write(ACK_BYTE);
                state = WAIT_START;
                valid = false;  // skip the queue-send path below
                break;

            case CMD_BRIGHTNESS:
                if (payload_len < 1) { valid = false; break; }
                c.mode = MODE_BRIGHTNESS;  // dedicated mode — does NOT clear display
                c.brightness = payload_buf[0];
                // brightness=0 means "no change" — display_task checks > 0
                break;

            default:
                Serial.printf("[uart] unknown cmd=0x%02X — ignoring\n", cmd);
                valid = false;
                break;
            }

            if (!valid) {
                // CMD_PING already sent ACK; everything else gets NACK
                if (cmd != CMD_PING) {
                    Serial2.write(NACK_BYTE);
                }
                state = WAIT_START;
                break;
            }

            Serial2.write(ACK_BYTE);
            xQueueSend(cmd_queue, &c, 0);  // non-blocking; drop if queue full
            state = WAIT_START;
            break;
        }

        } // switch
    }
}

void protocol_init() {
    cmd_queue = xQueueCreate(CMD_QUEUE_DEPTH, sizeof(Command));
    Serial2.begin(UART_BAUD, SERIAL_8N1, UART_RX_PIN, UART_TX_PIN);
    xTaskCreatePinnedToCore(uart_task, "uart_task", 8192, nullptr, 1, nullptr, 0);
    Serial.println("[protocol] uart_task started on Core 0");
}
