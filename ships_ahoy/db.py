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
from datetime import datetime
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

_CREATE_DISPLAY_STATE = """
CREATE TABLE IF NOT EXISTS display_state (
    id           INTEGER PRIMARY KEY CHECK (id = 1),
    text         TEXT,
    speed        REAL,
    mode         TEXT,
    duration_ms  INTEGER,
    updated_at   DATETIME
)
"""

_DEFAULT_SETTINGS = [
    ("home_lat", None),
    ("home_lon", None),
    ("distance_km", "50"),
    ("scroll_speed_px_per_sec", "40"),
    ("stale_ship_hours", "1"),
    ("enrichment_delay_sec", "10"),
    ("enrichment_max_attempts", "3"),
    ("esp32_port", ""),
]

# Columns that save_enrichment is permitted to write — fixed literal set so the
# SQL template is never built from caller-supplied strings.
_ENRICHMENT_ALLOWED_COLS = (
    "vessel_name", "imo", "call_sign", "flag", "ship_type_label",
    "length_m", "build_year", "owner", "photo_url", "photo_path", "source",
)


def _now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now().isoformat()


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
    conn.execute(_CREATE_DISPLAY_STATE)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ships_last_seen ON ships (last_seen)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ships_enriched ON ships (enriched)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ships_position ON ships (latitude, longitude)"
        " WHERE latitude IS NOT NULL AND longitude IS NOT NULL"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_events_pending ON events (displayed_at, created_at)"
        " WHERE displayed_at IS NULL"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_events_recent ON events (created_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_visits_mmsi ON ship_visits (mmsi)"
    )
    conn.executemany(
        "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
        _DEFAULT_SETTINGS,
    )
    conn.commit()
    return conn


def upsert_ship(conn: sqlite3.Connection, ship: ShipInfo) -> None:
    """Insert or update a ship row from a ShipInfo object.

    Updates all known fields. first_seen is only set on first insert.
    visit_count is managed separately via record_visit/close_visit.
    """
    now = ship.last_seen.isoformat()
    conn.execute(
        """
        INSERT INTO ships (mmsi, name, ship_type, flag, latitude, longitude,
                           speed, heading, course, status, destination,
                           first_seen, last_seen)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(mmsi) DO UPDATE SET
            name        = excluded.name,
            ship_type   = excluded.ship_type,
            flag        = excluded.flag,
            latitude    = excluded.latitude,
            longitude   = excluded.longitude,
            speed       = excluded.speed,
            heading     = excluded.heading,
            course      = excluded.course,
            status      = excluded.status,
            destination = excluded.destination,
            last_seen   = excluded.last_seen
        """,
        (
            ship.mmsi, ship.name, ship.ship_type, ship.flag,
            ship.latitude, ship.longitude, ship.speed, ship.heading,
            ship.course, ship.status, ship.destination, now, now,
        ),
    )
    conn.commit()


def get_ship(conn: sqlite3.Connection, mmsi: int) -> Optional[sqlite3.Row]:
    """Return the ships row for *mmsi*, or None if not found."""
    return conn.execute("SELECT * FROM ships WHERE mmsi=?", (mmsi,)).fetchone()


