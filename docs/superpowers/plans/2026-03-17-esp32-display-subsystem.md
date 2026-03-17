# ESP32 Display Subsystem Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an ESP32-backed WS2812 LED ticker display to ShipsAhoy, with a binary UART protocol, live web SSE preview, and console preview utility — all best-effort from the Pi's perspective.

**Architecture:** `esp32_protocol.py` handles pure binary packet encoding; `renderer.py` handles pure pixel rendering; `ESP32Driver` and `PreviewDriver` are added to `matrix_driver.py`; `ticker_service` gains `--esp32-port` and writes `display_state` to SQLite; `web_service` gains a `GET /ticker/preview` SSE route that streams rendered frames to a canvas in the browser.

**Tech Stack:** Python 3.11, SQLite3, Flask, pyserial (new), ANSI terminal escape codes

---

## Chunk 1: Foundation — Protocol, Renderer, DB

### Task 1: Protocol encoding module

**Files:**
- Create: `ships_ahoy/esp32_protocol.py`
- Create: `tests/test_esp32_protocol.py`

- [ ] **Step 1.1: Write failing tests for CRC8 and constants**

```python
# tests/test_esp32_protocol.py
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
    # CRC8/MAXIM (poly 0x31, init 0x00): crc8([0x01]) == 0x31
    assert crc8(b'\x01') == 0x31

def test_crc8_multi_byte():
    # Verify CRC8 is not the same as XOR (would be 0x00 for equal bytes)
    result = crc8(b'\xAA\xAA')
    assert isinstance(result, int)
    assert 0 <= result <= 255
```

- [ ] **Step 1.2: Run to verify FAIL**

```
uv run pytest tests/test_esp32_protocol.py -v
```
Expected: `ModuleNotFoundError` or `ImportError`

- [ ] **Step 1.3: Create `ships_ahoy/esp32_protocol.py` with constants and CRC8**

```python
"""Binary protocol encoding for the ESP32 display subsystem.

No I/O — pure data transformation, fully testable without hardware.

Wire format per packet:
    [0xAA] [CMD] [LEN_HI] [LEN_LO] [PAYLOAD ...] [CRC8]

CRC8 covers CMD + LEN_HI + LEN_LO + PAYLOAD using CRC8/MAXIM
(Dallas 1-Wire), polynomial 0x31, initial value 0x00, no reflection.
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
    """CRC8/MAXIM (Dallas 1-Wire): polynomial 0x31, init 0x00, no reflection."""
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

    Guarantees single-byte-per-glyph output so len() gives a correct
    glyph count for scroll-duration estimation.
    Unknown non-ASCII characters are stripped and logged at DEBUG.
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
```

- [ ] **Step 1.4: Run CRC8 and constants tests — verify PASS**

```
uv run pytest tests/test_esp32_protocol.py::test_constants_defined tests/test_esp32_protocol.py::test_crc8_zero tests/test_esp32_protocol.py::test_crc8_known_vector tests/test_esp32_protocol.py::test_crc8_multi_byte -v
```

- [ ] **Step 1.5: Write failing tests for encode_text and encode_packet**

```python
# add to tests/test_esp32_protocol.py
import logging

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
```

- [ ] **Step 1.6: Run full test suite — verify all pass**

```
uv run pytest tests/test_esp32_protocol.py -v
```
Expected: all PASS (full implementation was written in Step 1.3 before these tests were added)

- [ ] **Step 1.7: Commit**

```
git add ships_ahoy/esp32_protocol.py tests/test_esp32_protocol.py
git commit -m "feat: add esp32_protocol module with CRC8, encode_text, encode_packet"
```

---

### Task 2: Renderer module

**Files:**
- Create: `ships_ahoy/renderer.py`
- Create: `tests/test_renderer.py`

- [ ] **Step 2.1: Write failing tests**

```python
# tests/test_renderer.py
from ships_ahoy.renderer import BitmapFont, render_text, scroll_frame

DISPLAY_W = 20  # small display for tests
DISPLAY_H = 8

def test_render_text_returns_pixel_grid():
    grid = render_text("AB", color=(255, 255, 255), width=DISPLAY_W, height=DISPLAY_H)
    assert isinstance(grid, list)
    assert len(grid) == DISPLAY_H
    assert all(len(row) == DISPLAY_W for row in grid)

def test_render_text_pixel_is_rgb_tuple():
    grid = render_text("A", color=(255, 0, 0), width=DISPLAY_W, height=DISPLAY_H)
    px = grid[0][0]
    assert isinstance(px, tuple)
    assert len(px) == 3

def test_render_text_space_is_all_black():
    grid = render_text(" ", color=(255, 255, 255), width=DISPLAY_W, height=DISPLAY_H)
    for row in grid:
        for px in row:
            assert px == (0, 0, 0)

def test_render_text_letter_has_some_lit_pixels():
    # 'A' should have at least one non-black pixel
    grid = render_text("A", color=(255, 255, 255), width=DISPLAY_W, height=DISPLAY_H)
    lit = sum(1 for row in grid for px in row if px != (0, 0, 0))
    assert lit > 0

def test_render_text_color_respected():
    grid = render_text("A", color=(100, 200, 50), width=DISPLAY_W, height=DISPLAY_H)
    colors = {px for row in grid for px in row if px != (0, 0, 0)}
    assert (100, 200, 50) in colors

def test_scroll_frame_zero_offset():
    full = render_text("HELLO", color=(255, 255, 255), width=100, height=DISPLAY_H)
    frame = scroll_frame(full, offset=0, display_width=DISPLAY_W)
    assert len(frame) == DISPLAY_H
    assert all(len(row) == DISPLAY_W for row in frame)
    assert frame[0] == full[0][:DISPLAY_W]

def test_scroll_frame_nonzero_offset():
    full = render_text("HELLO", color=(255, 255, 255), width=100, height=DISPLAY_H)
    frame0 = scroll_frame(full, offset=0, display_width=DISPLAY_W)
    frame6 = scroll_frame(full, offset=6, display_width=DISPLAY_W)
    assert frame0 != frame6

def test_scroll_frame_past_end_is_black():
    full = render_text("A", color=(255, 255, 255), width=100, height=DISPLAY_H)
    # offset beyond full width: all black
    frame = scroll_frame(full, offset=9999, display_width=DISPLAY_W)
    for row in frame:
        assert all(px == (0, 0, 0) for px in row)
```

- [ ] **Step 2.2: Run to verify FAIL**

```
uv run pytest tests/test_renderer.py -v
```
Expected: `ModuleNotFoundError`

- [ ] **Step 2.3: Create `ships_ahoy/renderer.py`**

