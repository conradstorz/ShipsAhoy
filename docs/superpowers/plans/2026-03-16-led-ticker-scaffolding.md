# ShipsAhoy LED Ticker Scaffolding Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Create the complete file/module scaffolding for the ShipsAhoy LED ticker system — all stubs wired and importable, with tests written and failing for the right reason (NotImplementedError, not ImportError), and distance.py fully implemented.

**Architecture:** Four independent systemd-managed Python services share a single SQLite database (WAL mode). A shared library (`ships_ahoy/`) provides all DB access, configuration, event detection, distance math, and LED driver abstraction. Services are thin loops that import from the shared library.

**Tech Stack:** Python 3.11+, uv, SQLite3, pyais, Flask, requests, BeautifulSoup4, rpi-rgb-led-matrix (Pi only), pytest

**Spec:** `docs/superpowers/specs/2026-03-16-led-ticker-design.md`

---

## Chunk 1: Core Shared Library

### Task 1: Extend ShipInfo with destination and flag

**Files:**
- Modify: `ships_ahoy/ship_tracker.py`
- Modify: `tests/test_ship_tracker.py`

- [x] **Step 1.1: Read existing ShipInfo dataclass**

Read `ships_ahoy/ship_tracker.py` lines 25–51. Identify where to add the two new fields.

- [x] **Step 1.2: Write failing tests for new fields**

Add to `tests/test_ship_tracker.py`:

```python
def test_ship_info_has_destination_field():
    ship = ShipInfo(mmsi=123456789)
    assert ship.destination is None

def test_ship_info_has_flag_field():
    ship = ShipInfo(mmsi=123456789)
    assert ship.flag is None

def test_ship_info_destination_can_be_set():
    ship = ShipInfo(mmsi=123456789, destination="ROTTERDAM")
    assert ship.destination == "ROTTERDAM"

def test_ship_info_flag_can_be_set():
    ship = ShipInfo(mmsi=123456789, flag="NL")
    assert ship.flag == "NL"
```

- [x] **Step 1.3: Run tests to confirm they fail**

Run: `uv run pytest tests/test_ship_tracker.py::test_ship_info_has_destination_field -v`
Expected: FAIL — `TypeError: ShipInfo.__init__() got an unexpected keyword argument`

- [x] **Step 1.4: Add fields to ShipInfo**

In `ships_ahoy/ship_tracker.py`, add after `status`:

```python
destination: Optional[str] = None  # port of destination from AIS type-5
flag: Optional[str] = None         # country flag code from AIS type-24
```

- [x] **Step 1.5: Run all ship_tracker tests**

Run: `uv run pytest tests/test_ship_tracker.py -v`
Expected: All PASS

- [x] **Step 1.6: Commit**

```
git add ships_ahoy/ship_tracker.py tests/test_ship_tracker.py
git commit -m "feat: extend ShipInfo with destination and flag fields"
```

---

### Task 2: Scaffold ships_ahoy/db.py

**Files:**
- Create: `ships_ahoy/db.py`
- Create: `tests/test_db.py`

- [x] **Step 2.1: Write test_db.py**

Create `tests/test_db.py`:

```python
"""Tests for ships_ahoy.db.

All tests use an in-memory SQLite database.
Tests verify: schema creation, WAL mode, and function signatures.
Behavior tests will raise NotImplementedError until implementation is complete.
"""
import sqlite3
import pytest
from ships_ahoy.db import (
    init_db,
    upsert_ship,
    get_ship,
    get_enrichment,
    get_unenriched_ships,
    save_enrichment,
    write_event,
    get_pending_events,
    get_recent_events,
    mark_event_displayed,
    get_ships_in_range,
    get_visit_history,
    record_visit,
    close_visit,
    mark_ship_departed,
)
from ships_ahoy.ship_tracker import ShipInfo


@pytest.fixture
def conn():
    return init_db(":memory:")


def test_init_db_returns_connection(conn):
    assert isinstance(conn, sqlite3.Connection)


def test_init_db_creates_ships_table(conn):
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ships'")
    assert cursor.fetchone() is not None


def test_init_db_creates_events_table(conn):
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='events'")
    assert cursor.fetchone() is not None


def test_init_db_creates_enrichment_table(conn):
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='enrichment'")
    assert cursor.fetchone() is not None


def test_init_db_creates_settings_table(conn):
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='settings'")
    assert cursor.fetchone() is not None


def test_init_db_creates_ship_visits_table(conn):
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ship_visits'")
    assert cursor.fetchone() is not None


def test_init_db_enables_wal_mode(tmp_path):
    # WAL mode is silently ignored on :memory: databases — use a real file.
    db_path = str(tmp_path / "test.db")
    conn = init_db(db_path)
    row = conn.execute("PRAGMA journal_mode").fetchone()
    assert row[0] == "wal"
    conn.close()


def test_upsert_ship_raises(conn):
    ship = ShipInfo(mmsi=123456789, name="TEST VESSEL")
    with pytest.raises(NotImplementedError):
        upsert_ship(conn, ship)


def test_get_ship_raises(conn):
    with pytest.raises(NotImplementedError):
        get_ship(conn, 123456789)


def test_get_enrichment_raises(conn):
    with pytest.raises(NotImplementedError):
        get_enrichment(conn, 123456789)


def test_get_unenriched_ships_raises(conn):
    with pytest.raises(NotImplementedError):
        get_unenriched_ships(conn, max_attempts=3)


def test_save_enrichment_raises(conn):
    with pytest.raises(NotImplementedError):
        save_enrichment(conn, 123456789, {})


def test_write_event_raises(conn):
    with pytest.raises(NotImplementedError):
        write_event(conn, 123456789, "ARRIVED", "test detail")


def test_get_pending_events_raises(conn):
    with pytest.raises(NotImplementedError):
        get_pending_events(conn)


def test_get_recent_events_raises(conn):
    with pytest.raises(NotImplementedError):
        get_recent_events(conn)


def test_mark_event_displayed_raises(conn):
    with pytest.raises(NotImplementedError):
        mark_event_displayed(conn, 1)


def test_get_ships_in_range_raises(conn):
    with pytest.raises(NotImplementedError):
        get_ships_in_range(conn, 51.5, -0.1, 50.0)


def test_get_visit_history_raises(conn):
    with pytest.raises(NotImplementedError):
        get_visit_history(conn, 123456789)


def test_record_visit_raises(conn):
    with pytest.raises(NotImplementedError):
        record_visit(conn, 123456789)


def test_close_visit_raises(conn):
    with pytest.raises(NotImplementedError):
        close_visit(conn, 123456789)


def test_mark_ship_departed_raises(conn):
    with pytest.raises(NotImplementedError):
        mark_ship_departed(conn, 123456789)
```

