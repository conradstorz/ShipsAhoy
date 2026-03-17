"""Binary protocol encoding for the ESP32 display subsystem.

No I/O — pure data transformation, fully testable without hardware.

Wire format per packet:
    [0xAA] [CMD] [LEN_HI] [LEN_LO] [PAYLOAD ...] [CRC8]

CRC8 covers CMD + LEN_HI + LEN_LO + PAYLOAD using
CRC8 polynomial 0x31, initial value 0x00, no input/output reflection
(a non-standard variant; the ESP32 firmware must implement the same variant).
"""

import logging

logger = logging.getLogger(__name__)

# Command identifiers (Pi → ESP32)
CMD_SCROLL     = 0x01
CMD_STATIC     = 0x02
CMD_FRAME      = 0x03
CMD_CLEAR      = 0x04
CMD_PING       = 0x05
CMD_BRIGHTNESS = 0x06

# Response bytes (ESP32 → Pi)
ACK  = 0x00
NACK = 0xFF

# Protocol constants
MAX_PAYLOAD_BYTES = 512   # max total payload length per packet
GLYPH_WIDTH_PX    = 6     # 5 px glyph + 1 px inter-character spacing

# Sprite table: emoji/name → 1-byte ID embedded in text via \x1E escape
SPRITES: dict[str, int] = {
    "⚓": 0x01,
    "🚢": 0x02,
    "🏴": 0x03,
    "🌊": 0x04,
}


def crc8(data: bytes) -> int:
    """CRC8: polynomial 0x31, init 0x00, no bit reflection.

    This is a non-reflected CRC8 variant — not the same as CRC8/MAXIM-DOW
    (which uses refin=True, refout=True). The ESP32 firmware must implement
    this exact variant for packet integrity checks to succeed.
    """
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ 0x31) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
    return crc


def encode_text(text: str) -> bytes:
    """Substitute known SPRITES with \\x1E + ID escapes; strip all other non-ASCII.

    Each ASCII character encodes as one byte; each known sprite encodes as
    two bytes (escape byte 0x1E followed by sprite ID). Callers computing
    scroll duration should use the plan-specified formula; they must not
    assume len() gives a direct glyph count when sprites are present.
    Unknown non-ASCII characters are stripped and logged at DEBUG level.
    """
    result = bytearray()
    for ch in text:
        if ch in SPRITES:
            result.append(0x1E)
            result.append(SPRITES[ch])
        elif ord(ch) < 128:
            result.extend(ch.encode("ascii"))
        else:
            logger.debug("encode_text: non-ASCII character %r stripped", ch)
    return bytes(result)


def encode_packet(cmd: int, payload: bytes) -> bytes:
    """Build a framed packet: [0xAA][CMD][LEN_HI][LEN_LO][PAYLOAD][CRC8].

    Truncates payload to MAX_PAYLOAD_BYTES with a WARNING if oversized.
    CRC8 is computed over CMD + LEN_HI + LEN_LO + PAYLOAD.
    """
    if len(payload) > MAX_PAYLOAD_BYTES:
        logger.warning(
            "encode_packet cmd=0x%02X: payload %d bytes exceeds %d; truncating",
            cmd, len(payload), MAX_PAYLOAD_BYTES,
        )
        payload = payload[:MAX_PAYLOAD_BYTES]
    length = len(payload)
    len_hi = (length >> 8) & 0xFF
    len_lo = length & 0xFF
    crc_input = bytes([cmd, len_hi, len_lo]) + payload
    checksum = crc8(crc_input)
    return bytes([0xAA, cmd, len_hi, len_lo]) + payload + bytes([checksum])
