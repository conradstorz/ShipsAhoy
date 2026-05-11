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
from datetime import datetime, timezone
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

# AIS ship type ranges → human-readable label
def _ship_type_label(ship_type: Optional[int]) -> str:
    if ship_type is None:
        return "vessel"
    if 70 <= ship_type <= 79:
        return "cargo vessel"
    if 80 <= ship_type <= 89:
        return "tanker"
    if 60 <= ship_type <= 69:
        return "passenger vessel"
    if 30 <= ship_type <= 39:
        return "fishing vessel"
    if 50 <= ship_type <= 59:
        return "service vessel"
    return "vessel"


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
        detail = f"{new_ship.name or new_ship.mmsi} status: {old_label} -> {new_label}"
        events.append((EventType.STATUS_CHANGE, detail))

    return events


def format_ticker_message(
    event_row: sqlite3.Row,
    ship_row: sqlite3.Row,
    enrichment_row: Optional[sqlite3.Row],
    last_departed_iso: Optional[str] = None,
) -> Optional[str]:
    """Produce a single-line string for the LED ticker display, or None to skip.

    Returns None for ENRICHED events (internal housekeeping, not worth displaying).

    Parameters
    ----------
    event_row:
        Row from the events table.
    ship_row:
        Row from the ships table for the event's MMSI.
    enrichment_row:
        Row from the enrichment table, or None.
    last_departed_iso:
        ISO timestamp of the ship's most recent departure.  When provided and
        the ship has been away ≥1 day, the ARRIVED message reads
        "returns — away N days" instead of "has arrived — visit N".
    """
    enrich_name = enrichment_row["vessel_name"] if enrichment_row else None
    ais_name = ship_row["name"]
    if ais_name and (ais_name.strip() == "Unknown" or ais_name.strip().isdigit()):
        ais_name = None
    type_label = _ship_type_label(ship_row["ship_type"])
    name = enrich_name or ais_name or f"an unidentified {type_label}"
    event_type = event_row["event_type"]
    visit_count = ship_row["visit_count"] or 0

    if event_type == EventType.ENRICHED:
        return None

    if event_type == EventType.ARRIVED:
        if visit_count <= 1:
            named = enrich_name or ais_name
            if named:
                return f"First sighting: {named} — {type_label}"
            return f"First sighting of {name}"
        if last_departed_iso is not None:
            try:
                departed_dt = datetime.fromisoformat(last_departed_iso)
                days = (datetime.now(timezone.utc) - departed_dt).days
                if days >= 1:
                    day_str = f"{days} day{'s' if days != 1 else ''}"
                    return f"{name} returns — away {day_str}"
            except (ValueError, TypeError):
                pass
        return f"{name} has arrived — visit {visit_count}"

    if event_type == EventType.DEPARTED:
        return f"{name} has departed"

    if event_type == EventType.STATUS_CHANGE:
        # detail is "Name status: old → new" — rebuild with the best available name
        parts = event_row["detail"].split(" status: ", 1)
        status_part = parts[1] if len(parts) == 2 else event_row["detail"]
        return f"{name} status: {status_part}"

    return event_row["detail"]