- [x] **Step 2.2: Run test to confirm ImportError**

Run: `uv run pytest tests/test_db.py -v`
Expected: ERROR — `ModuleNotFoundError: No module named 'ships_ahoy.db'`

- [x] **Step 2.3: Create ships_ahoy/db.py scaffold**

Create `ships_ahoy/db.py`:

```python
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
```

- [x] **Step 2.4: Run tests — expect init_db tests to pass, rest to raise NotImplementedError**

Note: `init_db()` is the one function in `db.py` that is fully implemented (not stubbed), because
all other tests depend on a working connection with the correct schema. The fail-first TDD step
for `test_init_db_*` was intentionally skipped — those tests are verified structurally in Step 2.1
and confirmed passing below.

Run: `uv run pytest tests/test_db.py -v`
Expected:
- `test_init_db_*` tests: PASS (init_db is fully implemented)
- All other tests: PASS (they assert NotImplementedError, which is raised)

- [x] **Step 2.5: Commit**

```
git add ships_ahoy/db.py tests/test_db.py
git commit -m "feat: scaffold db.py with table creation and function stubs"
```

---

### Task 3: Scaffold ships_ahoy/config.py

**Files:**
- Create: `ships_ahoy/config.py`
- Create: `tests/test_config.py`

- [x] **Step 3.1: Write test_config.py**

Create `tests/test_config.py`:

```python
"""Tests for ships_ahoy.config.

Uses an in-memory DB seeded with default settings.
Behavior tests raise NotImplementedError until implementation is complete.
"""
import pytest
from ships_ahoy.db import init_db
from ships_ahoy.config import Config


@pytest.fixture
def config():
    conn = init_db(":memory:")
    return Config(conn)


def test_config_can_be_instantiated(config):
    assert config is not None


def test_config_get_raises(config):
    with pytest.raises(NotImplementedError):
        config.get("distance_km")


def test_config_set_raises(config):
    with pytest.raises(NotImplementedError):
        config.set("distance_km", "100")


def test_config_home_location_raises(config):
    with pytest.raises(NotImplementedError):
        _ = config.home_location


def test_config_distance_km_raises(config):
    with pytest.raises(NotImplementedError):
        _ = config.distance_km


def test_config_stale_ship_hours_raises(config):
    with pytest.raises(NotImplementedError):
        _ = config.stale_ship_hours


def test_config_scroll_speed_raises(config):
    with pytest.raises(NotImplementedError):
        _ = config.scroll_speed


def test_config_enrichment_delay_sec_raises(config):
    with pytest.raises(NotImplementedError):
        _ = config.enrichment_delay_sec


def test_config_enrichment_max_attempts_raises(config):
    with pytest.raises(NotImplementedError):
        _ = config.enrichment_max_attempts
```

- [x] **Step 3.2: Run to confirm ImportError**

Run: `uv run pytest tests/test_config.py -v`
Expected: ERROR — `ModuleNotFoundError: No module named 'ships_ahoy.config'`

- [x] **Step 3.3: Create ships_ahoy/config.py scaffold**

Create `ships_ahoy/config.py`:

```python
"""Settings table wrapper for ShipsAhoy.

Re-reads the database on every property access so that changes made
via the web portal take effect immediately without restarting services.

Usage::

    conn = init_db("/path/to/ships.db")
    cfg = Config(conn)
    lat, lon = cfg.home_location or (None, None)
    threshold = cfg.distance_km
"""

import sqlite3
from typing import Optional


class Config:
    """Provides typed access to the settings table.

    Each property re-reads from the database on every access.
    No caching — this ensures web portal changes propagate immediately.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Read a setting by key. Returns *default* if the key is absent or NULL."""
        raise NotImplementedError

    def set(self, key: str, value: str) -> None:
        """Write a setting. Inserts or replaces the row."""
        raise NotImplementedError

    @property
    def home_location(self) -> Optional[tuple]:
        """Return (lat, lon) when both are set, otherwise None.

        When None, callers should log a warning and treat all ships as noteworthy.
        """
        raise NotImplementedError

    @property
    def distance_km(self) -> float:
        """Return the noteworthy-ship distance threshold in kilometres."""
        raise NotImplementedError

    @property
    def stale_ship_hours(self) -> float:
        """Return hours before an absent ship fires a DEPARTED event."""
        raise NotImplementedError

    @property
    def scroll_speed(self) -> float:
        """Return LED ticker scroll speed in pixels per second."""
        raise NotImplementedError

    @property
    def enrichment_delay_sec(self) -> float:
        """Return seconds to wait between enrichment scrape requests."""
        raise NotImplementedError

    @property
    def enrichment_max_attempts(self) -> int:
        """Return max scrape attempts per ship before permanently skipping."""
        raise NotImplementedError
```

- [x] **Step 3.4: Run tests**

Run: `uv run pytest tests/test_config.py -v`
Expected: All PASS (`test_config_can_be_instantiated` passes; all others assert NotImplementedError)

