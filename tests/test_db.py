"""Tests for ships_ahoy.db.

All tests use an in-memory SQLite database (or tmp_path for WAL mode).
"""
import sqlite3
import time
import pytest
from ships_ahoy.db import (
    init_db,
    upsert_ship,
    get_ship,
    get_enrichment,
    get_unenriched_ships,
    save_enrichment,
    increment_fetch_attempts,
    write_event,
    get_pending_events,
    get_recent_events,
    mark_event_displayed,
    batch_mark_events_displayed,
    get_ships_in_range,
    get_all_ships,
    count_ships,
    get_stale_mmsis,
    get_visit_history,
    record_visit,
    close_visit,
    mark_ship_departed,
)
from ships_ahoy.events import EventType
from ships_ahoy.ship_tracker import ShipInfo


@pytest.fixture
def conn():
    return init_db(":memory:")


# ---------------------------------------------------------------------------
# init_db
# ---------------------------------------------------------------------------

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


def test_init_db_seeds_default_settings(conn):
    row = conn.execute("SELECT value FROM settings WHERE key='distance_km'").fetchone()
    assert row is not None
    assert row[0] == "50"


# ---------------------------------------------------------------------------
# upsert_ship
# ---------------------------------------------------------------------------

def test_upsert_ship_inserts_new_row(conn):
    ship = ShipInfo(mmsi=123456789, name="CARGO KING")
    upsert_ship(conn, ship)
    row = conn.execute("SELECT name FROM ships WHERE mmsi=123456789").fetchone()
    assert row["name"] == "CARGO KING"


def test_upsert_ship_updates_existing_row(conn):
    ship = ShipInfo(mmsi=123456789, name="OLD NAME")
    upsert_ship(conn, ship)
    ship.name = "NEW NAME"
    upsert_ship(conn, ship)
    row = conn.execute("SELECT name FROM ships WHERE mmsi=123456789").fetchone()
    assert row["name"] == "NEW NAME"


def test_upsert_ship_sets_first_seen_once(conn):
    ship = ShipInfo(mmsi=111111111, name="FIRST")
    upsert_ship(conn, ship)
    first = conn.execute("SELECT first_seen FROM ships WHERE mmsi=111111111").fetchone()["first_seen"]
    time.sleep(0.01)
    upsert_ship(conn, ship)
    second = conn.execute("SELECT first_seen FROM ships WHERE mmsi=111111111").fetchone()["first_seen"]
    assert first == second


def test_upsert_ship_updates_last_seen(conn):
    ship = ShipInfo(mmsi=222222222)
    upsert_ship(conn, ship)
    t1 = conn.execute("SELECT last_seen FROM ships WHERE mmsi=222222222").fetchone()["last_seen"]
    time.sleep(0.01)
    upsert_ship(conn, ship)
    t2 = conn.execute("SELECT last_seen FROM ships WHERE mmsi=222222222").fetchone()["last_seen"]
    assert t2 >= t1


def test_upsert_ship_writes_position(conn):
    ship = ShipInfo(mmsi=333333333, latitude=51.5, longitude=-0.1)
    upsert_ship(conn, ship)
    row = conn.execute("SELECT latitude, longitude FROM ships WHERE mmsi=333333333").fetchone()
    assert abs(row["latitude"] - 51.5) < 0.0001
    assert abs(row["longitude"] - (-0.1)) < 0.0001


# ---------------------------------------------------------------------------
# get_ship
# ---------------------------------------------------------------------------

def test_get_ship_returns_none_for_unknown(conn):
    assert get_ship(conn, 999999999) is None


def test_get_ship_returns_row_after_upsert(conn):
    ship = ShipInfo(mmsi=444444444, name="FINDER")
    upsert_ship(conn, ship)
    row = get_ship(conn, 444444444)
    assert row is not None
    assert row["name"] == "FINDER"


# ---------------------------------------------------------------------------
# write_event / get_pending_events / get_recent_events / mark_event_displayed
# ---------------------------------------------------------------------------

