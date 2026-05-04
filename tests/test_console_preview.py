"""Tests for ships_ahoy.console_preview.

Covers render_frame_to_terminal() and _build_parser() without requiring
a real terminal — no I/O, no hardware.
"""
import pytest
from ships_ahoy.console_preview import render_frame_to_terminal, _build_parser

_BLACK = (0, 0, 0)
_WHITE = (255, 255, 255)
_RED   = (255, 0, 0)


def _solid_frame(color, width: int, height: int) -> list:
    return [[color] * width for _ in range(height)]


# ---------------------------------------------------------------------------
# render_frame_to_terminal
# ---------------------------------------------------------------------------

def test_returns_string():
    frame = _solid_frame(_BLACK, width=4, height=2)
    result = render_frame_to_terminal(frame, display_height=2)
    assert isinstance(result, str)


def test_line_count_equals_half_height():
    """Each pair of LED rows produces one terminal line."""
    frame = _solid_frame(_BLACK, width=4, height=8)
    result = render_frame_to_terminal(frame, display_height=8)
    assert result.count("\n") == 3  # 4 lines → 3 newlines


def test_half_block_character_present():
    frame = _solid_frame(_WHITE, width=4, height=2)
    result = render_frame_to_terminal(frame, display_height=2)
    assert "▀" in result


def test_ansi_reset_present():
    frame = _solid_frame(_BLACK, width=4, height=2)
    result = render_frame_to_terminal(frame, display_height=2)
    assert "\x1b[0m" in result


def test_ansi_fg_code_present_for_lit_pixel():
    """A lit top-row pixel should produce a non-black foreground ANSI code."""
    top_row = [_RED] + [_BLACK] * 3
    bot_row = [_BLACK] * 4
    frame = [top_row, bot_row]
    result = render_frame_to_terminal(frame, display_height=2)
    # fg for red: \x1b[38;2;255;0;0m
    assert "\x1b[38;2;255;0;0m" in result


def test_ansi_bg_code_present_for_lit_pixel():
    """A lit bottom-row pixel should produce a non-black background ANSI code."""
    top_row = [_BLACK] * 4
    bot_row = [_RED] + [_BLACK] * 3
    frame = [top_row, bot_row]
    result = render_frame_to_terminal(frame, display_height=2)
    # bg for red: \x1b[48;2;255;0;0m
    assert "\x1b[48;2;255;0;0m" in result


def test_half_blocks_per_line_equals_width():
    """Number of ▀ characters in a line equals the display width."""
    width = 10
    frame = _solid_frame(_WHITE, width=width, height=2)
    result = render_frame_to_terminal(frame, display_height=2)
    # Single terminal line — strip the reset suffix and count half-blocks
    assert result.count("▀") == width


def test_all_black_frame_fg_is_black():
    """All-black frame: every foreground ANSI code uses (0,0,0)."""
    frame = _solid_frame(_BLACK, width=4, height=2)
    result = render_frame_to_terminal(frame, display_height=2)
    assert "\x1b[38;2;0;0;0m" in result
    # No non-black fg codes
    assert "\x1b[38;2;255;" not in result


def test_four_row_display_produces_two_terminal_lines():
    frame = _solid_frame(_BLACK, width=2, height=4)
    result = render_frame_to_terminal(frame, display_height=4)
    lines = result.split("\n")
    assert len(lines) == 2


def test_eight_row_display_produces_four_terminal_lines():
    frame = _solid_frame(_BLACK, width=2, height=8)
    result = render_frame_to_terminal(frame, display_height=8)
    lines = result.split("\n")
    assert len(lines) == 4


# ---------------------------------------------------------------------------
# _build_parser
# ---------------------------------------------------------------------------

def test_parser_default_speed():
    args = _build_parser().parse_args([])
    assert args.speed == 40.0


def test_parser_default_width():
    args = _build_parser().parse_args([])
    assert args.width == 80


def test_parser_default_height():
    args = _build_parser().parse_args([])
    assert args.height == 16


def test_parser_text_override():
    args = _build_parser().parse_args(["--text", "HELLO"])
    assert args.text == "HELLO"


def test_parser_speed_override():
    args = _build_parser().parse_args(["--speed", "60"])
    assert args.speed == 60.0


def test_parser_width_override():
    args = _build_parser().parse_args(["--width", "320"])
    assert args.width == 320


def test_parser_height_override():
    args = _build_parser().parse_args(["--height", "8"])
    assert args.height == 8