- [x] **Step 3.5: Commit**

```
git add ships_ahoy/config.py tests/test_config.py
git commit -m "feat: scaffold config.py settings wrapper"
```

---

### Task 4: Implement ships_ahoy/distance.py (fully)

Distance functions are pure math — implement fully, no stubs.

**Files:**
- Create: `ships_ahoy/distance.py`
- Create: `tests/test_distance.py`

- [x] **Step 4.1: Write test_distance.py with known reference values**

Create `tests/test_distance.py`:

```python
"""Tests for ships_ahoy.distance.

Reference values computed from known coordinates.
London (51.5074, -0.1278) to Paris (48.8566, 2.3522) ≈ 340.6 km, bearing ≈ 156° (SSE).
"""
import pytest
from ships_ahoy.distance import (
    haversine_km,
    bearing_degrees,
    bearing_to_cardinal,
    is_noteworthy,
)

LONDON = (51.5074, -0.1278)
PARIS = (48.8566, 2.3522)


def test_haversine_london_to_paris():
    km = haversine_km(*LONDON, *PARIS)
    assert 338 < km < 343


def test_haversine_same_point_is_zero():
    assert haversine_km(51.5, -0.1, 51.5, -0.1) == pytest.approx(0.0, abs=1e-6)


def test_haversine_is_symmetric():
    a = haversine_km(*LONDON, *PARIS)
    b = haversine_km(*PARIS, *LONDON)
    assert a == pytest.approx(b, rel=1e-6)


def test_bearing_london_to_paris():
    bearing = bearing_degrees(*LONDON, *PARIS)
    assert 150 < bearing < 162


def test_bearing_due_north():
    bearing = bearing_degrees(0.0, 0.0, 1.0, 0.0)
    assert bearing == pytest.approx(0.0, abs=1.0)


def test_bearing_due_east():
    bearing = bearing_degrees(0.0, 0.0, 0.0, 1.0)
    assert bearing == pytest.approx(90.0, abs=1.0)


def test_bearing_to_cardinal_north():
    assert bearing_to_cardinal(0.0) == "N"
    assert bearing_to_cardinal(360.0) == "N"


def test_bearing_to_cardinal_south():
    assert bearing_to_cardinal(180.0) == "S"


def test_bearing_to_cardinal_east():
    assert bearing_to_cardinal(90.0) == "E"


def test_bearing_to_cardinal_west():
    assert bearing_to_cardinal(270.0) == "W"


def test_bearing_to_cardinal_sse():
    # London to Paris is roughly SSE (~156 degrees)
    assert bearing_to_cardinal(156.0) == "SSE"


def test_bearing_to_cardinal_wsw():
    assert bearing_to_cardinal(247.0) == "WSW"


def test_is_noteworthy_within_range():
    # Paris is ~340 km from London; threshold 400 km → noteworthy
    assert is_noteworthy(*PARIS, *LONDON, threshold_km=400.0) is True


def test_is_noteworthy_outside_range():
    # Paris is ~340 km from London; threshold 200 km → not noteworthy
    assert is_noteworthy(*PARIS, *LONDON, threshold_km=200.0) is False


def test_is_noteworthy_exactly_on_boundary():
    km = haversine_km(*LONDON, *PARIS)
    assert is_noteworthy(*PARIS, *LONDON, threshold_km=km) is True
```

- [x] **Step 4.2: Run to confirm ImportError**

Run: `uv run pytest tests/test_distance.py -v`
Expected: ERROR — `ModuleNotFoundError: No module named 'ships_ahoy.distance'`

- [x] **Step 4.3: Create ships_ahoy/distance.py (full implementation)**

Create `ships_ahoy/distance.py`:

```python
"""Geographic distance and bearing utilities for ShipsAhoy.

All functions operate on WGS-84 decimal degrees.

Usage::

    km = haversine_km(ship.latitude, ship.longitude, home_lat, home_lon)
    direction = bearing_to_cardinal(bearing_degrees(...))
    if is_noteworthy(ship.latitude, ship.longitude, home_lat, home_lon, 50.0):
        ...
"""

import math


_EARTH_RADIUS_KM = 6371.0

_CARDINALS = [
    "N", "NNE", "NE", "ENE",
    "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW",
    "W", "WNW", "NW", "NNW",
]


def haversine_km(
    lat1: float, lon1: float,
    lat2: float, lon2: float,
) -> float:
    """Return the great-circle distance in kilometres between two points.

    Parameters
    ----------
    lat1, lon1:
        Origin coordinates in decimal degrees.
    lat2, lon2:
        Destination coordinates in decimal degrees.
    """
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def bearing_degrees(
    lat1: float, lon1: float,
    lat2: float, lon2: float,
) -> float:
    """Return the initial bearing in degrees (0–360) from point 1 to point 2.

    0° = North, 90° = East, 180° = South, 270° = West.
    """
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dlambda = math.radians(lon2 - lon1)
    x = math.sin(dlambda) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlambda)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def bearing_to_cardinal(degrees: float) -> str:
    """Convert a bearing in degrees to a 16-point cardinal string.

    Examples: 0° → "N", 90° → "E", 247° → "WSW"
    """
    index = round(degrees / 22.5) % 16
    return _CARDINALS[index]


def is_noteworthy(
    ship_lat: float,
    ship_lon: float,
    home_lat: float,
    home_lon: float,
    threshold_km: float,
) -> bool:
    """Return True if the ship is within *threshold_km* of the home location."""
    return haversine_km(ship_lat, ship_lon, home_lat, home_lon) <= threshold_km
```

- [x] **Step 4.4: Run tests — all should pass**

Run: `uv run pytest tests/test_distance.py -v`
Expected: All 14 PASS

- [x] **Step 4.5: Commit**

```
git add ships_ahoy/distance.py tests/test_distance.py
git commit -m "feat: implement distance.py (haversine, bearing, cardinal, is_noteworthy)"
```

