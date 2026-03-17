"""LED matrix driver abstraction for ShipsAhoy.

Defines the MatrixDriver interface and two concrete implementations:

- RGBMatrixDriver: real HUB75 driver using rpi-rgb-led-matrix Python bindings.
  Configured for 5 chained 64x32 panels (320x32 pixels total).
- StubMatrixDriver: no-op implementation for development and testing on
  non-Pi hardware. Logs text to stdout instead of driving hardware.

ticker_service.py imports MatrixDriver only. At startup it attempts to
import rpi-rgb-led-matrix; if unavailable it falls back to StubMatrixDriver.

Usage::

    try:
        from ships_ahoy.matrix_driver import RGBMatrixDriver as DriverClass
    except ImportError:
        from ships_ahoy.matrix_driver import StubMatrixDriver as DriverClass

    driver = DriverClass()
    driver.scroll_text("⚓ CARGO 'FOO' — underway", speed_px_per_sec=40.0)
"""

import abc
import logging

logger = logging.getLogger(__name__)

# HUB75 panel configuration constants
PANEL_WIDTH = 64
PANEL_HEIGHT = 32
PANEL_COUNT = 5
DISPLAY_WIDTH = PANEL_WIDTH * PANEL_COUNT  # 320
DISPLAY_HEIGHT = PANEL_HEIGHT              # 32

# WS2812 ESP32 display dimensions
ESP32_DISPLAY_WIDTH  = 600
ESP32_DISPLAY_HEIGHT = 32


class MatrixDriver(abc.ABC):
    """Abstract base class for LED matrix display drivers."""

    @abc.abstractmethod
    def scroll_text(self, text: str, speed_px_per_sec: float) -> None:
        """Scroll *text* left across the full display width. Blocking."""

    @abc.abstractmethod
    def clear(self) -> None:
        """Clear all pixels on the display."""

    @abc.abstractmethod
    def show_static(self, text: str, duration_sec: float) -> None:
        """Display *text* statically for *duration_sec* seconds."""

    def send_frame(self, pixels: bytes, width: int, height: int) -> None:
        """Send a pre-rendered RGB pixel frame. No-op by default."""


class StubMatrixDriver(MatrixDriver):
    """No-op MatrixDriver for development and testing on non-Pi hardware."""

    def scroll_text(self, text: str, speed_px_per_sec: float) -> None:
        logger.info("[StubMatrixDriver] scroll_text: %s (%.1f px/s)", text, speed_px_per_sec)
        print(f"[TICKER] {text}")

    def clear(self) -> None:
        logger.debug("[StubMatrixDriver] clear()")

    def show_static(self, text: str, duration_sec: float) -> None:
        logger.info("[StubMatrixDriver] show_static: %s (%.1fs)", text, duration_sec)
        print(f"[TICKER IDLE] {text}")

    def send_frame(self, pixels: bytes, width: int, height: int) -> None:
        logger.debug("[StubMatrixDriver] send_frame: %dx%d (%d bytes)", width, height, len(pixels))


class RGBMatrixDriver(MatrixDriver):
    """Real HUB75 driver using rpi-rgb-led-matrix Python bindings.

    Panel configuration: 5 chained 64x32 panels = 320x32 pixels total.
    Requires rpi-rgb-led-matrix installed and appropriate GPIO permissions.
    """

    def __init__(self) -> None:
        raise NotImplementedError(
            "RGBMatrixDriver requires rpi-rgb-led-matrix. "
            "See https://github.com/hzeller/rpi-rgb-led-matrix for installation."
        )

    def scroll_text(self, text: str, speed_px_per_sec: float) -> None:
        raise NotImplementedError

    def clear(self) -> None:
        raise NotImplementedError

    def show_static(self, text: str, duration_sec: float) -> None:
        raise NotImplementedError


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

    def get_current_frame(self, elapsed_sec: float) -> list:
        """Advance scroll by *elapsed_sec* × speed and return the current frame.

        Returns a PixelGrid: list[list[RGB]], height rows × display_width cols.
        """
        self._scroll_offset += elapsed_sec * self._speed
        offset = int(self._scroll_offset)
        return self._scroll_frame(self._pixels, offset=offset, display_width=self._display_width)


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
