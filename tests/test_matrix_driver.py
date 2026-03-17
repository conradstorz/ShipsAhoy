"""Tests for ships_ahoy.matrix_driver.

StubMatrixDriver must conform fully to the MatrixDriver interface.
These tests can run on any platform (no Pi hardware required).
"""
import pytest
import time
from ships_ahoy.matrix_driver import (
    MatrixDriver, StubMatrixDriver, PreviewDriver,
    ESP32_DISPLAY_WIDTH, ESP32_DISPLAY_HEIGHT,
)


def test_stub_is_matrix_driver_subclass():
    assert issubclass(StubMatrixDriver, MatrixDriver)


def test_stub_can_be_instantiated():
    driver = StubMatrixDriver()
    assert driver is not None


def test_stub_scroll_text_does_not_raise():
    driver = StubMatrixDriver()
    driver.scroll_text("TEST MESSAGE", speed_px_per_sec=40.0)


def test_stub_clear_does_not_raise():
    driver = StubMatrixDriver()
    driver.clear()


def test_stub_show_static_does_not_raise():
    driver = StubMatrixDriver()
    driver.show_static("IDLE TEXT", duration_sec=2.0)


def test_matrix_driver_scroll_text_is_abstract():
    """MatrixDriver cannot be instantiated directly."""
    with pytest.raises(TypeError):
        MatrixDriver()  # type: ignore[abstract]


def test_stub_scroll_text_accepts_empty_string():
    driver = StubMatrixDriver()
    driver.scroll_text("", speed_px_per_sec=40.0)


def test_stub_show_static_accepts_zero_duration():
    driver = StubMatrixDriver()
    driver.show_static("X", duration_sec=0.0)


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