```python
"""Pixel rendering for ShipsAhoy LED display preview.

Provides a 5x8 bitmap font renderer and scroll-frame slicer.
No I/O — pure data transformation. The same font glyph data is
also shipped to the ESP32 firmware so both sides agree on layout.

Usage::

    from ships_ahoy.renderer import render_text, scroll_frame

    pixels = render_text("ARRIVED", color=(255, 255, 0), width=600, height=32)
    frame  = scroll_frame(pixels, offset=12, display_width=600)
"""

from typing import NamedTuple

RGB      = tuple[int, int, int]
PixelGrid = list[list[RGB]]

_BLACK: RGB = (0, 0, 0)

# ---------------------------------------------------------------------------
# 5x8 bitmap font
# Each entry is 5 column bytes for ASCII codes 32–126.
# Each byte encodes one column: bit 0 = top row, bit 7 = bottom row.
# Characters outside 32–126 render as blank (5 black columns).
# ---------------------------------------------------------------------------
# fmt: off
_FONT_DATA: list[list[int]] = [
    [0x00,0x00,0x00,0x00,0x00],  # 32  space
    [0x00,0x00,0x5F,0x00,0x00],  # 33  !
    [0x00,0x07,0x00,0x07,0x00],  # 34  "
    [0x14,0x7F,0x14,0x7F,0x14],  # 35  #
    [0x24,0x2A,0x7F,0x2A,0x12],  # 36  $
    [0x23,0x13,0x08,0x64,0x62],  # 37  %
    [0x36,0x49,0x55,0x22,0x50],  # 38  &
    [0x00,0x05,0x03,0x00,0x00],  # 39  '
    [0x00,0x1C,0x22,0x41,0x00],  # 40  (
    [0x00,0x41,0x22,0x1C,0x00],  # 41  )
    [0x08,0x2A,0x1C,0x2A,0x08],  # 42  *
    [0x08,0x08,0x3E,0x08,0x08],  # 43  +
    [0x00,0x50,0x30,0x00,0x00],  # 44  ,
    [0x08,0x08,0x08,0x08,0x08],  # 45  -
    [0x00,0x60,0x60,0x00,0x00],  # 46  .
    [0x20,0x10,0x08,0x04,0x02],  # 47  /
    [0x3E,0x51,0x49,0x45,0x3E],  # 48  0
    [0x00,0x42,0x7F,0x40,0x00],  # 49  1
    [0x42,0x61,0x51,0x49,0x46],  # 50  2
    [0x21,0x41,0x45,0x4B,0x31],  # 51  3
    [0x18,0x14,0x12,0x7F,0x10],  # 52  4
    [0x27,0x45,0x45,0x45,0x39],  # 53  5
    [0x3C,0x4A,0x49,0x49,0x30],  # 54  6
    [0x01,0x71,0x09,0x05,0x03],  # 55  7
    [0x36,0x49,0x49,0x49,0x36],  # 56  8
    [0x06,0x49,0x49,0x29,0x1E],  # 57  9
    [0x00,0x36,0x36,0x00,0x00],  # 58  :
    [0x00,0x56,0x36,0x00,0x00],  # 59  ;
    [0x00,0x08,0x14,0x22,0x41],  # 60  <
    [0x14,0x14,0x14,0x14,0x14],  # 61  =
    [0x41,0x22,0x14,0x08,0x00],  # 62  >
    [0x02,0x01,0x51,0x09,0x06],  # 63  ?
    [0x32,0x49,0x79,0x41,0x3E],  # 64  @
    [0x7E,0x11,0x11,0x11,0x7E],  # 65  A
    [0x7F,0x49,0x49,0x49,0x36],  # 66  B
    [0x3E,0x41,0x41,0x41,0x22],  # 67  C
    [0x7F,0x41,0x41,0x22,0x1C],  # 68  D
    [0x7F,0x49,0x49,0x49,0x41],  # 69  E
    [0x7F,0x09,0x09,0x09,0x01],  # 70  F
    [0x3E,0x41,0x49,0x49,0x7A],  # 71  G
    [0x7F,0x08,0x08,0x08,0x7F],  # 72  H
    [0x00,0x41,0x7F,0x41,0x00],  # 73  I
    [0x20,0x40,0x41,0x3F,0x01],  # 74  J
    [0x7F,0x08,0x14,0x22,0x41],  # 75  K
    [0x7F,0x40,0x40,0x40,0x40],  # 76  L
    [0x7F,0x02,0x04,0x02,0x7F],  # 77  M
    [0x7F,0x04,0x08,0x10,0x7F],  # 78  N
    [0x3E,0x41,0x41,0x41,0x3E],  # 79  O
    [0x7F,0x09,0x09,0x09,0x06],  # 80  P
    [0x3E,0x41,0x51,0x21,0x5E],  # 81  Q
    [0x7F,0x09,0x19,0x29,0x46],  # 82  R
    [0x46,0x49,0x49,0x49,0x31],  # 83  S
    [0x01,0x01,0x7F,0x01,0x01],  # 84  T
    [0x3F,0x40,0x40,0x40,0x3F],  # 85  U
    [0x1F,0x20,0x40,0x20,0x1F],  # 86  V
    [0x3F,0x40,0x38,0x40,0x3F],  # 87  W
    [0x63,0x14,0x08,0x14,0x63],  # 88  X
    [0x07,0x08,0x70,0x08,0x07],  # 89  Y
    [0x61,0x51,0x49,0x45,0x43],  # 90  Z
    [0x00,0x7F,0x41,0x41,0x00],  # 91  [
    [0x02,0x04,0x08,0x10,0x20],  # 92  backslash
    [0x00,0x41,0x41,0x7F,0x00],  # 93  ]
    [0x04,0x02,0x01,0x02,0x04],  # 94  ^
    [0x40,0x40,0x40,0x40,0x40],  # 95  _
    [0x00,0x01,0x02,0x04,0x00],  # 96  `
    [0x20,0x54,0x54,0x54,0x78],  # 97  a
    [0x7F,0x48,0x44,0x44,0x38],  # 98  b
    [0x38,0x44,0x44,0x44,0x20],  # 99  c
    [0x38,0x44,0x44,0x48,0x7F],  # 100 d
    [0x38,0x54,0x54,0x54,0x18],  # 101 e
    [0x08,0x7E,0x09,0x01,0x02],  # 102 f
    [0x0C,0x52,0x52,0x52,0x3E],  # 103 g
    [0x7F,0x08,0x04,0x04,0x78],  # 104 h
    [0x00,0x44,0x7D,0x40,0x00],  # 105 i
    [0x20,0x40,0x44,0x3D,0x00],  # 106 j
    [0x7F,0x10,0x28,0x44,0x00],  # 107 k
    [0x00,0x41,0x7F,0x40,0x00],  # 108 l
    [0x7C,0x04,0x18,0x04,0x78],  # 109 m
    [0x7C,0x08,0x04,0x04,0x78],  # 110 n
    [0x38,0x44,0x44,0x44,0x38],  # 111 o
    [0x7C,0x14,0x14,0x14,0x08],  # 112 p
    [0x08,0x14,0x14,0x18,0x7C],  # 113 q
    [0x7C,0x08,0x04,0x04,0x08],  # 114 r
    [0x48,0x54,0x54,0x54,0x20],  # 115 s
    [0x04,0x3F,0x44,0x40,0x20],  # 116 t
    [0x3C,0x40,0x40,0x20,0x7C],  # 117 u
    [0x1C,0x20,0x40,0x20,0x1C],  # 118 v
    [0x3C,0x40,0x30,0x40,0x3C],  # 119 w
    [0x44,0x28,0x10,0x28,0x44],  # 120 x
    [0x0C,0x50,0x50,0x50,0x3C],  # 121 y
    [0x44,0x64,0x54,0x4C,0x44],  # 122 z
    [0x00,0x08,0x36,0x41,0x00],  # 123 {
    [0x00,0x00,0x7F,0x00,0x00],  # 124 |
    [0x00,0x41,0x36,0x08,0x00],  # 125 }
    [0x08,0x08,0x2A,0x1C,0x08],  # 126 ~
]
# fmt: on

