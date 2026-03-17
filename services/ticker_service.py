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
    get_ships_in_range,
)
from ships_ahoy.events import format_ticker_message

try:
    from ships_ahoy.matrix_driver import RGBMatrixDriver as _DriverClass
except (ImportError, NotImplementedError):
    from ships_ahoy.matrix_driver import StubMatrixDriver as _DriverClass  # type: ignore[assignment]

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = "ships.db"
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
    return parser


def _handle_overflow(conn, events, driver) -> None:
    """Flush stale events and display a summary message.

    Called when more than OVERFLOW_THRESHOLD events are pending.
    Marks all pending events as displayed without scrolling them individually,
    then scrolls a single summary.
    """
    cutoff = (datetime.now() - timedelta(minutes=OVERFLOW_AGE_MINUTES)).isoformat()
    flushed = 0
    for event in events:
        if event["created_at"] < cutoff:
            mark_event_displayed(conn, event["id"])
            flushed += 1

    if flushed > 0:
        msg = f"ShipsAhoy — {flushed} new events (queue flushed)"
        driver.scroll_text(msg, speed_px_per_sec=40)
        logger.info("Overflow: flushed %d stale events", flushed)


def _display_event(conn, event_row, driver, cfg: Config) -> None:
    """Fetch ship and enrichment data, format ticker message, scroll it, mark displayed."""
    ship_row = get_ship(conn, event_row["mmsi"])
    if ship_row is None:
        mark_event_displayed(conn, event_row["id"])
        return
    enrichment_row = get_enrichment(conn, event_row["mmsi"])
    text = format_ticker_message(event_row, ship_row, enrichment_row)
    driver.scroll_text(text, speed_px_per_sec=cfg.scroll_speed)
    mark_event_displayed(conn, event_row["id"])


def _show_idle(conn, driver, cfg: Config) -> None:
    """Display the idle message showing current ship count."""
    home = cfg.home_location
    if home:
        ships = get_ships_in_range(conn, home[0], home[1], cfg.distance_km)
        count = len(ships)
    else:
        count = conn.execute("SELECT COUNT(*) FROM ships").fetchone()[0]
    msg = f"ShipsAhoy — {count} ships nearby"
    driver.show_static(msg, duration_sec=POLL_INTERVAL_SEC)


def main() -> None:
    """Service entry point. Polls for events and drives the LED display."""
    args = _build_parser().parse_args()
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    conn = init_db(args.db)
    cfg = Config(conn)
    driver = _DriverClass()

    logger.info("Ticker service starting.")

    while True:
        try:
            events = get_pending_events(conn)

            if not events:
                _show_idle(conn, driver, cfg)
                time.sleep(POLL_INTERVAL_SEC)
                continue

            # Overflow check: total pending count is the gate; age determines what gets flushed.
            # Spec: "if more than 10 events are pending, events older than 5 minutes are skipped"
            if len(events) > OVERFLOW_THRESHOLD:
                _handle_overflow(conn, events, driver)
                continue

            # Display one event per loop iteration
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