---

### Task 5: Scaffold ships_ahoy/events.py

**Files:**
- Create: `ships_ahoy/events.py`
- Create: `tests/test_events.py`

- [x] **Step 5.1: Write test_events.py**

Create `tests/test_events.py`:

```python
"""Tests for ships_ahoy.events.

detect_events compares two ShipInfo snapshots and returns change events.
format_ticker_message produces single-line strings for the LED ticker.
"""
import sqlite3
import pytest
from ships_ahoy.events import EventType, detect_events, format_ticker_message
from ships_ahoy.ship_tracker import ShipInfo


def make_ship(**kwargs):
    defaults = dict(mmsi=123456789, name="TEST VESSEL", status=0)
    defaults.update(kwargs)
    return ShipInfo(**defaults)


# --- EventType constants ---

def test_event_type_arrived():
    assert EventType.ARRIVED == "ARRIVED"


def test_event_type_departed():
    assert EventType.DEPARTED == "DEPARTED"


def test_event_type_status_change():
    assert EventType.STATUS_CHANGE == "STATUS_CHANGE"


def test_event_type_enriched():
    assert EventType.ENRICHED == "ENRICHED"


# --- detect_events ---

def test_detect_events_no_change_returns_empty():
    ship = make_ship()
    with pytest.raises(NotImplementedError):
        detect_events(ship, ship)


def test_detect_events_status_change_detected():
    old = make_ship(status=1)   # At anchor
    new = make_ship(status=0)   # Under way
    with pytest.raises(NotImplementedError):
        detect_events(old, new)


def test_detect_events_not_called_for_new_ships():
    """ARRIVED is written directly by ais_service; detect_events is never called
    with a 'new' ship. This test documents that contract by showing detect_events
    requires two ShipInfo objects — it has no None-safe path."""
    ship = make_ship()
    # Passing None should raise TypeError, not NotImplementedError
    with pytest.raises((TypeError, NotImplementedError)):
        detect_events(None, ship)  # type: ignore[arg-type]


# --- format_ticker_message ---

def test_format_ticker_message_raises():
    # sqlite3.Row cannot be easily constructed in tests; use None to verify stub
    with pytest.raises((NotImplementedError, TypeError)):
        format_ticker_message(None, None, None)
```

- [x] **Step 5.2: Run to confirm ImportError**

Run: `uv run pytest tests/test_events.py -v`
Expected: ERROR — `ModuleNotFoundError: No module named 'ships_ahoy.events'`

- [x] **Step 5.3: Create ships_ahoy/events.py scaffold**

Create `ships_ahoy/events.py`:

```python
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
```

- [x] **Step 5.4: Run tests**

Run: `uv run pytest tests/test_events.py -v`
Expected: All PASS

- [x] **Step 5.5: Commit**

```
git add ships_ahoy/events.py tests/test_events.py
git commit -m "feat: scaffold events.py with EventType constants and function stubs"
```

---

### Task 6: Scaffold ships_ahoy/matrix_driver.py

**Files:**
- Create: `ships_ahoy/matrix_driver.py`
- Create: `tests/test_matrix_driver.py`

- [x] **Step 6.1: Write test_matrix_driver.py**

Create `tests/test_matrix_driver.py`:

```python
"""Tests for ships_ahoy.matrix_driver.

StubMatrixDriver must conform fully to the MatrixDriver interface.
These tests can run on any platform (no Pi hardware required).
"""
import pytest
from ships_ahoy.matrix_driver import MatrixDriver, StubMatrixDriver


def test_stub_is_matrix_driver_subclass():
    assert issubclass(StubMatrixDriver, MatrixDriver)


def test_stub_can_be_instantiated():
    driver = StubMatrixDriver()
    assert driver is not None


def test_stub_scroll_text_does_not_raise():
    driver = StubMatrixDriver()
    driver.scroll_text("TEST MESSAGE", speed_px_per_sec=40.0)


def test_stub_clear_does_not_raise():
    driver = StubMatrixDriver()
    driver.clear()


def test_stub_show_static_does_not_raise():
    driver = StubMatrixDriver()
    driver.show_static("IDLE TEXT", duration_sec=2.0)


def test_matrix_driver_scroll_text_is_abstract():
    """MatrixDriver cannot be instantiated directly."""
    with pytest.raises(TypeError):
        MatrixDriver()  # type: ignore[abstract]


def test_stub_scroll_text_accepts_empty_string():
    driver = StubMatrixDriver()
    driver.scroll_text("", speed_px_per_sec=40.0)


def test_stub_show_static_accepts_zero_duration():
    driver = StubMatrixDriver()
    driver.show_static("X", duration_sec=0.0)
```

- [x] **Step 6.2: Run to confirm ImportError**

Run: `uv run pytest tests/test_matrix_driver.py -v`
Expected: ERROR — `ModuleNotFoundError: No module named 'ships_ahoy.matrix_driver'`

- [x] **Step 6.3: Create ships_ahoy/matrix_driver.py scaffold**

Create `ships_ahoy/matrix_driver.py`:

```python
"""LED matrix driver abstraction for ShipsAhoy.

Defines the MatrixDriver interface and two concrete implementations:

- RGBMatrixDriver: real HUB75 driver using rpi-rgb-led-matrix Python bindings.
  Configured for 5 chained 64×32 panels (320×32 pixels total).
- StubMatrixDriver: no-op implementation for development and testing on
  non-Pi hardware. Logs text to stdout instead of driving hardware.

ticker_service.py imports MatrixDriver only. At startup it attempts to
import rpi-rgb-led-matrix; if unavailable it falls back to StubMatrixDriver.

Usage::

    try:
        from ships_ahoy.matrix_driver import RGBMatrixDriver as DriverClass
    except ImportError:
        from ships_ahoy.matrix_driver import StubMatrixDriver as DriverClass

    driver = DriverClass()
    driver.scroll_text("⚓ CARGO 'FOO' — underway", speed_px_per_sec=40.0)
"""

import abc
import logging

logger = logging.getLogger(__name__)

# HUB75 panel configuration constants
PANEL_WIDTH = 64
PANEL_HEIGHT = 32
PANEL_COUNT = 5
DISPLAY_WIDTH = PANEL_WIDTH * PANEL_COUNT  # 320
DISPLAY_HEIGHT = PANEL_HEIGHT              # 32


class MatrixDriver(abc.ABC):
    """Abstract base class for LED matrix display drivers.

    All implementations must be safe to call from a single-threaded
    service process. Methods are blocking — scroll_text does not return
    until the full scroll animation is complete.
    """

    @abc.abstractmethod
    def scroll_text(self, text: str, speed_px_per_sec: float) -> None:
        """Scroll *text* left across the full display width.

        Blocks until the text has scrolled fully off the left edge.

        Parameters
        ----------
        text:
            UTF-8 string to display. May include emoji.
        speed_px_per_sec:
            Scroll speed in pixels per second.
        """

    @abc.abstractmethod
    def clear(self) -> None:
        """Clear all pixels on the display."""

    @abc.abstractmethod
    def show_static(self, text: str, duration_sec: float) -> None:
        """Display *text* statically (no scrolling) for *duration_sec* seconds.

        Used for the idle "N ships nearby" message.
        """


class StubMatrixDriver(MatrixDriver):
    """No-op MatrixDriver for development and testing on non-Pi hardware.

    Instead of driving hardware, logs the text to stdout so developers
    can verify what would be displayed without a physical panel.
    """

    def scroll_text(self, text: str, speed_px_per_sec: float) -> None:
        """Log the text that would be scrolled."""
        logger.info("[StubMatrixDriver] scroll_text: %s (%.1f px/s)", text, speed_px_per_sec)
        print(f"[TICKER] {text}")

    def clear(self) -> None:
        """Log a clear operation."""
        logger.debug("[StubMatrixDriver] clear()")

    def show_static(self, text: str, duration_sec: float) -> None:
        """Log the static text that would be shown."""
        logger.info("[StubMatrixDriver] show_static: %s (%.1fs)", text, duration_sec)
        print(f"[TICKER IDLE] {text}")


class RGBMatrixDriver(MatrixDriver):
    """Real HUB75 driver using rpi-rgb-led-matrix Python bindings.

    Panel configuration: 5 chained 64×32 panels = 320×32 pixels total.

    Requires the rpi-rgb-led-matrix library to be installed and the
    process to run with appropriate GPIO permissions (typically root or
    a user in the gpio group with the library's suid bit set).

    Raises ImportError at module load time on non-Pi platforms.
    """

    def __init__(self) -> None:
        raise NotImplementedError(
            "RGBMatrixDriver requires rpi-rgb-led-matrix. "
            "See https://github.com/hzeller/rpi-rgb-led-matrix for installation."
        )

    def scroll_text(self, text: str, speed_px_per_sec: float) -> None:
        raise NotImplementedError

    def clear(self) -> None:
        raise NotImplementedError

    def show_static(self, text: str, duration_sec: float) -> None:
        raise NotImplementedError
```

- [x] **Step 6.4: Run tests — all should pass**

Run: `uv run pytest tests/test_matrix_driver.py -v`
Expected: All 8 PASS (StubMatrixDriver is fully implemented)

- [x] **Step 6.5: Run full test suite to confirm nothing broken**

Run: `uv run pytest -v`
Expected: All tests PASS

- [x] **Step 6.6: Commit**

```
git add ships_ahoy/matrix_driver.py tests/test_matrix_driver.py
git commit -m "feat: scaffold matrix_driver.py with MatrixDriver ABC, StubMatrixDriver, and RGBMatrixDriver stub"
```

---

## Chunk 2: AIS Service Scaffold

### Task 7: Scaffold services/ais_service.py

**Files:**
- Create: `services/__init__.py`
- Create: `services/ais_service.py`

- [x] **Step 7.1: Verify AISReceiver API before scaffolding**

Read `ships_ahoy/ais_receiver.py` and confirm:
- The class is named `AISReceiver`
- It has a `messages()` method that returns an iterable of decoded AIS messages
- The constants `DEFAULT_HOST` and `DEFAULT_TCP_PORT` are defined at module level

Expected: all three confirmed. If the method name differs, update `services/ais_service.py` accordingly.

- [x] **Step 7.2: Create services/__init__.py**

Create `services/__init__.py` (empty — marks directory as a package):

```python
# intentionally empty
```

- [x] **Step 7.3: Create services/ais_service.py scaffold**

Create `services/ais_service.py`:

```python
"""AIS Receiver Service for ShipsAhoy.

Hardened replacement for main.py. Runs as a persistent systemd service.

Responsibilities:
- Connect to rtl_ais over TCP or UDP via AISReceiver
- Reconnect on failure with exponential backoff (1s → 2s → 4s → … capped at 60s)
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

Configuration is read from the settings table via Config on each loop iteration
so that web portal changes take effect without restarting this service.

Usage (via systemd or manually)::

    uv run python services/ais_service.py [--host HOST] [--port PORT] [--udp] [--db PATH]
"""

import argparse
import logging
import sys
import time

from ships_ahoy.ais_receiver import AISReceiver, DEFAULT_HOST, DEFAULT_TCP_PORT
from ships_ahoy.config import Config
from ships_ahoy.db import init_db, get_ship, upsert_ship, write_event, record_visit, mark_ship_departed
from ships_ahoy.distance import is_noteworthy
from ships_ahoy.events import EventType, detect_events

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = "ships.db"
SWEEP_INTERVAL_SEC = 300  # 5 minutes
MAX_BACKOFF_SEC = 60


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
    raise NotImplementedError


def _run_stale_sweep(conn, cfg: Config) -> None:
    """Query for ships past stale_ship_hours and mark each as departed."""
    raise NotImplementedError


def _process_message(conn, msg, cfg: Config) -> None:
    """Handle one decoded AIS message: upsert ship, detect events, write events.

    - Fetches ship state before upsert for comparison.
    - Writes ARRIVED for new ships (not via detect_events).
    - Calls detect_events for existing ships.
    - Only writes events for ships within distance_km of home.
    """
    raise NotImplementedError


def main() -> None:
    """Service entry point. Loops forever; reconnects on failure."""
    args = _build_parser().parse_args()
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

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
```