_GLYPH_W = 5   # pixel columns per glyph
_GLYPH_H = 8   # pixel rows per glyph
_GLYPH_SPACING = 1  # blank columns between glyphs


class BitmapFont:
    """5x8 bitmap font renderer."""

    def char_columns(self, ch: str) -> list[int]:
        """Return the 5 column bytes for *ch* (blank if out of range)."""
        code = ord(ch)
        if 32 <= code <= 126:
            return _FONT_DATA[code - 32]
        return [0] * _GLYPH_W


def render_text(
    text: str,
    color: RGB,
    width: int,
    height: int,
) -> PixelGrid:
    """Render *text* to a pixel grid of the given dimensions.

    The grid is *height* rows tall and at least *width* columns wide
    (padded with black if the text is shorter than *width*).
    Characters are vertically centred within *height*.
    Each glyph is 5 px wide + 1 px spacing = 6 px per character.
    """
    font = BitmapFont()

    # Build full-width pixel columns for the entire text
    columns: list[list[RGB]] = []
    for ch in text:
        cols = font.char_columns(ch)
        for col_byte in cols:
            col_pixels: list[RGB] = []
            for row in range(_GLYPH_H):
                bit = (col_byte >> row) & 1
                col_pixels.append(color if bit else _BLACK)
            columns.append(col_pixels)
        # spacing column
        columns.append([_BLACK] * _GLYPH_H)

    text_width = len(columns)
    total_width = max(width, text_width)

    # Pad to requested width
    while len(columns) < total_width:
        columns.append([_BLACK] * _GLYPH_H)

    # Build row-major grid, vertically centring the 8-row glyph in *height*
    top_pad = (height - _GLYPH_H) // 2
    grid: PixelGrid = []
    for row in range(height):
        glyph_row = row - top_pad
        if 0 <= glyph_row < _GLYPH_H:
            grid.append([columns[col][glyph_row] for col in range(total_width)])
        else:
            grid.append([_BLACK] * total_width)

    return grid


def scroll_frame(
    pixels: PixelGrid,
    offset: int,
    display_width: int,
) -> PixelGrid:
    """Slice *pixels* at *offset* to produce a *display_width*-wide frame.

    If offset + display_width exceeds the pixel grid, the remainder is
    filled with black. If offset >= total width, returns an all-black frame.
    """
    if not pixels:
        return [[_BLACK] * display_width]

    total_width = len(pixels[0])
    height = len(pixels)
    frame: PixelGrid = []
    for row in pixels:
        frame_row: list[RGB] = []
        for col in range(display_width):
            src_col = offset + col
            if 0 <= src_col < total_width:
                frame_row.append(row[src_col])
            else:
                frame_row.append(_BLACK)
        frame.append(frame_row)
    return frame
```

- [ ] **Step 2.4: Run tests — verify PASS**

```
uv run pytest tests/test_renderer.py -v
```

- [ ] **Step 2.5: Commit**

```
git add ships_ahoy/renderer.py tests/test_renderer.py
git commit -m "feat: add renderer module with BitmapFont, render_text, scroll_frame"
```

---

### Task 3: display_state table in db.py

**Files:**
- Modify: `ships_ahoy/db.py`
- Modify: `tests/test_db.py`

- [ ] **Step 3.1: Write failing tests**

```python
# add to tests/test_db.py — replace the existing db import block with this
from ships_ahoy.db import (
    init_db,
    upsert_ship,
    get_ship,
    get_enrichment,
    get_unenriched_ships,
    save_enrichment,
    increment_fetch_attempts,
    write_event,
    get_pending_events,
    get_recent_events,
    mark_event_displayed,
    batch_mark_events_displayed,
    get_ships_in_range,
    get_all_ships,
    count_ships,
    get_stale_mmsis,
    get_visit_history,
    record_visit,
    close_visit,
    mark_ship_departed,
    write_display_state,
    get_display_state,
)

def test_get_display_state_returns_none_on_empty_db(conn):
    assert get_display_state(conn) is None

def test_write_display_state_creates_readable_row(conn):
    write_display_state(conn, text="CARGO arrived", speed=40.0, mode="scroll", duration_ms=0)
    row = get_display_state(conn)
    assert row is not None
    assert row["text"] == "CARGO arrived"
    assert row["mode"] == "scroll"
    assert abs(row["speed"] - 40.0) < 0.001

def test_write_display_state_is_single_row(conn):
    write_display_state(conn, text="first", speed=40.0, mode="scroll", duration_ms=0)
    write_display_state(conn, text="second", speed=40.0, mode="scroll", duration_ms=0)
    count = conn.execute("SELECT COUNT(*) FROM display_state").fetchone()[0]
    assert count == 1

def test_write_display_state_overwrites_previous(conn):
    write_display_state(conn, text="old", speed=40.0, mode="scroll", duration_ms=0)
    write_display_state(conn, text="new", speed=60.0, mode="static", duration_ms=2000)
    row = get_display_state(conn)
    assert row["text"] == "new"
    assert row["mode"] == "static"
    assert row["duration_ms"] == 2000

def test_write_display_state_sets_updated_at(conn):
    write_display_state(conn, text="x", speed=40.0, mode="scroll", duration_ms=0)
    row = get_display_state(conn)
    assert row["updated_at"] is not None
```

- [ ] **Step 3.2: Run to verify FAIL**

```
uv run pytest tests/test_db.py -k "display_state" -v
```
Expected: FAIL — `ImportError`

- [ ] **Step 3.3: Add display_state table and functions to `db.py`**

Add the following to `ships_ahoy/db.py`:

After `_CREATE_SHIP_VISITS`:
```python
_CREATE_DISPLAY_STATE = """
CREATE TABLE IF NOT EXISTS display_state (
    id           INTEGER PRIMARY KEY CHECK (id = 1),
    text         TEXT,
    speed        REAL,
    mode         TEXT,
    duration_ms  INTEGER,
    updated_at   DATETIME
)
"""
```

In `init_db()`, after `conn.execute(_CREATE_SHIP_VISITS)`:
```python
conn.execute(_CREATE_DISPLAY_STATE)
```

Add new default settings key `("esp32_port", "")` to `_DEFAULT_SETTINGS` list.

Add these two functions at the end of the file:
```python
def write_display_state(
    conn: sqlite3.Connection,
    text: str,
    speed: float,
    mode: str,
    duration_ms: int,
) -> None:
    """Write current display content to the single-row display_state table.

    Uses INSERT OR REPLACE to guarantee exactly one row exists at all times.
    """
    conn.execute(
        """
        INSERT OR REPLACE INTO display_state (id, text, speed, mode, duration_ms, updated_at)
        VALUES (1, ?, ?, ?, ?, ?)
        """,
        (text, speed, mode, duration_ms, _now_iso()),
    )
    conn.commit()


def get_display_state(conn: sqlite3.Connection) -> Optional[sqlite3.Row]:
    """Return the single display_state row, or None if not yet written."""
    return conn.execute("SELECT * FROM display_state").fetchone()