def test_write_event_inserts_row(conn):
    ship = ShipInfo(mmsi=555555555)
    upsert_ship(conn, ship)
    write_event(conn, 555555555, EventType.ARRIVED, "Ship arrived")
    row = conn.execute("SELECT * FROM events WHERE mmsi=555555555").fetchone()
    assert row is not None
    assert row["event_type"] == EventType.ARRIVED
    assert row["detail"] == "Ship arrived"
    assert row["displayed_at"] is None


def test_get_pending_events_returns_undisplayed(conn):
    ship = ShipInfo(mmsi=666666666)
    upsert_ship(conn, ship)
    write_event(conn, 666666666, EventType.ARRIVED, "detail")
    events = get_pending_events(conn)
    assert len(events) == 1
    assert events[0]["mmsi"] == 666666666


def test_get_pending_events_excludes_displayed(conn):
    ship = ShipInfo(mmsi=777777777)
    upsert_ship(conn, ship)
    write_event(conn, 777777777, EventType.ARRIVED, "detail")
    event_id = conn.execute("SELECT id FROM events WHERE mmsi=777777777").fetchone()["id"]
    mark_event_displayed(conn, event_id)
    assert get_pending_events(conn) == []


def test_get_pending_events_ordered_by_created_at(conn):
    for mmsi in [100000001, 100000002, 100000003]:
        upsert_ship(conn, ShipInfo(mmsi=mmsi))
        write_event(conn, mmsi, EventType.ARRIVED, f"ship {mmsi}")
    events = get_pending_events(conn)
    mmsis = [e["mmsi"] for e in events]
    assert mmsis == sorted(mmsis)


def test_mark_event_displayed_sets_timestamp(conn):
    ship = ShipInfo(mmsi=888888888)
    upsert_ship(conn, ship)
    write_event(conn, 888888888, EventType.ARRIVED, "detail")
    event_id = conn.execute("SELECT id FROM events WHERE mmsi=888888888").fetchone()["id"]
    mark_event_displayed(conn, event_id)
    row = conn.execute("SELECT displayed_at FROM events WHERE id=?", (event_id,)).fetchone()
    assert row["displayed_at"] is not None


def test_get_recent_events_returns_newest_first(conn):
    for mmsi in [200000001, 200000002, 200000003]:
        upsert_ship(conn, ShipInfo(mmsi=mmsi))
        write_event(conn, mmsi, EventType.ARRIVED, f"ship {mmsi}")
    events = get_recent_events(conn)
    ids = [e["id"] for e in events]
    assert ids == sorted(ids, reverse=True)


def test_get_recent_events_respects_limit(conn):
    for mmsi in range(300000001, 300000011):  # 10 ships
        upsert_ship(conn, ShipInfo(mmsi=mmsi))
        write_event(conn, mmsi, EventType.ARRIVED, "detail")
    events = get_recent_events(conn, limit=5)
    assert len(events) == 5


# ---------------------------------------------------------------------------
# get_enrichment / save_enrichment / get_unenriched_ships
# ---------------------------------------------------------------------------

def test_get_enrichment_returns_none_for_unknown(conn):
    assert get_enrichment(conn, 999999999) is None


def test_save_enrichment_inserts_row(conn):
    ship = ShipInfo(mmsi=400000001)
    upsert_ship(conn, ship)
    save_enrichment(conn, 400000001, {"vessel_name": "BIG BOAT", "flag": "NO"})
    row = get_enrichment(conn, 400000001)
    assert row is not None
    assert row["vessel_name"] == "BIG BOAT"
    assert row["flag"] == "NO"


def test_save_enrichment_marks_ship_enriched(conn):
    ship = ShipInfo(mmsi=400000002)
    upsert_ship(conn, ship)
    save_enrichment(conn, 400000002, {"vessel_name": "ENRICHED"})
    row = conn.execute("SELECT enriched FROM ships WHERE mmsi=400000002").fetchone()
    assert row["enriched"]


def test_save_enrichment_updates_on_second_call(conn):
    ship = ShipInfo(mmsi=400000003)
    upsert_ship(conn, ship)
    save_enrichment(conn, 400000003, {"vessel_name": "FIRST"})
    save_enrichment(conn, 400000003, {"vessel_name": "UPDATED"})
    row = get_enrichment(conn, 400000003)
    assert row["vessel_name"] == "UPDATED"