- [x] **Step 7.4: Verify service imports cleanly**

Run: `uv run python -c "import services.ais_service; print('OK')"`
Expected: `OK` (no ImportError)

- [x] **Step 7.5: Commit**

```
git add services/__init__.py services/ais_service.py
git commit -m "feat: scaffold ais_service.py with reconnect loop and processing stubs"
```

---

## Chunk 3: Ticker Service Scaffold

### Task 8: Scaffold services/ticker_service.py

**Files:**
- Create: `services/ticker_service.py`

- [x] **Step 8.1: Create services/ticker_service.py scaffold**

Create `services/ticker_service.py`:

```python
"""LED Ticker Service for ShipsAhoy.

Drives the HUB75 LED matrix (5× 64×32 panels = 320×32 pixels).
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

Usage (via systemd or manually)::

    uv run python services/ticker_service.py [--db PATH] [--verbose]
"""

import argparse
import logging
import sys
import time

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

    Called when more than OVERFLOW_THRESHOLD events are older than
    OVERFLOW_AGE_MINUTES. Marks all pending events as displayed without
    scrolling them individually, then scrolls a single summary.
    """
    raise NotImplementedError


def _display_event(conn, event_row, driver, cfg: Config) -> None:
    """Fetch ship and enrichment data, format ticker message, scroll it, mark displayed."""
    raise NotImplementedError


def _show_idle(conn, driver, cfg: Config) -> None:
    """Display the idle message showing current ship count."""
    raise NotImplementedError


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
```

- [x] **Step 8.2: Verify imports cleanly**

Run: `uv run python -c "import services.ticker_service; print('OK')"`
Expected: `OK`

- [x] **Step 8.3: Commit**

```
git add services/ticker_service.py
git commit -m "feat: scaffold ticker_service.py with overflow handling and display stubs"
```

---

## Chunk 4: Enrichment Service Scaffold

### Task 9: Scaffold services/enrichment_service.py

**Files:**
- Create: `services/enrichment_service.py`

- [x] **Step 9.1: Create services/enrichment_service.py scaffold**

Create `services/enrichment_service.py`:

```python
"""Enrichment Service for ShipsAhoy.

Scrapes free internet sources to gather additional details about ships
and caches results in the enrichment table and static/photos/.

Runs as a persistent systemd service.

Responsibilities:
- Poll get_unenriched_ships() in a loop
- For each unenriched MMSI: attempt scrape from sources in priority order
- Sleep enrichment_delay_sec between each request (rate limiting)
- Download first available photo to static/photos/<mmsi>.jpg
- Mark ship enriched and write ENRICHED event on success
- Increment fetch_attempts on failure; stop retrying at enrichment_max_attempts

Scrape source priority order:
1. ShipXplorer: https://www.shipxplorer.com/vessel/<mmsi>
2. MarineTraffic (may block): https://www.marinetraffic.com/en/ais/details/ships/mmsi:<mmsi>
3. ITU MMSI lookup (form POST): https://www.itu.int/mmsapp/ShipSearch.do

HTTP client: requests + BeautifulSoup (html.parser)

All scraping is wrapped in try/except. Any HTTP or parse error increments
fetch_attempts and moves on to the next source.

Usage (via systemd or manually)::

    uv run python services/enrichment_service.py [--db PATH] [--photos-dir DIR] [--verbose]
"""

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

from ships_ahoy.config import Config
from ships_ahoy.db import init_db, get_unenriched_ships, save_enrichment, write_event
from ships_ahoy.events import EventType

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = "ships.db"
DEFAULT_PHOTOS_DIR = "static/photos"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="enrichment_service",
        description="ShipsAhoy Enrichment Service",
    )
    parser.add_argument("--db", default=DEFAULT_DB_PATH, metavar="PATH")
    parser.add_argument("--photos-dir", default=DEFAULT_PHOTOS_DIR, metavar="DIR")
    parser.add_argument("--verbose", action="store_true")
    return parser


def _scrape_shipxplorer(mmsi: int) -> Optional[dict]:
    """Attempt to scrape vessel data from ShipXplorer.

    Returns a dict with any of: vessel_name, imo, call_sign, flag,
    ship_type_label, length_m, build_year, owner, photo_url, source.
    Returns None on any failure.
    """
    raise NotImplementedError


def _scrape_marinetraffic(mmsi: int) -> Optional[dict]:
    """Attempt to scrape vessel data from MarineTraffic public pages.

    May return 403 or Cloudflare challenge — returns None on any failure.
    Returns same dict shape as _scrape_shipxplorer.
    """
    raise NotImplementedError


def _scrape_itu(mmsi: int) -> Optional[dict]:
    """Attempt MMSI lookup via ITU MMSI database (form POST).

    Returns dict with vessel_name, call_sign, flag at minimum.
    Returns None on any failure.
    """
    raise NotImplementedError


def _download_photo(photo_url: str, mmsi: int, photos_dir: Path) -> Optional[str]:
    """Download photo_url to photos_dir/<mmsi>.jpg.

    Returns the local file path string on success, None on failure.
    """
    raise NotImplementedError


def _enrich_ship(mmsi: int, photos_dir: Path) -> Optional[dict]:
    """Try each scrape source in priority order. Return first successful result, or None."""
    for scraper in (_scrape_shipxplorer, _scrape_marinetraffic, _scrape_itu):
        try:
            result = scraper(mmsi)
            if result:
                return result
        except Exception:
            logger.debug("Scraper %s failed for MMSI %d", scraper.__name__, mmsi)
    return None


def main() -> None:
    """Service entry point. Loops forever enriching unenriched ships."""
    args = _build_parser().parse_args()
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    photos_dir = Path(args.photos_dir)
    photos_dir.mkdir(parents=True, exist_ok=True)

    conn = init_db(args.db)
    cfg = Config(conn)

    logger.info("Enrichment service starting.")

    while True:
        try:
            max_attempts = cfg.enrichment_max_attempts
            delay = cfg.enrichment_delay_sec
            mmsi_list = get_unenriched_ships(conn, max_attempts)

            if not mmsi_list:
                time.sleep(delay)
                continue

            for mmsi in mmsi_list:
                try:
                    data = _enrich_ship(mmsi, photos_dir)
                    if data:
                        if data.get("photo_url"):
                            local_path = _download_photo(data["photo_url"], mmsi, photos_dir)
                            if local_path:
                                data["photo_path"] = local_path
                        save_enrichment(conn, mmsi, data)
                        write_event(conn, mmsi, EventType.ENRICHED,
                                    f"New enrichment data for MMSI {mmsi}")
                        logger.info("Enriched MMSI %d from %s", mmsi, data.get("source"))
                    else:
                        # Increment fetch_attempts without saving data
                        save_enrichment(conn, mmsi, {})
                        logger.debug("No data found for MMSI %d", mmsi)
                except Exception:
                    logger.exception("Error enriching MMSI %d", mmsi)

                time.sleep(delay)

        except KeyboardInterrupt:
            logger.info("Enrichment service stopped by user.")
            sys.exit(0)
        except Exception:
            logger.exception("Enrichment service outer loop error")
            time.sleep(5)


if __name__ == "__main__":
    main()
```

