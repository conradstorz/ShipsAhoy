"""LED Ticker Service for ShipsAhoy.

Drives the LED matrix display in a continuous cycle.
Runs as a persistent systemd service.

Responsibilities:
- Build a playlist of prose chunks from in-range ships (closest first)
- Scroll each chunk across the display
- Repeat, rebuilding the playlist on each cycle
- When no ships are in range, cycle through idle quips and location facts

MatrixDriver selection:
    Attempts to import RGBMatrixDriver (requires rpi-rgb-led-matrix on Pi).
    Falls back to StubMatrixDriver automatically on non-Pi platforms.

Usage::

    uv run python services/ticker_service.py [--db PATH] [--verbose] [--esp32-port PORT]
"""

import argparse
import sys
import time

from loguru import logger

from ships_ahoy.config import Config
from ships_ahoy.db import init_db
from ships_ahoy.ticker_content import build_playlist
from ships_ahoy.service_utils import DEFAULT_DB_PATH, configure_logging

try:
    from ships_ahoy.matrix_driver import RGBMatrixDriver as _DriverClass
except (ImportError, NotImplementedError):
    from ships_ahoy.matrix_driver import StubMatrixDriver as _DriverClass  # type: ignore[assignment]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ticker_service",
        description="ShipsAhoy LED Ticker Service",
    )
    parser.add_argument("--db", default=DEFAULT_DB_PATH, metavar="PATH")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--esp32-port", default=None, metavar="PORT",
        help="UART device for ESP32, e.g. /dev/ttyAMA0",
    )
    return parser


def main() -> None:
    """Service entry point. Continuously cycles through ship info and idle content."""
    args = _build_parser().parse_args()
    configure_logging(args.verbose)

    conn = init_db(args.db)
    cfg = Config(conn)

    if args.esp32_port:
        from ships_ahoy.matrix_driver import ESP32Driver
        driver = ESP32Driver(port=args.esp32_port)
        logger.info("Using ESP32Driver on {}", args.esp32_port)
    else:
        driver = _DriverClass()

    logger.info("Ticker service starting.")

    try:
        while True:
            try:
                playlist = build_playlist(conn, cfg)
                for text in playlist:
                    logger.info("Ticker: {}", text)
                    driver.scroll_text(text, speed_px_per_sec=cfg.scroll_speed)
                    time.sleep(cfg.gap_sec)
            except Exception:
                logger.exception("Ticker service loop error")
                time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Ticker service stopped by user.")
        driver.clear()
        sys.exit(0)


if __name__ == "__main__":
    main()
