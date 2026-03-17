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
from enum import StrEnum
from typing import Optional

from ships_ahoy.ship_tracker import ShipInfo

# AIS navigation status codes → human-readable label
_STATUS_LABELS = {
    0: "underway",
    1: "at anchor",
    2: "not under command",
    3: "restricted manoeuvrability",
    4: "constrained by draught",
    5: "moored",
    6: "aground",
    7: "fishing",
    8: "underway sailing",
    15: "undefined",
}

# AIS ship type ranges → short label
def _ship_type_label(ship_type: Optional[int]) -> str:
    if ship_type is None:
        return "VESSEL"
    if 70 <= ship_type <= 79:
        return "CARGO"
    if 80 <= ship_type <= 89:
        return "TANKER"
    if 60 <= ship_type <= 69:
        return "PASSENGER"
    if 30 <= ship_type <= 39:
        return "FISHING"
    if 50 <= ship_type <= 59:
        return "SERVICE"
    return "VESSEL"


class EventType(StrEnum):
    """AIS event types stored in the events table."""

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
    events = []

    if (
        old_ship.status is not None
        and new_ship.status is not None
        and old_ship.status != new_ship.status
    ):
        old_label = _STATUS_LABELS.get(old_ship.status, str(old_ship.status))
        new_label = _STATUS_LABELS.get(new_ship.status, str(new_ship.status))
        detail = f"{new_ship.name} status: {old_label} → {new_label}"
        events.append((EventType.STATUS_CHANGE, detail))

    return events


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
        "⚓ CARGO 'ATLANTIC STAR' — ARRIVED — underway"
    """
    name = (
        enrichment_row["vessel_name"]
        if enrichment_row and enrichment_row["vessel_name"]
        else ship_row["name"]
    )
    type_label = _ship_type_label(ship_row["ship_type"])
    event_type = event_row["event_type"]
    status_label = _STATUS_LABELS.get(ship_row["status"], "")

    parts = [f"{type_label} '{name}' — {event_type}"]
    if status_label:
        parts.append(status_label)

    return " — ".join(parts)