- [x] **Step 9.2: Verify imports cleanly**

Note: `requests` and `beautifulsoup4` must be installed first. If not yet done, run:
`uv pip install requests beautifulsoup4` (they will be added to requirements.txt in Task 10).

Run: `uv run python -c "import services.enrichment_service; print('OK')"`
Expected: `OK`

- [x] **Step 9.3: Commit**

```
git add services/enrichment_service.py
git commit -m "feat: scaffold enrichment_service.py with scraper stubs and download stub"
```

---

## Chunk 5: Web Portal and Systemd Scaffolds

### Task 10: Scaffold services/web_service.py and templates

**Files:**
- Create: `services/web_service.py`
- Create: `templates/index.html`
- Create: `templates/ship.html`
- Create: `templates/events.html`
- Create: `templates/settings.html`
- Create: `static/photos/.gitkeep`

- [x] **Step 10.1: Create static/photos/.gitkeep**

Create `static/photos/.gitkeep` (empty file — ensures directory is tracked by git):

```
```

- [x] **Step 10.2: Create services/web_service.py scaffold**

Create `services/web_service.py`:

```python
"""Web Portal Service for ShipsAhoy.

Flask application providing a browser-based interface for browsing ships,
viewing event history, and adjusting system settings.

Routes:
    GET  /              Ship list sorted by last_seen, with distance and type
    GET  /ship/<mmsi>   Ship detail: all fields + enrichment + visit history + photo
    GET  /events        Recent 50 events
    GET  /settings      Settings form pre-populated from Config
    POST /settings      Save updated settings, redirect to GET /settings
    GET  /static/photos/<filename>  Cached ship photos

Flag display rule: show enrichment.flag when non-null, otherwise ships.flag.

Usage (via systemd or manually)::

    uv run python services/web_service.py [--db PATH] [--port PORT] [--verbose]
"""

import argparse
import logging
import os

from flask import Flask, render_template, request, redirect, url_for

from ships_ahoy.config import Config
from ships_ahoy.db import (
    init_db,
    get_ship,
    get_enrichment,
    get_ships_in_range,
    get_recent_events,
    get_visit_history,
)
from ships_ahoy.distance import haversine_km, bearing_degrees, bearing_to_cardinal

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = "ships.db"
DEFAULT_PORT = 5000

app = Flask(__name__, template_folder="../templates", static_folder="../static")

# Module-level connection — set in main() before app.run()
_conn = None
_cfg = None


def _get_conn():
    """Return the module-level DB connection. Set by main()."""
    if _conn is None:
        raise RuntimeError("Database connection not initialised. Call main() to start the service.")
    return _conn


def _get_cfg():
    """Return the module-level Config instance. Set by main()."""
    if _cfg is None:
        raise RuntimeError("Config not initialised. Call main() to start the service.")
    return _cfg


@app.route("/")
def index():
    """Ship list sorted by last_seen descending, with distance and type."""
    raise NotImplementedError


@app.route("/ship/<int:mmsi>")
def ship_detail(mmsi: int):
    """Ship detail page: all DB fields + enrichment + visit history + photo."""
    raise NotImplementedError


@app.route("/events")
def events():
    """Recent 50 events, newest first."""
    raise NotImplementedError


@app.route("/settings", methods=["GET"])
def settings_get():
    """Settings form pre-populated from the settings table."""
    raise NotImplementedError


@app.route("/settings", methods=["POST"])
def settings_post():
    """Save submitted settings values and redirect to GET /settings."""
    raise NotImplementedError


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="web_service",
        description="ShipsAhoy Web Portal",
    )
    parser.add_argument("--db", default=DEFAULT_DB_PATH, metavar="PATH")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--verbose", action="store_true")
    return parser


def main() -> None:
    """Service entry point. Initialises DB connection then starts Flask."""
    global _conn, _cfg
    args = _build_parser().parse_args()
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    _conn = init_db(args.db)
    _cfg = Config(_conn)

    logger.info("Web service starting on port %d", args.port)
    app.run(host="0.0.0.0", port=args.port, debug=False)


if __name__ == "__main__":
    main()
```

