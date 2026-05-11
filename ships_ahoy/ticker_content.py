"""Content generation for the ShipsAhoy LED ticker.

Builds prose-sentence chunks from ship and enrichment data, assembles
playlists for the continuous-cycle ticker service and web preview.

No I/O except DB reads — fully testable without hardware.

``build_playlist`` returns ``list[tuple[str, tuple[int, ...]]]`` where each
entry is (display_text, mmsi_tuple).  The MMSI tuple carries the ship(s)
responsible for that entry so the ticker service can call ``mark_ship_shown``
after scrolling.  Idle entries use an empty MMSI tuple ``()``.

Usage::

    chunks = build_ship_chunks(ship_row, enrichment_row, distance_km=1.4, bearing_label="southwest")
    playlist = build_playlist(conn, cfg)
    for text, mmsis in playlist:
        driver.scroll_text(text, speed_px_per_sec=cfg.scroll_speed)
"""

import random
import sqlite3
from typing import Optional

from ships_ahoy.config import Config
from ships_ahoy.db import get_active_quips, get_enrichment, get_ships_in_range
from ships_ahoy.distance import bearing_to_cardinal, distance_info
from ships_ahoy.destination import resolve_destination
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


def _is_stationary(ship_row: sqlite3.Row) -> bool:
    """Return True if the ship is not meaningfully moving."""
    status = ship_row["status"]
    if status in (1, 5, 6):  # at anchor, moored, aground
        return True
    speed = ship_row["speed"]
    return speed is not None and speed < 0.5


def _display_name(ship_row: sqlite3.Row, enrichment_row: Optional[sqlite3.Row]) -> str:
    """Return the best available display name for a ship."""
    enrich_name = enrichment_row["vessel_name"] if enrichment_row else None
    ais_name = ship_row["name"]
    if ais_name and (ais_name.strip() == "Unknown" or ais_name.strip().isdigit()):
        ais_name = None
    return enrich_name or ais_name or str(ship_row["mmsi"])


def _extract_facts(
    ship_row: sqlite3.Row,
    enrichment_row: Optional[sqlite3.Row],
    distance_km: Optional[float] = None,
    bearing_label: Optional[str] = None,
) -> dict:
    """Convert DB rows into a plain facts dict for format_ship_display."""
    enrich_name = enrichment_row["vessel_name"] if enrichment_row else None
    ais_name = ship_row["name"]
    # Discard junk AIS names: "Unknown" (pre-fix default) or bare MMSI digits
    if ais_name and (ais_name.strip() == "Unknown" or ais_name.strip().isdigit()):
        ais_name = None
    name: str = enrich_name or ais_name or "Unknown vessel"

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
    destination = None
    if dest and dest.strip() and dest.strip() != "0":
        raw_dest = dest.strip()
        lat = ship_row["latitude"]
        lon = ship_row["longitude"]
        destination = resolve_destination(raw_dest, lat=lat, lon=lon) or raw_dest.title()

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


def build_playlist(
    conn: sqlite3.Connection, cfg: Config
) -> list[tuple[str, tuple[int, ...]]]:
    """Return the full scroll playlist for one cycle.

    Each entry is ``(text, mmsi_tuple)``.  ``mmsi_tuple`` carries the MMSI(s)
    whose ``ticker_shown_at`` the caller should update after scrolling.
    Idle entries have an empty MMSI tuple.

    Ordering:
    - Moving ships sorted by ``ticker_shown_at`` ASC NULLS FIRST (never-shown
      ships appear before recently-shown ones), with distance as tiebreaker.
    - Stationary ships (anchored / moored / speed < 0.5 kn) are collapsed into
      a single ``"At anchor: Name1, Name2, …"`` entry at the end, tagged with
      all their MMSIs so they are marked shown as a group.
    """
    ships_data = get_in_range_ships_with_distance(conn, cfg)
    if not ships_data:
        return [(text, ()) for text in build_idle_chunks(conn)]

    mode = "compact" if cfg.compact else "verbose"

    moving = [entry for entry in ships_data if not _is_stationary(entry[0])]
    stationary = [entry for entry in ships_data if _is_stationary(entry[0])]

    # Sort moving ships: never-shown first, then least-recently-shown, then closest
    moving.sort(key=lambda x: (
        x[0]["ticker_shown_at"] is not None,
        x[0]["ticker_shown_at"] or "",
        x[2],
    ))

    playlist: list[tuple[str, tuple[int, ...]]] = []
    for ship_row, enrichment_row, distance_km, bearing_label in moving:
        facts = _extract_facts(ship_row, enrichment_row, distance_km, bearing_label)
        for chunk in format_ship_display(facts, mode=mode):
            playlist.append((chunk, (ship_row["mmsi"],)))

    if stationary:
        names = [_display_name(s, e) for s, e, _, _ in stationary]
        mmsis = tuple(s["mmsi"] for s, _, _, _ in stationary)
        playlist.append(("At anchor: " + ", ".join(names), mmsis))

    return playlist
