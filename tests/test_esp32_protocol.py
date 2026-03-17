import logging

from ships_ahoy.esp32_protocol import (
    CMD_SCROLL, CMD_STATIC, CMD_FRAME, CMD_CLEAR, CMD_PING, CMD_BRIGHTNESS,
    MAX_PAYLOAD_BYTES, GLYPH_WIDTH_PX, SPRITES,
    crc8, encode_text, encode_packet,
)


def test_constants_defined():
    assert CMD_SCROLL == 0x01
    assert CMD_STATIC == 0x02
    assert CMD_FRAME  == 0x03
    assert CMD_CLEAR  == 0x04
    assert CMD_PING   == 0x05
    assert CMD_BRIGHTNESS == 0x06
    assert MAX_PAYLOAD_BYTES == 512
    assert GLYPH_WIDTH_PX == 6

def test_crc8_zero():
    assert crc8(b'\x00') == 0x00

def test_crc8_known_vector():
    # Non-reflected CRC8: poly=0x31, init=0x00, refin=False, refout=False.
    # NOT the same as CRC8/MAXIM-DOW (which uses refin=True, refout=True).
    # Pinned value verified against the implementation.
    assert crc8(b'\x01') == 0x31

def test_crc8_multi_byte():
    # Computed value for this specific non-reflected CRC8 variant (poly=0x31, init=0x00)
    assert crc8(b'\xAA\xAA') == 0x36
    # Also verify it differs from naive XOR (0x00 for equal bytes)
    assert crc8(b'\xAA\xAA') != 0x00


def test_encode_text_ascii_passthrough():
    assert encode_text("hello") == b"hello"

def test_encode_text_sprite_substitution():
    result = encode_text("⚓")
    assert result == bytes([0x1E, 0x01])

def test_encode_text_mixed():
    result = encode_text("⚓ship")
    assert result == bytes([0x1E, 0x01]) + b"ship"

def test_encode_text_unknown_emoji_stripped(caplog):
    with caplog.at_level(logging.DEBUG, logger="ships_ahoy.esp32_protocol"):
        result = encode_text("🍕hello")
    assert result == b"hello"
    assert any("stripped" in r.message for r in caplog.records)

def test_encode_packet_structure():
    pkt = encode_packet(CMD_CLEAR, b"")
    assert pkt[0] == 0xAA          # start byte
    assert pkt[1] == CMD_CLEAR     # command
    assert pkt[2] == 0x00          # LEN_HI
    assert pkt[3] == 0x00          # LEN_LO
    assert len(pkt) == 5           # header(4) + crc(1)

def test_encode_packet_crc_position():
    pkt = encode_packet(CMD_CLEAR, b"")
    crc_expected = crc8(bytes([CMD_CLEAR, 0x00, 0x00]))
    assert pkt[-1] == crc_expected

def test_encode_packet_with_payload():
    payload = b"\x01\x02\x03"
    pkt = encode_packet(CMD_BRIGHTNESS, payload)
    assert pkt[2:4] == bytes([0x00, 0x03])  # length = 3
    assert pkt[4:7] == payload

def test_encode_packet_truncates_oversized(caplog):
    oversized = b"X" * 600
    with caplog.at_level(logging.WARNING, logger="ships_ahoy.esp32_protocol"):
        pkt = encode_packet(CMD_SCROLL, oversized)
    payload_len = (pkt[2] << 8) | pkt[3]
    assert payload_len == MAX_PAYLOAD_BYTES
    assert any("truncating" in r.message for r in caplog.records)