def test_get_unenriched_ships_returns_unenriched(conn):
    for mmsi in [500000001, 500000002]:
        upsert_ship(conn, ShipInfo(mmsi=mmsi))
    result = get_unenriched_ships(conn, max_attempts=3)
    assert 500000001 in result
    assert 500000002 in result


def test_get_unenriched_ships_excludes_enriched(conn):
    ship = ShipInfo(mmsi=500000003)
    upsert_ship(conn, ship)
    save_enrichment(conn, 500000003, {"vessel_name": "DONE"})
    result = get_unenriched_ships(conn, max_attempts=3)
    assert 500000003 not in result


def test_get_unenriched_ships_excludes_max_attempts_reached(conn):
    ship = ShipInfo(mmsi=500000004)
    upsert_ship(conn, ship)
    conn.execute(
        "INSERT INTO enrichment (mmsi, fetch_attempts) VALUES (?, ?)", (500000004, 3)
    )
    conn.commit()
    result = get_unenriched_ships(conn, max_attempts=3)
    assert 500000004 not in result


# ---------------------------------------------------------------------------
# record_visit / close_visit / get_visit_history
# ---------------------------------------------------------------------------

def test_record_visit_creates_open_visit(conn):
    ship = ShipInfo(mmsi=600000001)
    upsert_ship(conn, ship)
    record_visit(conn, 600000001)
    row = conn.execute(
        "SELECT * FROM ship_visits WHERE mmsi=600000001"
    ).fetchone()
    assert row is not None
    assert row["departed_at"] is None


def test_record_visit_increments_visit_count(conn):
    ship = ShipInfo(mmsi=600000002)
    upsert_ship(conn, ship)
    record_visit(conn, 600000002)
    record_visit(conn, 600000002)
    row = conn.execute("SELECT visit_count FROM ships WHERE mmsi=600000002").fetchone()
    assert row["visit_count"] == 2


def test_close_visit_sets_departed_at(conn):
    ship = ShipInfo(mmsi=600000003)
    upsert_ship(conn, ship)
    record_visit(conn, 600000003)
    close_visit(conn, 600000003)
    row = conn.execute(
        "SELECT departed_at FROM ship_visits WHERE mmsi=600000003"
    ).fetchone()
    assert row["departed_at"] is not None


def test_close_visit_only_closes_most_recent(conn):
    ship = ShipInfo(mmsi=600000004)
    upsert_ship(conn, ship)
    record_visit(conn, 600000004)
    close_visit(conn, 600000004)
    record_visit(conn, 600000004)  # second visit still open
    rows = conn.execute(
        "SELECT departed_at FROM ship_visits WHERE mmsi=600000004 ORDER BY id"
    ).fetchall()
    assert rows[0]["departed_at"] is not None
    assert rows[1]["departed_at"] is None


def test_get_visit_history_returns_newest_first(conn):
    ship = ShipInfo(mmsi=600000005)
    upsert_ship(conn, ship)
    record_visit(conn, 600000005)
    close_visit(conn, 600000005)
    record_visit(conn, 600000005)
    rows = get_visit_history(conn, 600000005)
    assert len(rows) == 2
    ids = [r["id"] for r in rows]
    assert ids == sorted(ids, reverse=True)


def test_get_visit_history_empty_for_unknown(conn):
    assert get_visit_history(conn, 999999998) == []


# ---------------------------------------------------------------------------
# mark_ship_departed
# ---------------------------------------------------------------------------

def test_mark_ship_departed_writes_departed_event(conn):
    ship = ShipInfo(mmsi=700000001)
    upsert_ship(conn, ship)
    record_visit(conn, 700000001)
    mark_ship_departed(conn, 700000001)
    row = conn.execute(
        "SELECT event_type FROM events WHERE mmsi=700000001"
    ).fetchone()
    assert row["event_type"] == EventType.DEPARTED


