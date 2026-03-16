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
