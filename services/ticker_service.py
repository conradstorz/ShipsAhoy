"""LED Ticker Service for ShipsAhoy.

Drives the HUB75 LED matrix (5x 64x32 panels = 320x32 pixels).
Runs as a persistent systemd service.

Responsibilities:
- Poll the events table every 2 seconds for pending (undisplayed) events
- For each event: format a ticker message and scroll it across the display
- Mark each event as displayed after scrolling completes
- Queue overflow: if more than 10 events are pending with created_at older
  than 5 minutes, flush them (mark displayed without scrolling) and scroll a
  summary: "ShipsAhoy — N new events (queue flushed)"
- When queue is empty: show idle message "ShipsAhoy — N ships nearby"

MatrixDriver selection:
    Attempts to import RGBMatrixDriver (requires rpi-rgb-led-matrix on Pi).
    Falls back to StubMatrixDriver automatically on non-Pi platforms.

Usage::

    uv run python services/ticker_service.py [--db PATH] [--verbose]
"""

import argparse
import logging
import sys
import time
from datetime import datetime, timedelta

from ships_ahoy.config import Config
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
from ships_ahoy.events import format_ticker_message
from ships_ahoy.service_utils import DEFAULT_DB_PATH, configure_logging

try:
    from ships_ahoy.matrix_driver import RGBMatrixDriver as _DriverClass
except (ImportError, NotImplementedError):
    from ships_ahoy.matrix_driver import StubMatrixDriver as _DriverClass  # type: ignore[assignment]

logger = logging.getLogger(__name__)

POLL_INTERVAL_SEC = 2
OVERFLOW_THRESHOLD = 10   # "more than 10" means > 10 (fires at 11+)
OVERFLOW_AGE_MINUTES = 5


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


if __name__ == "__main__":
    main()