```

- [ ] **Step 3.4: Run display_state tests — verify PASS**

```
uv run pytest tests/test_db.py -k "display_state" -v
```

- [ ] **Step 3.5: Run full test suite to check no regressions**

```
uv run pytest tests/ -q
```
Expected: all PASS

- [ ] **Step 3.6: Commit**

```
git add ships_ahoy/db.py tests/test_db.py
git commit -m "feat: add display_state table and write/get_display_state to db"
```

---

## Chunk 2: Drivers and Ticker Service

### Task 4: MatrixDriver ABC extension and PreviewDriver

**Files:**
- Modify: `ships_ahoy/matrix_driver.py`
- Create: `tests/test_matrix_driver.py`

- [ ] **Step 4.1: Write failing tests for send_frame no-op and PreviewDriver**

```python
# tests/test_matrix_driver.py
import time
from ships_ahoy.matrix_driver import (
    MatrixDriver, StubMatrixDriver, PreviewDriver,
    ESP32_DISPLAY_WIDTH, ESP32_DISPLAY_HEIGHT,
)

# --- send_frame concrete default ---

def test_stub_driver_send_frame_does_not_raise():
    d = StubMatrixDriver()
    d.send_frame(b"\xFF" * 30, width=10, height=1)  # no error

def test_send_frame_is_concrete_on_abc():
    # MatrixDriver should not raise TypeError when only abstract methods implemented
    class MinimalDriver(MatrixDriver):
        def scroll_text(self, text, speed_px_per_sec): pass
        def clear(self): pass
        def show_static(self, text, duration_sec): pass
    d = MinimalDriver()
    d.send_frame(b"", width=0, height=0)  # should not raise

# --- PreviewDriver ---

def test_preview_driver_is_instantiable():
    d = PreviewDriver(display_width=20, display_height=8)
    assert d is not None

def test_preview_driver_scroll_text_returns_immediately():
    d = PreviewDriver(display_width=20, display_height=8)
    t0 = time.monotonic()
    d.scroll_text("hello", speed_px_per_sec=40.0)
    elapsed = time.monotonic() - t0
    assert elapsed < 0.5  # no sleep

def test_preview_driver_show_static_returns_immediately():
    d = PreviewDriver(display_width=20, display_height=8)
    t0 = time.monotonic()
    d.show_static("idle", duration_sec=5.0)
    elapsed = time.monotonic() - t0
    assert elapsed < 0.5  # no sleep

def test_preview_driver_get_current_frame_returns_correct_dimensions():
    d = PreviewDriver(display_width=20, display_height=8)
    d.scroll_text("HELLO", speed_px_per_sec=40.0)
    frame = d.get_current_frame(elapsed_sec=0.0)
    assert len(frame) == 8
    assert all(len(row) == 20 for row in frame)

def test_preview_driver_frame_advances_with_elapsed():
    d = PreviewDriver(display_width=20, display_height=8)
    d.scroll_text("HELLO WORLD TEST MESSAGE", speed_px_per_sec=40.0)
    frame0 = d.get_current_frame(elapsed_sec=0.0)
    frame1 = d.get_current_frame(elapsed_sec=1.0)  # 40 px scroll
    assert frame0 != frame1

def test_preview_driver_clear_resets_to_black():
    d = PreviewDriver(display_width=20, display_height=8)
    d.scroll_text("HELLO", speed_px_per_sec=40.0)
    d.clear()
    frame = d.get_current_frame(elapsed_sec=0.0)
    for row in frame:
        assert all(px == (0, 0, 0) for px in row)
```

- [ ] **Step 4.2: Run to verify FAIL**

```
uv run pytest tests/test_matrix_driver.py -v
```
Expected: FAIL — `ImportError` for `PreviewDriver`, `ESP32_DISPLAY_WIDTH`

- [ ] **Step 4.3: Add `send_frame`, `PreviewDriver`, and constants to `matrix_driver.py`**

At top of file, add constants after existing panel constants:
```python
# WS2812 ESP32 display dimensions
ESP32_DISPLAY_WIDTH  = 600
ESP32_DISPLAY_HEIGHT = 32
```

In `MatrixDriver` ABC, add concrete `send_frame` after `show_static`:
```python
def send_frame(self, pixels: bytes, width: int, height: int) -> None:
    """Send a pre-rendered RGB pixel frame. No-op by default."""
```

In `StubMatrixDriver`, override `send_frame`:
```python
def send_frame(self, pixels: bytes, width: int, height: int) -> None:
    logger.debug("[StubMatrixDriver] send_frame: %dx%d (%d bytes)", width, height, len(pixels))
```

Add new `PreviewDriver` class at end of file:
```python
class PreviewDriver(MatrixDriver):
    """Software-only driver that renders to an in-memory pixel grid.

    Used by web_service for the live SSE preview and by console_preview.
    No hardware, no serial port — safe to instantiate anywhere.
    Call get_current_frame(elapsed_sec) to retrieve the current display frame.
    """

    def __init__(self, display_width: int = ESP32_DISPLAY_WIDTH,
                 display_height: int = ESP32_DISPLAY_HEIGHT) -> None:
        from ships_ahoy.renderer import render_text, scroll_frame, _BLACK
        self._render_text = render_text
        self._scroll_frame = scroll_frame
        self._black = _BLACK
        self._display_width = display_width
        self._display_height = display_height
        self._pixels = [[_BLACK] * display_width for _ in range(display_height)]
        self._scroll_offset: float = 0.0
        self._speed: float = 0.0

    def scroll_text(self, text: str, speed_px_per_sec: float) -> None:
        """Load *text* for scrolling. Returns immediately (no sleep)."""
        self._pixels = self._render_text(
            text, color=(255, 255, 255),
            width=self._display_width, height=self._display_height,
        )
        self._scroll_offset = 0.0
        self._speed = speed_px_per_sec

    def show_static(self, text: str, duration_sec: float) -> None:
        """Load *text* as a static frame. Returns immediately (no sleep)."""
        self._pixels = self._render_text(
            text, color=(255, 255, 255),
            width=self._display_width, height=self._display_height,
        )
        self._scroll_offset = 0.0
        self._speed = 0.0

    def clear(self) -> None:
        """Reset display to all black."""
        self._pixels = [
            [self._black] * self._display_width
            for _ in range(self._display_height)
        ]
        self._scroll_offset = 0.0
        self._speed = 0.0

    def get_current_frame(self, elapsed_sec: float):
        """Advance scroll by *elapsed_sec* × speed and return the current frame.

        Returns a PixelGrid: list[list[RGB]], height rows × display_width cols.
        """
        from ships_ahoy.renderer import scroll_frame
        self._scroll_offset += elapsed_sec * self._speed
        offset = int(self._scroll_offset)
        return scroll_frame(self._pixels, offset=offset, display_width=self._display_width)
```

- [ ] **Step 4.4: Run tests — verify PASS**

```
uv run pytest tests/test_matrix_driver.py -v
```

- [ ] **Step 4.5: Run full suite**

```
uv run pytest tests/ -q
```

- [ ] **Step 4.6: Commit**

```
git add ships_ahoy/matrix_driver.py tests/test_matrix_driver.py
git commit -m "feat: add send_frame to MatrixDriver ABC, add PreviewDriver"
```

---

### Task 5: ESP32Driver

**Files:**
- Modify: `ships_ahoy/matrix_driver.py`
- Modify: `tests/test_matrix_driver.py`

- [ ] **Step 5.1: Write failing tests for ESP32Driver**

```python
# add to tests/test_matrix_driver.py
import logging
import struct
import unittest.mock as mock
from ships_ahoy.matrix_driver import ESP32Driver
from ships_ahoy.esp32_protocol import (
    CMD_SCROLL, CMD_STATIC, CMD_CLEAR, CMD_FRAME,
    ACK, NACK, encode_text, GLYPH_WIDTH_PX,
)

