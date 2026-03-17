"""AIS Receiver Service for ShipsAhoy.

Hardened replacement for main.py. Runs as a persistent systemd service.

Responsibilities:
- Connect to rtl_ais over TCP or UDP via AISReceiver
- Reconnect on failure with exponential backoff (1s → 2s → 4s → capped at 60s)
- On each decoded AIS message:
    - Fetch current ship state from DB (before update)
    - Upsert ship to DB with new data
    - Detect events by comparing old and new state
    - For new ships: write ARRIVED event, record_visit()
    - For existing ships: write any detected events (STATUS_CHANGE, etc.)
    - Only write events for ships within distance_km of home
- Stale-ship sweep every 5 minutes:
    - Query ships where last_seen < now - stale_ship_hours
    - For each: call mark_ship_departed()

Usage::

    uv run python services/ais_service.py [--host HOST] [--port PORT] [--udp] [--db PATH]
"""

import argparse
import logging
import socket
import sys
import time
from datetime import datetime, timedelta


from ships_ahoy.ais_receiver import AISReceiver, DEFAULT_HOST, DEFAULT_TCP_PORT
from ships_ahoy.config import Config
from ships_ahoy.db import init_db, get_ship, upsert_ship, write_event, record_visit, mark_ship_departed, get_stale_mmsis
from ships_ahoy.distance import is_noteworthy
from ships_ahoy.events import EventType, detect_events
from ships_ahoy.service_utils import DEFAULT_DB_PATH, configure_logging
from ships_ahoy.ship_tracker import ShipInfo, ShipTracker

logger = logging.getLogger(__name__)

SWEEP_INTERVAL_SEC = 300  # 5 minutes
MAX_BACKOFF_SEC = 60

_tracker = ShipTracker()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ais_service",
        description="ShipsAhoy AIS Receiver Service",
    )
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_TCP_PORT)
    parser.add_argument("--udp", action="store_true")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, metavar="PATH",
                        help="Path to SQLite database file")
    parser.add_argument("--verbose", action="store_true")
    return parser


def _connect_with_backoff(host: str, port: int, use_udp: bool) -> AISReceiver:
    """Attempt to create an AISReceiver, retrying with exponential backoff.

    Never gives up — logs each attempt and keeps retrying.
    """
    delay = 1
    while True:
        try:
            if not use_udp:
                # Verify TCP reachability before returning the receiver
                s = socket.create_connection((host, port), timeout=5)
                s.close()
            logger.info("Connected to AIS source %s:%d (udp=%s)", host, port, use_udp)
            return AISReceiver(host=host, port=port, use_udp=use_udp)
        except Exception as exc:
            logger.warning(
                "Cannot reach AIS source %s:%d: %s. Retrying in %ds", host, port, exc, delay
            )
            time.sleep(delay)
            delay = min(delay * 2, MAX_BACKOFF_SEC)


def _run_stale_sweep(conn, cfg: Config) -> None:
    """Query for ships past stale_ship_hours that still have an open visit, and mark each departed."""
    threshold = (datetime.now() - timedelta(hours=cfg.stale_ship_hours)).isoformat()
    for mmsi in get_stale_mmsis(conn, threshold):
        try:
            mark_ship_departed(conn, mmsi)
            logger.info("Stale sweep: marked MMSI %d as departed", mmsi)
        except Exception:
            logger.exception("Stale sweep: error marking MMSI %d as departed", mmsi)


def _process_message(conn, msg, cfg: Config) -> None:
    """Handle one decoded AIS message: upsert ship, detect events, write events.

    - Fetches ship state before upsert for comparison.
    - Writes ARRIVED for new ships (not via detect_events).
    - Calls detect_events for existing ships.
    - Only writes events for ships within distance_km of home.
    """
    new_ship = _tracker.update(msg)
    if new_ship is None:
        return

    old_row = get_ship(conn, new_ship.mmsi)
    upsert_ship(conn, new_ship)

    # Determine whether this ship is close enough to generate events
    home = cfg.home_location
    if home is not None and new_ship.latitude is not None and new_ship.longitude is not None:
        close_enough = is_noteworthy(
            new_ship.latitude, new_ship.longitude, home[0], home[1], cfg.distance_km
        )
    elif home is None:
        logger.warning("home_location not set — treating all ships as noteworthy")
        close_enough = True
    else:
        close_enough = False  # ship has no position yet

    if not close_enough:
        return

    if old_row is None:
        # First time we've seen this ship
        write_event(conn, new_ship.mmsi, EventType.ARRIVED, f"{new_ship.name} arrived")
        record_visit(conn, new_ship.mmsi)
    else:
        # Compare against previous state
        old_ship = ShipInfo(
            mmsi=old_row["mmsi"],
            name=old_row["name"] or "Unknown",
            status=old_row["status"],
        )
        for event_type, detail in detect_events(old_ship, new_ship):
            write_event(conn, new_ship.mmsi, event_type, detail)


def main() -> None:
    """Service entry point. Loops forever; reconnects on failure."""
    args = _build_parser().parse_args()
    configure_logging(args.verbose)

    conn = init_db(args.db)
    cfg = Config(conn)

    logger.info("AIS service starting. DB: %s", args.db)

    last_sweep = time.monotonic()

    while True:
        try:
            receiver = _connect_with_backoff(args.host, args.port, args.udp)
            for msg in receiver.messages():
                try:
                    _process_message(conn, msg, cfg)
                except Exception:
                    logger.exception("Error processing AIS message")

                now = time.monotonic()
                if now - last_sweep >= SWEEP_INTERVAL_SEC:
                    try:
                        _run_stale_sweep(conn, cfg)
                    except Exception:
                        logger.exception("Error in stale sweep")
                    last_sweep = now

        except KeyboardInterrupt:
            logger.info("AIS service stopped by user.")
            sys.exit(0)
        except Exception:
            logger.exception("AIS service outer loop error; restarting")
            time.sleep(1)


if __name__ == "__main__":
    main()
