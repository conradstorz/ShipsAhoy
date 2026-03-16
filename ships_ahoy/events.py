"""Event detection and ticker message formatting for ShipsAhoy.

Events represent notable changes in ship state that the LED ticker should announce.

detect_events() is called by ais_service on every AIS message update.
It is NOT called for new ships — ais_service writes ARRIVED directly.

format_ticker_message() is called by ticker_service to produce the
single-line string scrolled across the LED display.

Usage::

    events = detect_events(old_ship_info, new_ship_info)
    for event_type, detail in events:
        write_event(conn, ship.mmsi, event_type, detail)

    text = format_ticker_message(event_row, ship_row, enrichment_row)
    driver.scroll_text(text, speed)
"""

import sqlite3
from typing import Optional

from ships_ahoy.ship_tracker import ShipInfo


class EventType:
    """String constants for AIS event types stored in the events table."""

    ARRIVED = "ARRIVED"
    DEPARTED = "DEPARTED"
    STATUS_CHANGE = "STATUS_CHANGE"
    ENRICHED = "ENRICHED"


def detect_events(
    old_ship: ShipInfo,
    new_ship: ShipInfo,
) -> list[tuple[str, str]]:
    """Compare two ShipInfo snapshots and return a list of (event_type, detail) tuples.

    Parameters
    ----------
    old_ship:
        The ShipInfo state before the current AIS message was applied.
        Must not be None — ARRIVED events are written directly by ais_service,
        not via this function.
    new_ship:
        The ShipInfo state after applying the current AIS message.

    Returns
    -------
    list of (str, str)
        Each tuple is (EventType constant, human-readable detail string).
        Returns an empty list if no noteworthy changes are detected.

    Detected changes:
    - Navigation status change (e.g. anchored → underway)
    """
    raise NotImplementedError


def format_ticker_message(
    event_row: sqlite3.Row,
    ship_row: sqlite3.Row,
    enrichment_row: Optional[sqlite3.Row],
) -> str:
    """Produce a single-line string for the LED ticker display.

    Parameters
    ----------
    event_row:
        Row from the events table (must have event_type, detail, mmsi columns).
    ship_row:
        Row from the ships table for the event's MMSI.
    enrichment_row:
        Row from the enrichment table, or None if no enrichment exists.

    Returns
    -------
    str
        A compact single-line string. Example:
        "⚓ CARGO 'ATLANTIC STAR' — underway — 2.3 km NE"
    """
    raise NotImplementedError
