"""Content generation for the ShipsAhoy LED ticker.

Builds prose-sentence chunks from ship and enrichment data, assembles
playlists for the continuous-cycle ticker service and web preview.

No I/O except DB reads — fully testable without hardware.

Usage::

    chunks = build_ship_chunks(ship_row, enrichment_row, distance_km=1.4, bearing_label="southwest")
    playlist = build_playlist(conn, cfg)
    for text in playlist:
        driver.scroll_text(text, speed_px_per_sec=cfg.scroll_speed)
"""

import random
import sqlite3
from typing import Optional

from ships_ahoy.config import Config
from ships_ahoy.db import get_active_quips, get_enrichment, get_ships_in_range
from ships_ahoy.distance import bearing_to_cardinal, distance_info
from ships_ahoy.message_builder import format_ship_display

_STATUS_LABELS: dict[int, str] = {
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

# Status codes worth announcing (excludes 0=underway and 8=underway sailing)
_NOTEWORTHY_STATUSES: frozenset[int] = frozenset({1, 2, 3, 4, 5, 6, 7})

_CARDINAL_WORDS: dict[str, str] = {
    "N": "north", "NNE": "north-northeast", "NE": "northeast",
    "ENE": "east-northeast", "E": "east", "ESE": "east-southeast",
    "SE": "southeast", "SSE": "south-southeast", "S": "south",
    "SSW": "south-southwest", "SW": "southwest", "WSW": "west-southwest",
    "W": "west", "WNW": "west-northwest", "NW": "northwest",
    "NNW": "north-northwest",
}


def _type_label(ship_type: Optional[int]) -> str:
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


def _cardinal_word(degrees: float) -> str:
    """Convert a bearing in degrees to a full compass-direction word."""
    abbr = bearing_to_cardinal(degrees)
    return _CARDINAL_WORDS.get(abbr, abbr)


def _extract_facts(
    ship_row: sqlite3.Row,
    enrichment_row: Optional[sqlite3.Row],
    distance_km: Optional[float] = None,
    bearing_label: Optional[str] = None,
) -> dict:
    """Convert DB rows into a plain facts dict for format_ship_display."""
    name: str = (
        enrichment_row["vessel_name"]
        if enrichment_row and enrichment_row["vessel_name"]
        else ship_row["name"]
    ) or "Unknown vessel"

    flag = ship_row["flag"] or (enrichment_row["flag"] if enrichment_row else None)

    heading = ship_row["heading"]
    heading_word = _cardinal_word(heading) if heading is not None else None

    status = ship_row["status"]
    status_label = (
        _STATUS_LABELS[status]
        if status is not None and status in _NOTEWORTHY_STATUSES
        else None
    )

    dest = ship_row["destination"]
    destination = (
        dest.strip().title()
        if dest and dest.strip() and dest.strip() != "0"
        else None
    )

    length = enrichment_row["length_m"] if enrichment_row else None
    build_year = enrichment_row["build_year"] if enrichment_row else None
    owner = enrichment_row["owner"] if enrichment_row else None

    return {
        "name": name,
        "type_label": _type_label(ship_row["ship_type"]),
        "flag": flag,
        "speed_knots": ship_row["speed"],
        "heading_word": heading_word,
        "distance_km": distance_km,
        "bearing_word": bearing_label,
        "status_label": status_label,
        "destination": destination,
        "visit_count": ship_row["visit_count"] or 1,
        "length_m": length,
        "build_year": build_year,
        "owner": owner,
    }


def build_ship_chunks(
    ship_row: sqlite3.Row,
    enrichment_row: Optional[sqlite3.Row],
    distance_km: Optional[float] = None,
    bearing_label: Optional[str] = None,
) -> list[str]:
    """Return ordered prose chunks for one ship (verbose mode).

    Each chunk is a complete sentence containing the ship's name.
    Chunks for unavailable fields are omitted — no 'unknown' placeholders.
    """
    facts = _extract_facts(ship_row, enrichment_row, distance_km, bearing_label)
    return format_ship_display(facts, mode="verbose")


def get_in_range_ships_with_distance(
    conn: sqlite3.Connection,
    cfg: Config,
) -> list[tuple[sqlite3.Row, Optional[sqlite3.Row], float, str]]:
    """Return (ship_row, enrichment_row, distance_km, bearing_word) sorted closest-first.

    Returns an empty list if home location is not configured.
    """
    home = cfg.home_location
    if home is None:
        return []
    home_lat, home_lon = home
    ships = get_ships_in_range(conn, home_lat, home_lon, cfg.distance_km)
    result: list[tuple[sqlite3.Row, Optional[sqlite3.Row], float, str]] = []
    for ship in ships:
        km, cardinal = distance_info(home_lat, home_lon, ship["latitude"], ship["longitude"])
        bearing_word = _CARDINAL_WORDS.get(cardinal, cardinal)
        enrichment = get_enrichment(conn, ship["mmsi"])
        result.append((ship, enrichment, km, bearing_word))
    result.sort(key=lambda x: x[2])
    return result


def build_idle_chunks(conn: sqlite3.Connection) -> list[str]:
    """Return 'No ships in range' followed by shuffled active quips and location facts."""
    rows = get_active_quips(conn)
    texts = [r["text"] for r in rows]
    random.shuffle(texts)
    return ["No ships in range"] + texts


def build_playlist(conn: sqlite3.Connection, cfg: Config) -> list[str]:
    """Return the full scroll playlist for one cycle.

    If ships are in range: prose chunks for each ship, closest-first.
    If no ships (or home not configured): idle chunks.
    """
    ships_data = get_in_range_ships_with_distance(conn, cfg)
    if not ships_data:
        return build_idle_chunks(conn)
    mode = "compact" if cfg.compact else "verbose"
    playlist: list[str] = []
    for ship_row, enrichment_row, distance_km, bearing_label in ships_data:
        facts = _extract_facts(ship_row, enrichment_row, distance_km, bearing_label)
        playlist.extend(format_ship_display(facts, mode=mode))
    return playlist
