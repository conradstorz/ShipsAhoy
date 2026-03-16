"""Database access layer for ShipsAhoy.

All SQLite operations for all four services are defined here.
Uses WAL journal mode to support concurrent access from multiple processes.

Connection contract:
    Each service opens one connection at startup via init_db() and holds it
    for the process lifetime. WAL mode allows concurrent reads from multiple
    processes with one writer at a time. check_same_thread is not needed
    (one thread per service process).

Usage::

    conn = init_db("/path/to/ships.db")
    upsert_ship(conn, ship_info)
"""

import sqlite3
from typing import Optional

from ships_ahoy.ship_tracker import ShipInfo


_CREATE_SHIPS = """
CREATE TABLE IF NOT EXISTS ships (
    mmsi         INTEGER PRIMARY KEY,
    name         TEXT,
    ship_type    INTEGER,
    flag         TEXT,
    latitude     REAL,
    longitude    REAL,
    speed        REAL,
    heading      REAL,
    course       REAL,
    status       INTEGER,
    destination  TEXT,
    first_seen   DATETIME,
    last_seen    DATETIME,
    visit_count  INTEGER DEFAULT 0,
    enriched     BOOLEAN DEFAULT FALSE
)
"""

_CREATE_EVENTS = """
CREATE TABLE IF NOT EXISTS events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    mmsi         INTEGER,
    event_type   TEXT,
    detail       TEXT,
    created_at   DATETIME,
    displayed_at DATETIME
)
"""

_CREATE_ENRICHMENT = """
CREATE TABLE IF NOT EXISTS enrichment (
    mmsi            INTEGER PRIMARY KEY,
    vessel_name     TEXT,
    imo             TEXT,
    call_sign       TEXT,
    flag            TEXT,
    ship_type_label TEXT,
    length_m        REAL,
    build_year      INTEGER,
    owner           TEXT,
    photo_url       TEXT,
    photo_path      TEXT,
    source          TEXT,
    fetched_at      DATETIME,
    fetch_attempts  INTEGER DEFAULT 0
)
"""

_CREATE_SETTINGS = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
)
"""

_CREATE_SHIP_VISITS = """
CREATE TABLE IF NOT EXISTS ship_visits (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    mmsi        INTEGER,
    arrived_at  DATETIME,
    departed_at DATETIME
)
"""

_DEFAULT_SETTINGS = {
    "home_lat": None,
    "home_lon": None,
    "distance_km": "50",
    "scroll_speed_px_per_sec": "40",
    "stale_ship_hours": "1",
    "enrichment_delay_sec": "10",
    "enrichment_max_attempts": "3",
}


def init_db(path: str) -> sqlite3.Connection:
    """Create all tables, enable WAL mode, seed default settings, and return the connection.

    Parameters
    ----------
    path:
        Filesystem path to the SQLite database file, or ``":memory:"`` for tests.

    Returns
    -------
    sqlite3.Connection
        Open connection with WAL mode enabled and row_factory set to sqlite3.Row.
    """
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(_CREATE_SHIPS)
    conn.execute(_CREATE_EVENTS)
    conn.execute(_CREATE_ENRICHMENT)
    conn.execute(_CREATE_SETTINGS)
    conn.execute(_CREATE_SHIP_VISITS)
    for key, value in _DEFAULT_SETTINGS.items():
        conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            (key, value),
        )
    conn.commit()
    return conn


def upsert_ship(conn: sqlite3.Connection, ship: ShipInfo) -> None:
    """Insert or update a ship row from a ShipInfo object.

    Updates all known fields. first_seen is only set on first insert.
    visit_count is managed separately via record_visit/close_visit.
    """
    raise NotImplementedError


def get_ship(conn: sqlite3.Connection, mmsi: int) -> Optional[sqlite3.Row]:
    """Return the ships row for *mmsi*, or None if not found."""
    raise NotImplementedError


def get_enrichment(conn: sqlite3.Connection, mmsi: int) -> Optional[sqlite3.Row]:
    """Return the enrichment row for *mmsi*, or None if not found."""
    raise NotImplementedError


def get_unenriched_ships(conn: sqlite3.Connection, max_attempts: int) -> list[int]:
    """Return MMSIs where enriched=FALSE and fetch_attempts < max_attempts."""
    raise NotImplementedError


def save_enrichment(conn: sqlite3.Connection, mmsi: int, data: dict) -> None:
    """Write or update an enrichment row and mark ships.enriched=TRUE.

    Parameters
    ----------
    data:
        Dict with any subset of enrichment table columns as keys.
        Only keys present in data are written.
    """
    raise NotImplementedError


def write_event(
    conn: sqlite3.Connection,
    mmsi: int,
    event_type: str,
    detail: str,
) -> None:
    """Append a new event row with created_at=now() and displayed_at=NULL."""
    raise NotImplementedError


def get_pending_events(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return all events where displayed_at IS NULL, ordered by created_at ASC."""
    raise NotImplementedError


def get_recent_events(conn: sqlite3.Connection, limit: int = 50) -> list[sqlite3.Row]:
    """Return the most recent *limit* events ordered by created_at DESC."""
    raise NotImplementedError


def mark_event_displayed(conn: sqlite3.Connection, event_id: int) -> None:
    """Set displayed_at=now() for the given event id."""
    raise NotImplementedError


def get_ships_in_range(
    conn: sqlite3.Connection,
    home_lat: float,
    home_lon: float,
    km: float,
) -> list[sqlite3.Row]:
    """Return ships rows where last_seen is within the last stale_ship_hours
    and the haversine distance from (home_lat, home_lon) is <= km.

    Note: distance filtering is done in Python after fetching recently-seen
    ships (SQLite cannot compute haversine natively).
    """
    raise NotImplementedError


def get_visit_history(conn: sqlite3.Connection, mmsi: int) -> list[sqlite3.Row]:
    """Return all ship_visits rows for *mmsi*, newest first."""
    raise NotImplementedError


def record_visit(conn: sqlite3.Connection, mmsi: int) -> None:
    """Insert an open ship_visits row (departed_at NULL) and increment visit_count."""
    raise NotImplementedError


def close_visit(conn: sqlite3.Connection, mmsi: int) -> None:
    """Set departed_at=now() on the most recent open visit row for *mmsi*."""
    raise NotImplementedError


def mark_ship_departed(conn: sqlite3.Connection, mmsi: int) -> None:
    """Write a DEPARTED event, close the open visit, and log the departure.

    Does NOT delete the ships row — history is preserved permanently.
    Calls write_event() and close_visit() atomically within one transaction.
    """
    raise NotImplementedError