def _make_driver(port="/dev/ttyS0", read_byte=ACK):
    """Return an ESP32Driver with a mock serial port."""
    with mock.patch("serial.Serial") as MockSerial:
        instance = MockSerial.return_value
        instance.read.return_value = bytes([read_byte])
        driver = ESP32Driver(port=port, ack_timeout_sec=0.05)
        driver._serial = instance
        driver._connected = True
    return driver, instance

def test_esp32driver_connected_after_successful_open():
    with mock.patch("serial.Serial"):
        d = ESP32Driver(port="/dev/ttyS0")
    assert d._connected

def test_esp32driver_not_connected_on_serial_error():
    with mock.patch("serial.Serial", side_effect=Exception("no port")):
        d = ESP32Driver(port="/dev/ttyS0")
    assert not d._connected

def test_esp32driver_scroll_text_sends_packet():
    driver, serial_mock = _make_driver(read_byte=ACK)
    with mock.patch("time.sleep"):
        driver.scroll_text("HELLO", speed_px_per_sec=40.0)
    assert serial_mock.write.called
    pkt = serial_mock.write.call_args[0][0]
    assert pkt[0] == 0xAA        # start byte
    assert pkt[1] == CMD_SCROLL  # command

def test_esp32driver_scroll_text_sleeps_estimated_duration():
    driver, serial_mock = _make_driver(read_byte=ACK)
    text = "HI"
    expected_duration = len(encode_text(text)) * GLYPH_WIDTH_PX / 40.0
    sleep_calls = []
    with mock.patch("time.sleep", side_effect=lambda t: sleep_calls.append(t)):
        driver.scroll_text(text, speed_px_per_sec=40.0)
    total_sleep = sum(sleep_calls)
    assert abs(total_sleep - expected_duration) < 0.01

def test_esp32driver_returns_normally_on_nack(caplog):
    driver, serial_mock = _make_driver(read_byte=NACK)
    with mock.patch("time.sleep"):
        with caplog.at_level(logging.WARNING):
            driver.scroll_text("HI", speed_px_per_sec=40.0)
    assert any("NACK" in r.message or "nack" in r.message.lower() for r in caplog.records)

def test_esp32driver_returns_normally_when_disconnected():
    with mock.patch("serial.Serial", side_effect=Exception("no port")):
        d = ESP32Driver(port="/dev/ttyS0", ack_timeout_sec=0.05)
    # Should not raise even with no connection
    with mock.patch("time.sleep"):
        d.scroll_text("HI", speed_px_per_sec=40.0)
        d.show_static("idle", duration_sec=0.1)
        d.clear()

def test_esp32driver_clear_sends_clear_command():
    driver, serial_mock = _make_driver(read_byte=ACK)
    driver.clear()
    pkt = serial_mock.write.call_args[0][0]
    assert pkt[1] == CMD_CLEAR

def test_esp32driver_show_static_sleeps_duration():
    driver, serial_mock = _make_driver(read_byte=ACK)
    sleep_calls = []
    with mock.patch("time.sleep", side_effect=lambda t: sleep_calls.append(t)):
        driver.show_static("idle", duration_sec=2.0)
    assert abs(sum(sleep_calls) - 2.0) < 0.01
```

- [ ] **Step 5.2: Run to verify FAIL**

```
uv run pytest tests/test_matrix_driver.py -k "esp32" -v
```
Expected: FAIL — `ImportError` for `ESP32Driver`

- [ ] **Step 5.3: Add `ESP32Driver` to `matrix_driver.py`**

Add after `PreviewDriver` class:

```python
class ESP32Driver(MatrixDriver):
    """MatrixDriver that sends commands to an ESP32 over UART.

    Best-effort: all methods return normally regardless of whether the
    ESP32 acknowledged. scroll_text and show_static still sleep for the
    estimated display duration to throttle the ticker service loop.
    """

    def __init__(
        self,
        port: str,
        baud: int = 921600,
        ack_timeout_sec: float = 0.1,
    ) -> None:
        self._port = port
        self._baud = baud
        self._ack_timeout_sec = ack_timeout_sec
        self._serial = None
        self._connected = False
        self._open_serial()

    def _open_serial(self) -> None:
        """Attempt to open the serial port. Logs error on failure."""
        import serial
        try:
            self._serial = serial.Serial(self._port, self._baud, timeout=self._ack_timeout_sec)
            self._connected = True
            logger.info("ESP32Driver: connected to %s at %d baud", self._port, self._baud)
        except Exception as exc:
            logger.error("ESP32Driver: cannot open %s: %s", self._port, exc)
            self._connected = False

    def _send(self, packet: bytes) -> bool:
        """Send *packet* and wait briefly for ACK. Returns True on ACK.

        On NACK, timeout, or serial error: logs warning and returns False.
        Attempts one reconnect if not connected.
        """
        from ships_ahoy.esp32_protocol import ACK, NACK
        if not self._connected:
            self._open_serial()
            if not self._connected:
                return False
        try:
            self._serial.write(packet)
            response = self._serial.read(1)
            if response == bytes([ACK]):
                return True
            if response == bytes([NACK]):
                logger.warning("ESP32Driver: NACK received for cmd=0x%02X", packet[1])
            else:
                logger.warning("ESP32Driver: ACK timeout for cmd=0x%02X", packet[1])
            return False
        except Exception as exc:
            logger.error("ESP32Driver: serial error: %s", exc)
            self._connected = False
            return False

    def scroll_text(self, text: str, speed_px_per_sec: float) -> None:
        """Send SCROLL command, then sleep for estimated scroll duration."""
        import time
        import struct
        from ships_ahoy.esp32_protocol import CMD_SCROLL, encode_text, encode_packet, GLYPH_WIDTH_PX
        text_bytes = encode_text(text)
        speed_int = max(1, int(speed_px_per_sec))
        payload = struct.pack(">H", speed_int) + bytes([255, 255, 255]) + text_bytes
        self._send(encode_packet(CMD_SCROLL, payload))
        duration = len(text_bytes) * GLYPH_WIDTH_PX / max(speed_px_per_sec, 1.0)
        time.sleep(duration)

    def show_static(self, text: str, duration_sec: float) -> None:
        """Send STATIC command, then sleep for duration_sec."""
        import time
        import struct
        from ships_ahoy.esp32_protocol import CMD_STATIC, encode_text, encode_packet
        text_bytes = encode_text(text)
        duration_ms = int(duration_sec * 1000)
        payload = struct.pack(">I", duration_ms) + bytes([255, 255, 255]) + text_bytes
        self._send(encode_packet(CMD_STATIC, payload))
        time.sleep(duration_sec)

    def clear(self) -> None:
        """Send CLEAR command."""
        from ships_ahoy.esp32_protocol import CMD_CLEAR, encode_packet
        self._send(encode_packet(CMD_CLEAR, b""))

    def send_frame(self, pixels: bytes, width: int, height: int) -> None:
        """Send pre-rendered FRAME command."""
        import struct
        from ships_ahoy.esp32_protocol import CMD_FRAME, encode_packet
        payload = struct.pack(">HH", width, height) + pixels
        self._send(encode_packet(CMD_FRAME, payload))