def get_all_ships(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return all ships rows ordered by last_seen descending."""
    return conn.execute("SELECT * FROM ships ORDER BY last_seen DESC").fetchall()


def count_ships(conn: sqlite3.Connection) -> int:
    """Return the total number of ships in the database."""
    return conn.execute("SELECT COUNT(*) FROM ships").fetchone()[0]


def get_enrichment(conn: sqlite3.Connection, mmsi: int) -> Optional[sqlite3.Row]:
    """Return the enrichment row for *mmsi*, or None if not found."""
    return conn.execute("SELECT * FROM enrichment WHERE mmsi=?", (mmsi,)).fetchone()


def get_unenriched_ships(conn: sqlite3.Connection, max_attempts: int) -> list[int]:
    """Return MMSIs where enriched=FALSE and fetch_attempts < max_attempts."""
    rows = conn.execute(
        """
        SELECT s.mmsi FROM ships s
        LEFT JOIN enrichment e ON s.mmsi = e.mmsi
        WHERE s.enriched = FALSE
          AND COALESCE(e.fetch_attempts, 0) < ?
        """,
        (max_attempts,),
    ).fetchall()
    return [r["mmsi"] for r in rows]


def get_stale_mmsis(conn: sqlite3.Connection, threshold_iso: str) -> list[int]:
    """Return MMSIs for ships last seen before *threshold_iso* that still have an open visit.

    The open-visit join prevents duplicate DEPARTED events for ships already processed.
    """
    rows = conn.execute(
        """
        SELECT DISTINCT s.mmsi FROM ships s
        JOIN ship_visits sv ON s.mmsi = sv.mmsi
        WHERE s.last_seen < ?
          AND sv.departed_at IS NULL
        """,
        (threshold_iso,),
    ).fetchall()
    return [r["mmsi"] for r in rows]


def save_enrichment(conn: sqlite3.Connection, mmsi: int, data: dict) -> None:
    """Write or update an enrichment row and mark ships.enriched=TRUE.

    Parameters
    ----------
    data:
        Dict with any subset of enrichment table columns as keys.
        Only keys present in data are written.
    """
    fields = {k: v for k, v in data.items() if k in _ENRICHMENT_ALLOWED_COLS}
    fields["fetched_at"] = _now_iso()

    col_names = list(fields.keys())
    values = list(fields.values())
    placeholders = ", ".join("?" * len(col_names))
    col_list = ", ".join(["mmsi"] + col_names)
    set_clause = ", ".join(f"{c}=excluded.{c}" for c in col_names)

    conn.execute(
        f"INSERT INTO enrichment ({col_list}) VALUES (?, {placeholders})"  # noqa: S608
        f" ON CONFLICT(mmsi) DO UPDATE SET {set_clause}",
        (mmsi, *values),
    )
    conn.execute("UPDATE ships SET enriched=TRUE WHERE mmsi=?", (mmsi,))
    conn.commit()


def _write_event_sql(conn: sqlite3.Connection, mmsi: int, event_type: str, detail: str) -> None:
    """Execute the INSERT for an event row without committing."""
    conn.execute(
        "INSERT INTO events (mmsi, event_type, detail, created_at) VALUES (?, ?, ?, ?)",
        (mmsi, event_type, detail, _now_iso()),
    )


def write_event(
    conn: sqlite3.Connection,
    mmsi: int,
    event_type: str,
    detail: str,
) -> None:
    """Append a new event row with created_at=now() and displayed_at=NULL."""
    _write_event_sql(conn, mmsi, event_type, detail)
    conn.commit()


def get_pending_events(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return all events where displayed_at IS NULL, ordered by created_at ASC."""
    return conn.execute(
        "SELECT * FROM events WHERE displayed_at IS NULL ORDER BY created_at ASC"
    ).fetchall()


def get_recent_events(conn: sqlite3.Connection, limit: int = 50) -> list[sqlite3.Row]:
    """Return the most recent *limit* events ordered by created_at DESC."""
    return conn.execute(
        "SELECT * FROM events ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()


def mark_event_displayed(conn: sqlite3.Connection, event_id: int) -> None:
    """Set displayed_at=now() for the given event id."""
    conn.execute(
        "UPDATE events SET displayed_at=? WHERE id=?",
        (_now_iso(), event_id),
    )
    conn.commit()


def batch_mark_events_displayed(conn: sqlite3.Connection, event_ids: list[int]) -> None:
    """Set displayed_at=now() for all given event ids in a single statement."""
    if not event_ids:
        return
    placeholders = ",".join("?" * len(event_ids))
    conn.execute(
        f"UPDATE events SET displayed_at=? WHERE id IN ({placeholders})",  # noqa: S608
        (_now_iso(), *event_ids),
    )
    conn.commit()


def get_ships_in_range(
    conn: sqlite3.Connection,
    home_lat: float,
    home_lon: float,
    km: float,
) -> list[sqlite3.Row]:
    """Return ships rows where the haversine distance from (home_lat, home_lon) is <= km.

    Note: distance filtering is done in Python after fetching ships with known
    positions (SQLite cannot compute haversine natively).
    """
    from ships_ahoy.distance import haversine_km

    rows = conn.execute(
        "SELECT * FROM ships WHERE latitude IS NOT NULL AND longitude IS NOT NULL"
    ).fetchall()
    return [
        r for r in rows
        if haversine_km(home_lat, home_lon, r["latitude"], r["longitude"]) <= km
    ]


def get_visit_history(conn: sqlite3.Connection, mmsi: int) -> list[sqlite3.Row]:
    """Return all ship_visits rows for *mmsi*, newest first."""
    return conn.execute(
        "SELECT * FROM ship_visits WHERE mmsi=? ORDER BY id DESC", (mmsi,)
    ).fetchall()


def record_visit(conn: sqlite3.Connection, mmsi: int) -> None:
    """Insert an open ship_visits row (departed_at NULL) and increment visit_count."""
    conn.execute(
        "INSERT INTO ship_visits (mmsi, arrived_at) VALUES (?, ?)",
        (mmsi, _now_iso()),
    )
    conn.execute(
        "UPDATE ships SET visit_count = visit_count + 1 WHERE mmsi=?", (mmsi,)
    )
    conn.commit()


def _close_visit_sql(conn: sqlite3.Connection, mmsi: int) -> None:
    """Execute the UPDATE for closing the most recent open visit without committing."""
    conn.execute(
        """
        UPDATE ship_visits SET departed_at=?
        WHERE id = (
            SELECT id FROM ship_visits
            WHERE mmsi=? AND departed_at IS NULL
            ORDER BY id DESC LIMIT 1
        )
        """,
        (_now_iso(), mmsi),
    )


def close_visit(conn: sqlite3.Connection, mmsi: int) -> None:
    """Set departed_at=now() on the most recent open visit row for *mmsi*."""
    _close_visit_sql(conn, mmsi)
    conn.commit()


def mark_ship_departed(conn: sqlite3.Connection, mmsi: int) -> None:
    """Write a DEPARTED event and close the open visit in one atomic transaction.

    Does NOT delete the ships row — history is preserved permanently.
    """
    _write_event_sql(conn, mmsi, "DEPARTED", f"Ship {mmsi} departed")
    _close_visit_sql(conn, mmsi)
    conn.commit()


def increment_fetch_attempts(conn: sqlite3.Connection, mmsi: int) -> None:
    """Increment fetch_attempts for a ship's enrichment row without marking it enriched.

    Creates the enrichment row if it does not exist. Use this on scrape failures
    instead of save_enrichment() to avoid prematurely setting enriched=TRUE.
    """
    conn.execute(
        "INSERT INTO enrichment (mmsi, fetch_attempts) VALUES (?, 1)"
        " ON CONFLICT(mmsi) DO UPDATE SET fetch_attempts = fetch_attempts + 1",
        (mmsi,),
    )
    conn.commit()


def write_display_state(
    conn: sqlite3.Connection,
    text: str,
    speed: float,
    mode: str,
    duration_ms: int,
) -> None:
    """Write current display content to the single-row display_state table.

    Uses INSERT OR REPLACE to guarantee exactly one row exists at all times.
    """
    conn.execute(
        """
        INSERT OR REPLACE INTO display_state (id, text, speed, mode, duration_ms, updated_at)
        VALUES (1, ?, ?, ?, ?, ?)
        """,
        (text, speed, mode, duration_ms, _now_iso()),
    )
    conn.commit()


def get_display_state(conn: sqlite3.Connection) -> Optional[sqlite3.Row]:
    """Return the single display_state row, or None if not yet written."""
    return conn.execute("SELECT * FROM display_state").fetchone()
