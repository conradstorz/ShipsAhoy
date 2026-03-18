"""Integration tests for services/ais_service.py.

Tests call internal functions directly against a real :memory: SQLite database.
External I/O (sockets, time.sleep) is mocked.
"""
import socket
from datetime import datetime, timedelta
from unittest import mock

import pytest

import services.ais_service as svc
from ships_ahoy.config import Config
from ships_ahoy.db import init_db, get_ship, record_visit
from ships_ahoy.events import EventType
from ships_ahoy.ship_tracker import ShipInfo, ShipTracker


@pytest.fixture
def conn():
    """In-memory DB with home location set to London (51.5, 0.0)."""
    c = init_db(":memory:")
    c.execute("UPDATE settings SET value='51.5' WHERE key='home_lat'")
    c.execute("UPDATE settings SET value='0.0' WHERE key='home_lon'")
    c.commit()
    return c


@pytest.fixture
def cfg(conn):
    return Config(conn)


@pytest.fixture(autouse=True)
def reset_tracker():
    """Replace the module-level tracker with a fresh one before each test."""
    svc._tracker = ShipTracker()


def _make_ship(mmsi=123456789, lat=51.5, lon=0.0, status=0, name="MV Test"):
    """Helper: return a ShipInfo near London."""
    return ShipInfo(
        mmsi=mmsi,
        name=name,
        latitude=lat,
        longitude=lon,
        status=status,
        last_seen=datetime.now(),
    )


def test_new_ship_writes_arrived_event(conn, cfg):
    """New ship within home range -> ARRIVED event + open visit recorded."""
    ship = _make_ship()
    msg = mock.MagicMock()
    with mock.patch.object(svc._tracker, "update", return_value=ship):
        svc._process_message(conn, msg, cfg)

    events = conn.execute("SELECT * FROM events").fetchall()
    assert len(events) == 1
    assert events[0]["event_type"] == EventType.ARRIVED

    visits = conn.execute("SELECT * FROM ship_visits").fetchall()
    assert len(visits) == 1
    assert visits[0]["departed_at"] is None


def test_new_ship_outside_range_no_event(conn, cfg):
    """Ship far from home (equator) -> no event, no visit."""
    ship = _make_ship(lat=0.0, lon=0.0)
    msg = mock.MagicMock()
    with mock.patch.object(svc._tracker, "update", return_value=ship):
        svc._process_message(conn, msg, cfg)

    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM ship_visits").fetchone()[0] == 0


def test_status_change_writes_event(conn, cfg):
    """Existing ship changes nav status -> STATUS_CHANGE event written."""
    now = datetime.now().isoformat()
    conn.execute(
        "INSERT INTO ships (mmsi, name, status, last_seen, first_seen)"
        " VALUES (?, ?, ?, ?, ?)",
        (123456789, "MV Test", 0, now, now),
    )
    conn.commit()

    new_ship = _make_ship(status=5)  # 5 = moored
    msg = mock.MagicMock()
    with mock.patch.object(svc._tracker, "update", return_value=new_ship):
        svc._process_message(conn, msg, cfg)

    events = conn.execute("SELECT * FROM events").fetchall()
    assert len(events) == 1
    assert events[0]["event_type"] == EventType.STATUS_CHANGE


def test_no_home_location_treats_all_noteworthy():
    """When home_lat/lon are NULL, every ship gets events regardless of position."""
    # Use a fresh connection — do NOT set home_lat/lon so they stay NULL
    conn = init_db(":memory:")
    cfg = Config(conn)
    ship = _make_ship(lat=0.0, lon=0.0)  # far from London, but home is unset
    msg = mock.MagicMock()
    with mock.patch.object(svc._tracker, "update", return_value=ship):
        svc._process_message(conn, msg, cfg)

    events = conn.execute("SELECT * FROM events").fetchall()
    assert len(events) == 1
    assert events[0]["event_type"] == EventType.ARRIVED


def test_message_returns_none_is_noop(conn, cfg):
    """Tracker returning None (unrecognised message type) -> no DB writes."""
    msg = mock.MagicMock()
    with mock.patch.object(svc._tracker, "update", return_value=None):
        svc._process_message(conn, msg, cfg)

    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM ships").fetchone()[0] == 0


def test_run_stale_sweep_marks_departed(conn, cfg):
    """Ship with open visit last seen 2 hours ago -> DEPARTED event written."""
    old_time = (datetime.now() - timedelta(hours=2)).isoformat()
    conn.execute(
        "INSERT INTO ships (mmsi, name, last_seen, first_seen) VALUES (?, ?, ?, ?)",
        (111222333, "Stale Ship", old_time, old_time),
    )
    conn.execute(
        "INSERT INTO ship_visits (mmsi, arrived_at) VALUES (?, ?)",
        (111222333, old_time),
    )
    conn.commit()

    svc._run_stale_sweep(conn, cfg)

    events = conn.execute(
        "SELECT * FROM events WHERE mmsi=111222333"
    ).fetchall()
    assert len(events) == 1
    assert events[0]["event_type"] == EventType.DEPARTED

    visit = conn.execute(
        "SELECT * FROM ship_visits WHERE mmsi=111222333"
    ).fetchone()
    assert visit["departed_at"] is not None


def test_run_stale_sweep_skips_fresh_ships(conn, cfg):
    """Ship last seen moments ago -> no DEPARTED event."""
    now = datetime.now().isoformat()
    conn.execute(
        "INSERT INTO ships (mmsi, name, last_seen, first_seen) VALUES (?, ?, ?, ?)",
        (999888777, "Fresh Ship", now, now),
    )
    conn.execute(
        "INSERT INTO ship_visits (mmsi, arrived_at) VALUES (?, ?)",
        (999888777, now),
    )
    conn.commit()

    svc._run_stale_sweep(conn, cfg)

    assert conn.execute(
        "SELECT COUNT(*) FROM events WHERE mmsi=999888777"
    ).fetchone()[0] == 0


def test_connect_with_backoff_succeeds(monkeypatch):
    """Successful TCP check -> returns an AISReceiver instance."""
    mock_receiver = mock.MagicMock()
    monkeypatch.setattr("socket.create_connection", lambda *a, **kw: mock.MagicMock())
    monkeypatch.setattr("services.ais_service.AISReceiver", lambda **kw: mock_receiver)

    result = svc._connect_with_backoff("localhost", 10110, use_udp=False)
    assert result is mock_receiver


def test_connect_with_backoff_retries(monkeypatch):
    """First connection attempt fails, second succeeds -> time.sleep called once."""
    call_count = {"n": 0}

    def flaky_connect(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise ConnectionRefusedError("refused")
        return mock.MagicMock()

    sleep_calls = []
    monkeypatch.setattr("socket.create_connection", flaky_connect)
    monkeypatch.setattr("services.ais_service.AISReceiver", lambda **kw: mock.MagicMock())
    monkeypatch.setattr("services.ais_service.time.sleep", lambda s: sleep_calls.append(s))

    svc._connect_with_backoff("localhost", 10110, use_udp=False)

    assert len(sleep_calls) == 1
    assert sleep_calls[0] == 1  # first backoff delay is 1 second