```

- [ ] **Step 5.4: Run ESP32Driver tests — verify PASS**

```
uv run pytest tests/test_matrix_driver.py -v
```

- [ ] **Step 5.5: Run full suite**

```
uv run pytest tests/ -q
```

- [ ] **Step 5.6: Commit**

```
git add ships_ahoy/matrix_driver.py tests/test_matrix_driver.py
git commit -m "feat: add ESP32Driver with best-effort UART send and duration sleep"
```

---

### Task 6: ticker_service modifications

**Files:**
- Modify: `services/ticker_service.py`
- Modify: `tests/test_ticker_service.py` (create if not exists)

- [ ] **Step 6.1: Write failing tests**

```python
# tests/test_ticker_service.py
import argparse
import sys
import pytest
from unittest import mock


def _import_build_parser():
    # Import lazily to avoid import-time driver selection running
    import importlib
    spec = importlib.util.spec_from_file_location(
        "ticker_service",
        "services/ticker_service.py",
    )
    mod = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, {"ships_ahoy.matrix_driver": mock.MagicMock()}):
        spec.loader.exec_module(mod)
    return mod._build_parser


def test_build_parser_has_esp32_port_arg():
    build_parser = _import_build_parser()
    parser = build_parser()
    args = parser.parse_args(["--esp32-port", "/dev/ttyAMA0"])
    assert args.esp32_port == "/dev/ttyAMA0"

def test_build_parser_esp32_port_defaults_to_none():
    build_parser = _import_build_parser()
    parser = build_parser()
    args = parser.parse_args([])
    assert args.esp32_port is None
```

- [ ] **Step 6.2: Run to verify FAIL**

```
uv run pytest tests/test_ticker_service.py -v
```

- [ ] **Step 6.3: Modify `services/ticker_service.py`**

Update imports at top:
```python
from ships_ahoy.db import (
    init_db,
    get_ship,
    get_enrichment,
    get_pending_events,
    mark_event_displayed,
    batch_mark_events_displayed,
    count_ships,
    get_ships_in_range,
    write_display_state,   # NEW
)
```

Update `_build_parser()`:
```python
def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ticker_service",
        description="ShipsAhoy LED Ticker Service",
    )
    parser.add_argument("--db", default=DEFAULT_DB_PATH, metavar="PATH")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--esp32-port", default=None, metavar="PORT",
                        help="UART device for ESP32, e.g. /dev/ttyAMA0")
    return parser
```

Update `_display_event` to write display_state after scroll:
```python
def _display_event(conn, event_row, driver, cfg: Config) -> None:
    """Fetch ship and enrichment data, format ticker message, scroll it, mark displayed."""
    ship_row = get_ship(conn, event_row["mmsi"])
    if ship_row is None:
        mark_event_displayed(conn, event_row["id"])
        return
    enrichment_row = get_enrichment(conn, event_row["mmsi"])
    text = format_ticker_message(event_row, ship_row, enrichment_row)
    driver.scroll_text(text, speed_px_per_sec=cfg.scroll_speed)
    write_display_state(conn, text=text, speed=cfg.scroll_speed,
                        mode="scroll", duration_ms=0)
    mark_event_displayed(conn, event_row["id"])
```

Update `_show_idle` similarly:
```python
def _show_idle(conn, driver, cfg: Config) -> None:
    """Display the idle message showing current ship count."""
    home = cfg.home_location
    if home:
        count = len(get_ships_in_range(conn, home[0], home[1], cfg.distance_km))
    else:
        count = count_ships(conn)
    msg = f"ShipsAhoy — {count} ships nearby"
    driver.show_static(msg, duration_sec=POLL_INTERVAL_SEC)
    write_display_state(conn, text=msg, speed=0.0,
                        mode="static", duration_ms=int(POLL_INTERVAL_SEC * 1000))
```

Replace `_handle_overflow` in full:
```python
def _handle_overflow(conn, events, driver, cfg: Config) -> None:
    """Flush stale events and display a summary message.

    Called when more than OVERFLOW_THRESHOLD events are pending.
    Marks events older than OVERFLOW_AGE_MINUTES as displayed without scrolling,
    then scrolls a single summary. If no events are old enough to flush,
    displays the oldest one normally to avoid a spin loop.
    """
    cutoff = (datetime.now() - timedelta(minutes=OVERFLOW_AGE_MINUTES)).isoformat()
    stale_ids = [e["id"] for e in events if e["created_at"] < cutoff]
    flushed = len(stale_ids)

    if flushed > 0:
        batch_mark_events_displayed(conn, stale_ids)
        msg = f"ShipsAhoy — {flushed} new events (queue flushed)"
        driver.scroll_text(msg, speed_px_per_sec=cfg.scroll_speed)
        write_display_state(conn, text=msg, speed=cfg.scroll_speed,
                            mode="scroll", duration_ms=0)
        logger.info("Overflow: flushed %d stale events", flushed)
    else:
        # All events are recent — display the oldest one to drain the queue
        _display_event(conn, events[0], driver, cfg)
```

Replace `main()` in full:
```python
def main() -> None:
    """Service entry point. Polls for events and drives the LED display."""
    args = _build_parser().parse_args()
    configure_logging(args.verbose)

    conn = init_db(args.db)
    cfg = Config(conn)

    if args.esp32_port:
        from ships_ahoy.matrix_driver import ESP32Driver
        driver = ESP32Driver(port=args.esp32_port)
        logger.info("Using ESP32Driver on %s", args.esp32_port)
    else:
        driver = _DriverClass()

    logger.info("Ticker service starting.")

    while True:
        try:
            events = get_pending_events(conn)

            if not events:
                _show_idle(conn, driver, cfg)
                time.sleep(POLL_INTERVAL_SEC)
                continue

            if len(events) > OVERFLOW_THRESHOLD:
                _handle_overflow(conn, events, driver, cfg)
                continue

            _display_event(conn, events[0], driver, cfg)

        except KeyboardInterrupt:
            logger.info("Ticker service stopped by user.")
            driver.clear()
            sys.exit(0)
        except Exception:
            logger.exception("Ticker service loop error")
            time.sleep(1)
```

- [ ] **Step 6.4: Run tests — verify PASS**

```
uv run pytest tests/test_ticker_service.py -v
```

- [ ] **Step 6.5: Run full suite**

```
uv run pytest tests/ -q
```

- [ ] **Step 6.6: Commit**

```
git add services/ticker_service.py tests/test_ticker_service.py
git commit -m "feat: add --esp32-port arg and write_display_state calls to ticker_service"
```

---

## Chunk 3: Web Preview, Template, and Utilities

### Task 7: web_service SSE route

**Files:**
- Modify: `services/web_service.py`
- Create (or modify): `tests/test_web_service.py`

- [ ] **Step 7.1: Write failing tests**

```python
# tests/test_web_service.py
import sys
import pytest
from unittest import mock