- [x] **Step 10.3: Create template stubs**

Create `templates/index.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>ShipsAhoy — Ships</title>
</head>
<body>
  <h1>ShipsAhoy</h1>
  <p>Ship list — not yet implemented.</p>
  <nav><a href="/events">Events</a> | <a href="/settings">Settings</a></nav>
</body>
</html>
```

Create `templates/ship.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>ShipsAhoy — Ship Detail</title>
</head>
<body>
  <h1>Ship Detail</h1>
  <p>Ship detail — not yet implemented.</p>
  <a href="/">Back</a>
</body>
</html>
```

Create `templates/events.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>ShipsAhoy — Events</title>
</head>
<body>
  <h1>Recent Events</h1>
  <p>Event log — not yet implemented.</p>
  <a href="/">Back</a>
</body>
</html>
```

Create `templates/settings.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>ShipsAhoy — Settings</title>
</head>
<body>
  <h1>Settings</h1>
  <p>Settings form — not yet implemented.</p>
  <a href="/">Back</a>
</body>
</html>
```

- [x] **Step 10.4: Verify web_service imports cleanly**

Run: `uv run python -c "import services.web_service; print('OK')"`
Expected: `OK` (requires `flask` installed — add to requirements.txt if missing)

- [x] **Step 10.5: Update requirements.txt**

Ensure `requirements.txt` contains:
```
pyais>=2.8.0
flask>=3.0
requests>=2.31
beautifulsoup4>=4.12
```

- [x] **Step 10.6: Sync dependencies**

Run: `uv sync` (or `uv pip install -r requirements.txt`)

- [x] **Step 10.7: Commit**

```
git add services/web_service.py templates/ static/photos/.gitkeep requirements.txt
git commit -m "feat: scaffold web_service.py, template stubs, and update requirements"
```

---

### Task 11: Create systemd unit files

**Files:**
- Create: `systemd/ships-ahoy-ais.service`
- Create: `systemd/ships-ahoy-ticker.service`
- Create: `systemd/ships-ahoy-enrichment.service`
- Create: `systemd/ships-ahoy-web.service`
- Create: `systemd/ships-ahoy.target`

- [x] **Step 11.1: Create ships-ahoy-ais.service**

Create `systemd/ships-ahoy-ais.service`:

```ini
[Unit]
Description=ShipsAhoy AIS Receiver
After=network.target

[Service]
User=pi
WorkingDirectory=/home/pi/ShipsAhoy
ExecStart=uv run python services/ais_service.py --db /home/pi/ShipsAhoy/ships.db
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=ships-ahoy.target
```

- [x] **Step 11.2: Create ships-ahoy-ticker.service**

Create `systemd/ships-ahoy-ticker.service`:

```ini
[Unit]
Description=ShipsAhoy LED Ticker
# After= is a startup ordering hint only, not BindsTo.
# The ticker can run independently once ships.db exists.
After=ships-ahoy-ais.service

[Service]
User=pi
WorkingDirectory=/home/pi/ShipsAhoy
ExecStart=uv run python services/ticker_service.py --db /home/pi/ShipsAhoy/ships.db
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=ships-ahoy.target
```

- [x] **Step 11.3: Create ships-ahoy-enrichment.service**

Create `systemd/ships-ahoy-enrichment.service`:

```ini
[Unit]
Description=ShipsAhoy Enrichment Service
After=network.target

[Service]
User=pi
WorkingDirectory=/home/pi/ShipsAhoy
ExecStart=uv run python services/enrichment_service.py --db /home/pi/ShipsAhoy/ships.db --photos-dir /home/pi/ShipsAhoy/static/photos
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=ships-ahoy.target
```

- [x] **Step 11.4: Create ships-ahoy-web.service**

Create `systemd/ships-ahoy-web.service`:

```ini
[Unit]
Description=ShipsAhoy Web Portal
After=network.target

[Service]
User=pi
WorkingDirectory=/home/pi/ShipsAhoy
ExecStart=uv run python services/web_service.py --db /home/pi/ShipsAhoy/ships.db --port 5000
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=ships-ahoy.target
```

- [x] **Step 11.5: Create ships-ahoy.target**

Create `systemd/ships-ahoy.target`:

```ini
[Unit]
Description=ShipsAhoy All Services
Wants=ships-ahoy-ais.service ships-ahoy-ticker.service ships-ahoy-enrichment.service ships-ahoy-web.service

[Install]
WantedBy=multi-user.target
```

- [x] **Step 11.6: Run full test suite one final time**

Run: `uv run pytest -v`
Expected: All tests PASS

- [x] **Step 11.7: Commit**

```
git add systemd/
git commit -m "feat: add systemd unit files for all four services and ships-ahoy.target"
```

---

## Post-Scaffolding Verification

After all tasks complete, verify the scaffold is wired correctly:

- [x] All new modules importable:
  ```
  uv run python -c "
  from ships_ahoy.db import init_db
  from ships_ahoy.config import Config
  from ships_ahoy.events import EventType, detect_events, format_ticker_message
  from ships_ahoy.distance import haversine_km, bearing_to_cardinal, is_noteworthy
  from ships_ahoy.matrix_driver import MatrixDriver, StubMatrixDriver, RGBMatrixDriver
  import services.ais_service
  import services.ticker_service
  import services.enrichment_service
  import services.web_service
  print('All imports OK')
  "
  ```
  Expected: `All imports OK`

- [x] All tests pass: `uv run pytest -v`

- [x] Summary commit if not already done:
  ```
  git log --oneline -10
  ```
  Confirm all scaffold commits are present.
