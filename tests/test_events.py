"""Tests for ships_ahoy.events."""
import sqlite3
import pytest
from ships_ahoy.db import init_db, upsert_ship, write_event, get_recent_events
from ships_ahoy.events import EventType, detect_events, format_ticker_message
from ships_ahoy.ship_tracker import ShipInfo


def make_ship(**kwargs):
    defaults = dict(mmsi=123456789, name="TEST VESSEL", status=0)
    defaults.update(kwargs)
    return ShipInfo(**defaults)


# ---------------------------------------------------------------------------
# EventType constants
# ---------------------------------------------------------------------------

def test_event_type_arrived():
    assert EventType.ARRIVED == "ARRIVED"


def test_event_type_departed():
    assert EventType.DEPARTED == "DEPARTED"


def test_event_type_status_change():
    assert EventType.STATUS_CHANGE == "STATUS_CHANGE"


def test_event_type_enriched():
    assert EventType.ENRICHED == "ENRICHED"


# ---------------------------------------------------------------------------
# detect_events
# ---------------------------------------------------------------------------

def test_detect_events_no_change_returns_empty():
    ship = make_ship(status=0)
    assert detect_events(ship, ship) == []


def test_detect_events_status_change_detected():
    old = make_ship(status=1)   # at anchor
    new = make_ship(status=0)   # underway
    events = detect_events(old, new)
    assert len(events) == 1
    event_type, detail = events[0]
    assert event_type == EventType.STATUS_CHANGE
    assert "TEST VESSEL" in detail


def test_detect_events_no_event_when_status_unchanged():
    old = make_ship(status=5)
    new = make_ship(status=5)
    assert detect_events(old, new) == []


def test_detect_events_no_event_when_status_was_none():
    # No old status to compare against — not a "change"
    old = make_ship(status=None)
    new = make_ship(status=0)
    assert detect_events(old, new) == []


def test_detect_events_returns_list_of_tuples():
    old = make_ship(status=1)
    new = make_ship(status=0)
    result = detect_events(old, new)
    assert isinstance(result, list)
    assert all(isinstance(e, tuple) and len(e) == 2 for e in result)


def test_detect_events_status_change_detail_uses_ascii_arrow():
    """ESP32 strips Unicode — detail must use ASCII -> not Unicode →."""
    old = make_ship(status=1)
    new = make_ship(status=0)
    _, detail = detect_events(old, new)[0]
    assert "->" in detail
    assert "→" not in detail


# ---------------------------------------------------------------------------
# format_ticker_message
# ---------------------------------------------------------------------------

@pytest.fixture
def db_rows():
    """Return (event_row, ship_row, enrichment_row) as real sqlite3.Row objects."""
    conn = init_db(":memory:")
    ship = ShipInfo(mmsi=987654321, name="ATLANTIC STAR", ship_type=70,
                    latitude=51.52, longitude=-0.09, status=0)
    upsert_ship(conn, ship)
    write_event(conn, 987654321, EventType.ARRIVED, "Ship arrived")
    event_row = get_recent_events(conn, limit=1)[0]
    ship_row = conn.execute("SELECT * FROM ships WHERE mmsi=987654321").fetchone()
    return event_row, ship_row, None


def test_format_ticker_message_returns_string(db_rows):
    event_row, ship_row, enrichment_row = db_rows
    result = format_ticker_message(event_row, ship_row, enrichment_row)
    assert isinstance(result, str)


def test_format_ticker_message_contains_ship_name(db_rows):
    event_row, ship_row, enrichment_row = db_rows
    result = format_ticker_message(event_row, ship_row, enrichment_row)
    assert "ATLANTIC STAR" in result


def test_format_ticker_message_contains_event_type(db_rows):
    event_row, ship_row, enrichment_row = db_rows
    result = format_ticker_message(event_row, ship_row, enrichment_row)
    result_lower = result.lower()
    # First-visit ARRIVED uses "first sighting"; re-arrival uses "arrived" or "returns"
    assert "arrived" in result_lower or "first sighting" in result_lower or "returns" in result_lower


def test_format_ticker_message_is_single_line(db_rows):
    event_row, ship_row, enrichment_row = db_rows
    result = format_ticker_message(event_row, ship_row, enrichment_row)
    assert "\n" not in result


def test_format_ticker_message_first_sighting():
    """visit_count == 0 → 'First sighting: …'"""
    conn = init_db(":memory:")
    ship = ShipInfo(mmsi=200000001, name="MV FIRST", ship_type=70)
    upsert_ship(conn, ship)
    write_event(conn, 200000001, EventType.ARRIVED, "ship arrived")
    event_row = get_recent_events(conn, limit=1)[0]
    ship_row = conn.execute("SELECT * FROM ships WHERE mmsi=200000001").fetchone()
    result = format_ticker_message(event_row, ship_row, None)
    assert result is not None
    assert "First sighting" in result
    assert "MV FIRST" in result
    assert "cargo" in result