def test_mark_ship_departed_closes_visit(conn):
    ship = ShipInfo(mmsi=700000002)
    upsert_ship(conn, ship)
    record_visit(conn, 700000002)
    mark_ship_departed(conn, 700000002)
    row = conn.execute(
        "SELECT departed_at FROM ship_visits WHERE mmsi=700000002"
    ).fetchone()
    assert row["departed_at"] is not None


def test_mark_ship_departed_preserves_ship_row(conn):
    ship = ShipInfo(mmsi=700000003, name="PERSISTENT")
    upsert_ship(conn, ship)
    record_visit(conn, 700000003)
    mark_ship_departed(conn, 700000003)
    row = get_ship(conn, 700000003)
    assert row is not None
    assert row["name"] == "PERSISTENT"


# ---------------------------------------------------------------------------
# get_ships_in_range
# ---------------------------------------------------------------------------

def test_get_ships_in_range_returns_nearby_ships(conn):
    # Ship at ~2.2 km from home
    ship = ShipInfo(mmsi=800000001, latitude=51.502, longitude=-0.1)
    upsert_ship(conn, ship)
    result = get_ships_in_range(conn, home_lat=51.5, home_lon=-0.1, km=50.0)
    mmsis = [r["mmsi"] for r in result]
    assert 800000001 in mmsis


def test_get_ships_in_range_excludes_distant_ships(conn):
    # Ship ~560 km away (Paris)
    ship = ShipInfo(mmsi=800000002, latitude=48.85, longitude=2.35)
    upsert_ship(conn, ship)
    result = get_ships_in_range(conn, home_lat=51.5, home_lon=-0.1, km=50.0)
    mmsis = [r["mmsi"] for r in result]
    assert 800000002 not in mmsis


def test_get_ships_in_range_excludes_ships_without_position(conn):
    ship = ShipInfo(mmsi=800000003)  # no lat/lon
    upsert_ship(conn, ship)
    result = get_ships_in_range(conn, home_lat=51.5, home_lon=-0.1, km=50.0)
    mmsis = [r["mmsi"] for r in result]
    assert 800000003 not in mmsis


# ---------------------------------------------------------------------------
# Fix 1: mark_ship_departed atomicity
# ---------------------------------------------------------------------------

def test_mark_ship_departed_both_effects_visible_together(conn):
    """DEPARTED event and closed visit must both be committed by the same call.

    After mark_ship_departed returns, both side effects are present.
    If they were committed separately, a crash between the two commits would
    leave one but not the other — this test verifies the happy path;
    the structural fix (single conn.commit() in mark_ship_departed) prevents the
    partial-commit failure mode.
    """
    ship = ShipInfo(mmsi=900000001, name="ATOMIC TEST")
    upsert_ship(conn, ship)
    record_visit(conn, 900000001)
    mark_ship_departed(conn, 900000001)

    event = conn.execute(
        "SELECT id FROM events WHERE mmsi=900000001 AND event_type='DEPARTED'"
    ).fetchone()
    visit = conn.execute(
        "SELECT departed_at FROM ship_visits WHERE mmsi=900000001"
    ).fetchone()

    assert event is not None, "DEPARTED event must be present"
    assert visit["departed_at"] is not None, "visit must be closed"


# ---------------------------------------------------------------------------
# Fix 3: increment_fetch_attempts
# ---------------------------------------------------------------------------

def test_increment_fetch_attempts_creates_row_on_first_call(conn):
    ship = ShipInfo(mmsi=910000001)
    upsert_ship(conn, ship)
    increment_fetch_attempts(conn, 910000001)
    row = conn.execute(
        "SELECT fetch_attempts FROM enrichment WHERE mmsi=910000001"
    ).fetchone()
    assert row is not None
    assert row["fetch_attempts"] == 1


def test_increment_fetch_attempts_increments_on_subsequent_calls(conn):
    ship = ShipInfo(mmsi=910000002)
    upsert_ship(conn, ship)
    increment_fetch_attempts(conn, 910000002)
    increment_fetch_attempts(conn, 910000002)
    row = conn.execute(
        "SELECT fetch_attempts FROM enrichment WHERE mmsi=910000002"
    ).fetchone()
    assert row["fetch_attempts"] == 2


