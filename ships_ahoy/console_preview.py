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