def test_format_ticker_message_returning_ship_with_days():
    """visit_count > 1 + last_departed > 1 day → 'returns — away N days'"""
    import datetime as _dt
    conn = init_db(":memory:")
    ship = ShipInfo(mmsi=200000002, name="MV RETURNER", ship_type=80)
    upsert_ship(conn, ship)
    conn.execute("UPDATE ships SET visit_count=3 WHERE mmsi=200000002")
    conn.commit()
    write_event(conn, 200000002, EventType.ARRIVED, "ship arrived")
    event_row = get_recent_events(conn, limit=1)[0]
    ship_row = conn.execute("SELECT * FROM ships WHERE mmsi=200000002").fetchone()
    three_days_ago = (_dt.datetime.now() - _dt.timedelta(days=3)).isoformat()
    result = format_ticker_message(event_row, ship_row, None, last_departed_iso=three_days_ago)
    assert result is not None
    assert "returns" in result
    assert "3 days" in result


def test_format_ticker_message_returning_ship_recent():
    """visit_count > 1 + last_departed < 1 day → 'has arrived — visit N'"""
    import datetime as _dt
    conn = init_db(":memory:")
    ship = ShipInfo(mmsi=200000003, name="MV RECENT", ship_type=70)
    upsert_ship(conn, ship)
    conn.execute("UPDATE ships SET visit_count=2 WHERE mmsi=200000003")
    conn.commit()
    write_event(conn, 200000003, EventType.ARRIVED, "ship arrived")
    event_row = get_recent_events(conn, limit=1)[0]
    ship_row = conn.execute("SELECT * FROM ships WHERE mmsi=200000003").fetchone()
    one_hour_ago = (_dt.datetime.now() - _dt.timedelta(hours=1)).isoformat()
    result = format_ticker_message(event_row, ship_row, None, last_departed_iso=one_hour_ago)
    assert result is not None
    assert "has arrived" in result
    assert "visit 2" in result


def test_format_ticker_message_departed():
    conn = init_db(":memory:")
    ship = ShipInfo(mmsi=200000004, name="MV GONE", ship_type=70)
    upsert_ship(conn, ship)
    write_event(conn, 200000004, EventType.DEPARTED, "Ship departed")
    event_row = get_recent_events(conn, limit=1)[0]
    ship_row = conn.execute("SELECT * FROM ships WHERE mmsi=200000004").fetchone()
    result = format_ticker_message(event_row, ship_row, None)
    assert result is not None
    assert "has departed" in result
    assert "MV GONE" in result


def test_format_ticker_message_status_change():
    conn = init_db(":memory:")
    ship = ShipInfo(mmsi=200000005, name="MV CHANGE", ship_type=70)
    upsert_ship(conn, ship)
    write_event(conn, 200000005, EventType.STATUS_CHANGE, "MV CHANGE status: underway → moored")
    event_row = get_recent_events(conn, limit=1)[0]
    ship_row = conn.execute("SELECT * FROM ships WHERE mmsi=200000005").fetchone()
    result = format_ticker_message(event_row, ship_row, None)
    assert result is not None
    assert "status:" in result
    assert "underway" in result
    assert "moored" in result


def test_format_ticker_message_enriched_returns_none():
    conn = init_db(":memory:")
    ship = ShipInfo(mmsi=200000006, name="MV ENRICHED")
    upsert_ship(conn, ship)
    write_event(conn, 200000006, EventType.ENRICHED, "enriched")
    event_row = get_recent_events(conn, limit=1)[0]
    ship_row = conn.execute("SELECT * FROM ships WHERE mmsi=200000006").fetchone()
    result = format_ticker_message(event_row, ship_row, None)
    assert result is None


def test_format_ticker_message_uses_enrichment_name_when_available():
    conn = init_db(":memory:")
    ship = ShipInfo(mmsi=111222333, name="AIS NAME")
    upsert_ship(conn, ship)
    write_event(conn, 111222333, EventType.ARRIVED, "Ship arrived")
    conn.execute(
        "INSERT INTO enrichment (mmsi, vessel_name) VALUES (?, ?)",
        (111222333, "ENRICHED NAME"),
    )
    conn.commit()
    event_row = get_recent_events(conn, limit=1)[0]
    ship_row = conn.execute("SELECT * FROM ships WHERE mmsi=111222333").fetchone()
    enrichment_row = conn.execute("SELECT * FROM enrichment WHERE mmsi=111222333").fetchone()
    result = format_ticker_message(event_row, ship_row, enrichment_row)
    assert "ENRICHED NAME" in result