def test_increment_fetch_attempts_does_not_set_enriched(conn):
    ship = ShipInfo(mmsi=910000003)
    upsert_ship(conn, ship)
    increment_fetch_attempts(conn, 910000003)
    row = conn.execute(
        "SELECT enriched FROM ships WHERE mmsi=910000003"
    ).fetchone()
    assert not row["enriched"]


def test_get_unenriched_ships_excludes_after_max_attempts_via_increment(conn):
    """Ships that fail max_attempts times via increment_fetch_attempts are excluded."""
    ship = ShipInfo(mmsi=910000004)
    upsert_ship(conn, ship)
    for _ in range(3):
        increment_fetch_attempts(conn, 910000004)
    result = get_unenriched_ships(conn, max_attempts=3)
    assert 910000004 not in result


def test_failed_enrichment_does_not_mark_ship_enriched(conn):
    """Calling increment_fetch_attempts instead of save_enrichment({}) on failure
    leaves enriched=FALSE so the ship remains eligible for future attempts."""
    ship = ShipInfo(mmsi=910000005)
    upsert_ship(conn, ship)
    increment_fetch_attempts(conn, 910000005)
    increment_fetch_attempts(conn, 910000005)
    result = get_unenriched_ships(conn, max_attempts=3)
    assert 910000005 in result  # still eligible (only 2 of 3 attempts used)


# ---------------------------------------------------------------------------
# get_all_ships / count_ships
# ---------------------------------------------------------------------------

def test_get_all_ships_returns_all_rows(conn):
    for mmsi in [920000001, 920000002, 920000003]:
        upsert_ship(conn, ShipInfo(mmsi=mmsi))
    rows = get_all_ships(conn)
    mmsis = [r["mmsi"] for r in rows]
    assert 920000001 in mmsis
    assert 920000002 in mmsis
    assert 920000003 in mmsis


def test_get_all_ships_ordered_by_last_seen_desc(conn):
    for mmsi in [920000004, 920000005]:
        upsert_ship(conn, ShipInfo(mmsi=mmsi))
    rows = get_all_ships(conn)
    last_seens = [r["last_seen"] for r in rows]
    assert last_seens == sorted(last_seens, reverse=True)


def test_count_ships_returns_zero_for_empty_db(conn):
    assert count_ships(conn) == 0


def test_count_ships_returns_correct_count(conn):
    for mmsi in [930000001, 930000002]:
        upsert_ship(conn, ShipInfo(mmsi=mmsi))
    assert count_ships(conn) == 2


# ---------------------------------------------------------------------------
# get_stale_mmsis
# ---------------------------------------------------------------------------

def test_get_stale_mmsis_returns_ships_with_open_visit_past_threshold(conn):
    import time
    ship = ShipInfo(mmsi=940000001)
    upsert_ship(conn, ship)
    record_visit(conn, 940000001)
    # Use a future threshold so this ship is "stale"
    future = "9999-01-01T00:00:00"
    result = get_stale_mmsis(conn, future)
    assert 940000001 in result


def test_get_stale_mmsis_excludes_ships_with_closed_visit(conn):
    ship = ShipInfo(mmsi=940000002)
    upsert_ship(conn, ship)
    record_visit(conn, 940000002)
    close_visit(conn, 940000002)
    future = "9999-01-01T00:00:00"
    result = get_stale_mmsis(conn, future)
    assert 940000002 not in result


# ---------------------------------------------------------------------------
# batch_mark_events_displayed
# ---------------------------------------------------------------------------

def test_batch_mark_events_displayed_marks_all(conn):
    for mmsi in [950000001, 950000002]:
        upsert_ship(conn, ShipInfo(mmsi=mmsi))
        write_event(conn, mmsi, EventType.ARRIVED, "detail")
    event_ids = [r["id"] for r in conn.execute("SELECT id FROM events").fetchall()]
    batch_mark_events_displayed(conn, event_ids)
    assert get_pending_events(conn) == []


def test_batch_mark_events_displayed_no_op_on_empty_list(conn):
    # Should not raise
    batch_mark_events_displayed(conn, [])
