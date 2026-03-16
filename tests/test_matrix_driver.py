"""Tests for ships_ahoy.matrix_driver.

StubMatrixDriver must conform fully to the MatrixDriver interface.
These tests can run on any platform (no Pi hardware required).
"""
import pytest
from ships_ahoy.matrix_driver import MatrixDriver, StubMatrixDriver


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