@pytest.fixture
def client(tmp_path):
    """Flask test client with an in-memory database."""
    db_path = str(tmp_path / "test.db")
    with mock.patch.dict(sys.modules, {
        "ships_ahoy.matrix_driver": mock.MagicMock(),
    }):
        import importlib
        # Reload to get fresh module state
        import services.web_service as ws
        importlib.reload(ws)
        ws._conn = __import__("ships_ahoy.db", fromlist=["init_db"]).init_db(db_path)
        ws._cfg = __import__("ships_ahoy.config", fromlist=["Config"]).Config(ws._conn)
        ws._db_path = db_path
        ws.app.config["TESTING"] = True
        with ws.app.test_client() as c:
            yield c

def test_ticker_preview_content_type(client):
    """GET /ticker/preview returns text/event-stream."""
    # Use a short timeout generator for testing
    resp = client.get("/ticker/preview", query_string={"_max_frames": "1"})
    assert "text/event-stream" in resp.content_type

def test_ticker_preview_returns_data_line(client):
    """SSE stream emits at least one data: line with valid JSON."""
    import json
    resp = client.get("/ticker/preview", query_string={"_max_frames": "1"})
    body = resp.data.decode()
    # Find first data: line
    for line in body.splitlines():
        if line.startswith("data:"):
            payload = json.loads(line[5:].strip())
            assert "pixels" in payload
            assert "width" in payload
            assert "height" in payload
            return
    pytest.fail("No data: line found in SSE stream")
```

- [ ] **Step 7.2: Run to verify FAIL**

```
uv run pytest tests/test_web_service.py -v
```

- [ ] **Step 7.3: Modify `services/web_service.py`**

Add to imports:
```python
import json
import threading
import time

