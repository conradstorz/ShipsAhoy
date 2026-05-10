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


def build_ship_chunks(
    ship_row: sqlite3.Row,
    enrichment_row: Optional[sqlite3.Row],
    distance_km: Optional[float] = None,
    bearing_label: Optional[str] = None,
) -> list[str]:
    """Return ordered prose chunks for one ship.

    Each chunk is a complete sentence containing the ship's name.
    Chunks for unavailable fields are omitted — no 'unknown' placeholders.
    """
    name: str = (
        enrichment_row["vessel_name"]
        if enrichment_row and enrichment_row["vessel_name"]
        else ship_row["name"]
    ) or "Unknown vessel"

    chunks: list[str] = []

    # 1. Identity
    flag = ship_row["flag"] or (enrichment_row["flag"] if enrichment_row else None)
    type_label = _type_label(ship_row["ship_type"])
    if flag:
        chunks.append(f"{name} is a {type_label} flying the {flag} flag")
    else:
        chunks.append(f"{name} is a {type_label}")

    # 2. Motion
    speed = ship_row["speed"]
    heading = ship_row["heading"]
    if speed is not None and heading is not None:
        direction = _cardinal_word(heading)
        chunks.append(f"{name} is traveling at {speed:.1f} knots heading {direction}")

    # 3. Position
    if distance_km is not None and bearing_label is not None:
        chunks.append(f"{name} is {distance_km:.1f} km away, to the {bearing_label}")

    # 4. Navigation status (only noteworthy ones)
    status = ship_row["status"]
    if status is not None and status in _NOTEWORTHY_STATUSES:
        chunks.append(f"{name} is currently {_STATUS_LABELS[status]}")

    # 5. Destination
    dest = ship_row["destination"]
    if dest and dest.strip() and dest.strip() != "0":
        chunks.append(f"{name} is bound for {dest.strip().title()}")

    # 6. Visit history
    visits = ship_row["visit_count"] or 1
    if visits == 1:
        chunks.append(f"This is {name}'s first visit to this area")
    else:
        chunks.append(f"{name} has visited this area {visits} times")

    # 7. Size and build year (requires enrichment)
    if enrichment_row:
        length = enrichment_row["length_m"]
        year = enrichment_row["build_year"]
        if length and year:
            chunks.append(f"{name} is {int(length)} meters long, built in {year}")
        elif length:
            chunks.append(f"{name} is {int(length)} meters long")

    # 8. Operator (requires enrichment)
    if enrichment_row and enrichment_row["owner"]:
        chunks.append(f"{name} is operated by {enrichment_row['owner']}")

    return chunks
