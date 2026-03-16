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