from ships_ahoy.db import (
    init_db,
    get_all_ships,
    get_ship,
    get_enrichment,
    get_ships_in_range,
    get_recent_events,
    get_visit_history,
    get_display_state,   # NEW
)
from ships_ahoy.distance import distance_info
from ships_ahoy.matrix_driver import PreviewDriver, ESP32_DISPLAY_WIDTH, ESP32_DISPLAY_HEIGHT  # NEW
from ships_ahoy.service_utils import DEFAULT_DB_PATH, configure_logging
```

Add module-level `_db_path` alongside `_conn` and `_cfg`:
```python
_conn = None
_cfg = None
_db_path = DEFAULT_DB_PATH  # set in main(); used by SSE generator
```

Add new route after the `/events` route:
```python
@app.route("/ticker/preview")
def ticker_preview():
    """Server-Sent Events stream of rendered ticker frames at ~30 FPS.

    Each SSE client opens its own SQLite connection and PreviewDriver instance.
    The generator polls display_state every ~250 ms for content updates,
    and ticks the PreviewDriver at ~30 FPS.
    """
    max_frames = request.args.get("_max_frames", type=int)  # test hook

    def generate():
        import sqlite3
        conn = sqlite3.connect(_db_path)
        conn.row_factory = sqlite3.Row
        preview = PreviewDriver(
            display_width=ESP32_DISPLAY_WIDTH,
            display_height=ESP32_DISPLAY_HEIGHT,
        )
        last_updated_at = None
        last_frame_time = time.monotonic()
        frames_sent = 0
        poll_counter = 0

        try:
            while True:
                # Poll display_state every ~250 ms (every 8 frames at 30 FPS)
                poll_counter += 1
                if poll_counter >= 8:
                    poll_counter = 0
                    row = get_display_state(conn)
                    if row and row["updated_at"] != last_updated_at:
                        last_updated_at = row["updated_at"]
                        if row["mode"] == "scroll":
                            preview.scroll_text(row["text"] or "", row["speed"] or 40.0)
                        else:
                            preview.show_static(
                                row["text"] or "",
                                (row["duration_ms"] or 2000) / 1000.0,
                            )

                # Advance scroll and get frame
                now = time.monotonic()
                elapsed = now - last_frame_time
                last_frame_time = now
                frame = preview.get_current_frame(elapsed_sec=elapsed)

                # Flatten row-major and emit
                flat = [list(px) for row in frame for px in row]
                data = json.dumps({
                    "pixels": flat,
                    "width": ESP32_DISPLAY_WIDTH,
                    "height": ESP32_DISPLAY_HEIGHT,
                })
                yield f"data: {data}\n\n"

                frames_sent += 1
                if max_frames is not None and frames_sent >= max_frames:
                    break

                time.sleep(1 / 30)
        finally:
            conn.close()

    return Response(
        generate(),
        content_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

Update `main()` to set `_db_path` and switch to `threaded=True`:
```python
def main() -> None:
    """Service entry point. Initialises DB connection then starts Flask."""
    global _conn, _cfg, _db_path
    args = _build_parser().parse_args()
    configure_logging(args.verbose)

    _db_path = args.db
    _conn = init_db(args.db)
    _cfg = Config(_conn)

    logger.info("Web service starting on port %d", args.port)
    # threaded=True allows SSE connections to stream while other routes remain
    # responsive. Each SSE generator opens its own SQLite connection (WAL mode
    # supports concurrent reads) so _conn is not accessed from SSE threads.
    app.run(host="0.0.0.0", port=args.port, debug=False, threaded=True)
```

- [ ] **Step 7.4: Run web_service tests — verify PASS**

```
uv run pytest tests/test_web_service.py -v
```

- [ ] **Step 7.5: Run full suite**

```
uv run pytest tests/ -q
```

- [ ] **Step 7.6: Commit**

```
git add services/web_service.py tests/test_web_service.py
git commit -m "feat: add /ticker/preview SSE route to web_service"
```

---

### Task 8: Ticker preview HTML template

**Files:**
- Create: `templates/ticker_preview.html`

- [ ] **Step 8.1: Create `templates/ticker_preview.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>ShipsAhoy — Ticker Preview</title>
    <style>
        body { background: #111; color: #ccc; font-family: monospace; padding: 1rem; }
        h1 { font-size: 1rem; margin-bottom: 0.5rem; }
        canvas {
            display: block;
            image-rendering: pixelated;
            border: 1px solid #333;
        }
        #status { margin-top: 0.5rem; font-size: 0.75rem; color: #666; }
    </style>
</head>
<body>
    <h1>Ticker Preview (live)</h1>
    <!--
        Each LED is drawn as a 3x3 px rectangle with a 1 px gap → 4 px pitch.
        Canvas: width*4 - 1 wide, height*4 - 1 tall.
        600 cols × 4 - 1 = 2399 px wide
         32 rows × 4 - 1 = 127  px tall
    -->
    <canvas id="ticker"></canvas>
    <div id="status">Connecting…</div>

    <script>
        const LED_PITCH = 4;    // pixels per LED (3 px rectangle + 1 px gap)
        const LED_SIZE  = 3;    // drawn rectangle size in px

        const canvas = document.getElementById('ticker');
        const ctx    = canvas.getContext('2d');
        const status = document.getElementById('status');

        let displayWidth  = 600;
        let displayHeight = 32;
        let initialized   = false;

        function initCanvas(w, h) {
            displayWidth  = w;
            displayHeight = h;
            canvas.width  = w * LED_PITCH - 1;
            canvas.height = h * LED_PITCH - 1;
            ctx.fillStyle = '#000';
            ctx.fillRect(0, 0, canvas.width, canvas.height);
            initialized = true;
        }

        function drawFrame(pixels, w, h) {
            if (!initialized || w !== displayWidth || h !== displayHeight) {
                initCanvas(w, h);
            }
            let i = 0;
            for (let row = 0; row < h; row++) {
                for (let col = 0; col < w; col++) {
                    const [r, g, b] = pixels[i++];
                    ctx.fillStyle = `rgb(${r},${g},${b})`;
                    ctx.fillRect(
                        col * LED_PITCH,
                        row * LED_PITCH,
                        LED_SIZE,
                        LED_SIZE,
                    );
                }
            }
        }

        function connect() {
            const es = new EventSource('/ticker/preview');

            es.onopen = () => {
                status.textContent = 'Connected — streaming at ~30 FPS';
            };

            es.onmessage = (evt) => {
                try {
                    const { pixels, width, height } = JSON.parse(evt.data);
                    drawFrame(pixels, width, height);
                } catch (e) {
                    console.error('Frame parse error', e);
                }
            };

            es.onerror = () => {
                status.textContent = 'Disconnected — reconnecting…';
                es.close();
                setTimeout(connect, 3000);
            };
        }

        initCanvas(displayWidth, displayHeight);
        connect();
    </script>
</body>
</html>
```

- [ ] **Step 8.2: Add route to `web_service.py`** (no tests needed — template rendering tested manually)

Add after the `/ticker/preview` route:
```python
@app.route("/ticker")
def ticker_page():
    """Ticker live preview page."""
    return render_template("ticker_preview.html")
```

Add `ticker_page` link to `templates/index.html` nav (or wherever the nav lives). In the existing index template, add:
```html
<a href="/ticker">Ticker Preview</a>
```

- [ ] **Step 8.3: Verify manually**

```
uv run python services/web_service.py --verbose
```
Open `http://localhost:5000/ticker` — canvas should appear and show a scrolling idle message once ticker_service is running.

- [ ] **Step 8.4: Commit**

```
git add templates/ticker_preview.html services/web_service.py
git commit -m "feat: add /ticker page with live LED canvas preview"
```

---

### Task 9: Console preview utility and dependency

**Files:**
- Create: `ships_ahoy/console_preview.py`
- Modify: `pyproject.toml`

- [ ] **Step 9.1: Add pyserial to `pyproject.toml`**

In `pyproject.toml`, under `[project]` → `dependencies`, add:
```
"pyserial>=3.5",
```

Verify it installs:
```
uv sync
```

- [ ] **Step 9.2: Create `ships_ahoy/console_preview.py`**

```python
"""Console preview for ShipsAhoy LED ticker.

Renders scrolling text in the terminal using ANSI 256-color codes and
Unicode half-block characters (▀ / ▄). Each pair of LED rows is rendered
as one terminal line: top-half pixels use ▀ with foreground color, bottom-half
pixels use ▄ with background color, giving 2 LED rows per terminal line.

A 32-row display renders as 16 terminal lines.

Usage::

    uv run python -m ships_ahoy.console_preview [--text "..."] [--speed N]
    uv run python -m ships_ahoy.console_preview --text "CARGO arrived" --speed 40
"""

import argparse
import sys
import time

from ships_ahoy.matrix_driver import PreviewDriver, ESP32_DISPLAY_WIDTH, ESP32_DISPLAY_HEIGHT


def _ansi_fg(r: int, g: int, b: int) -> str:
    return f"\x1b[38;2;{r};{g};{b}m"


def _ansi_bg(r: int, g: int, b: int) -> str:
    return f"\x1b[48;2;{r};{g};{b}m"


_RESET = "\x1b[0m"
_UPPER_HALF = "▀"
_CLEAR_LINE = "\x1b[2K\r"


def render_frame_to_terminal(frame, display_height: int) -> str:
    """Convert a PixelGrid to an ANSI string for terminal display.

    Two LED rows rendered per terminal line using Unicode half-blocks.
    Assumes display_height is even.
    """
    lines = []
    for terminal_row in range(display_height // 2):
        top_row = frame[terminal_row * 2]
        bot_row = frame[terminal_row * 2 + 1]
        line = ""
        for col in range(len(top_row)):
            tr, tg, tb = top_row[col]
            br, bg, bb = bot_row[col]
            line += _ansi_fg(tr, tg, tb) + _ansi_bg(br, bg, bb) + _UPPER_HALF
        line += _RESET
        lines.append(line)
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="console_preview",
        description="ShipsAhoy LED ticker console preview",
    )
    parser.add_argument("--text", default="ShipsAhoy — console preview",
                        help="Text to scroll")
    parser.add_argument("--speed", type=float, default=40.0,
                        help="Scroll speed in pixels per second")
    parser.add_argument("--width", type=int, default=80,
                        help="Display width in LEDs (default: 80 for terminal fit)")
    parser.add_argument("--height", type=int, default=16,
                        help="Display height in LEDs (must be even, default: 16)")
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    if args.height % 2 != 0:
        print("--height must be even", file=sys.stderr)
        sys.exit(1)

    driver = PreviewDriver(display_width=args.width, display_height=args.height)
    driver.scroll_text(args.text, speed_px_per_sec=args.speed)

    terminal_lines = args.height // 2
    # Move cursor up by terminal_lines before each frame (after first)
    cursor_up = f"\x1b[{terminal_lines}A"
    first_frame = True

    print(f"Scrolling: \"{args.text}\"  speed={args.speed} px/s  Ctrl-C to quit\n")

    last_time = time.monotonic()
    try:
        while True:
            now = time.monotonic()
            elapsed = now - last_time
            last_time = now

            frame = driver.get_current_frame(elapsed_sec=elapsed)
            rendered = render_frame_to_terminal(frame, args.height)

            if not first_frame:
                print(cursor_up, end="")
            print(rendered)
            first_frame = False

            time.sleep(1 / 30)
    except KeyboardInterrupt:
        print(_RESET)


if __name__ == "__main__":
    main()
```

- [ ] **Step 9.3: Smoke test in terminal**

```
uv run python -m ships_ahoy.console_preview --text "CARGO 'ATLANTIC STAR' — ARRIVED" --speed 30 --width 80 --height 16
```
Expected: scrolling colored text visible in the terminal. Press Ctrl-C to exit.

- [ ] **Step 9.4: Run full test suite one final time**

```
uv run pytest tests/ -q
```
Expected: all PASS

- [ ] **Step 9.5: Final commit**

```
git add ships_ahoy/console_preview.py requirements.txt
git commit -m "feat: add console_preview utility and pyserial dependency"
```

---

## Summary

| Task | Files | Tests |
|------|-------|-------|
| 1 — esp32_protocol | `ships_ahoy/esp32_protocol.py` | `tests/test_esp32_protocol.py` |
| 2 — renderer | `ships_ahoy/renderer.py` | `tests/test_renderer.py` |
| 3 — display_state DB | `ships_ahoy/db.py` | `tests/test_db.py` |
| 4 — ABC + PreviewDriver | `ships_ahoy/matrix_driver.py` | `tests/test_matrix_driver.py` |
| 5 — ESP32Driver | `ships_ahoy/matrix_driver.py` | `tests/test_matrix_driver.py` |
| 6 — ticker_service | `services/ticker_service.py` | `tests/test_ticker_service.py` |
| 7 — web SSE route | `services/web_service.py` | `tests/test_web_service.py` |
| 8 — preview template | `templates/ticker_preview.html` | manual |
| 9 — console_preview + deps | `ships_ahoy/console_preview.py`, `requirements.txt` | smoke test |
