import sys
from unittest import mock
import importlib.util
from pathlib import Path
import pytest

# Load ticker_service with matrix_driver mocked to prevent hardware import errors
_ts_spec = importlib.util.spec_from_file_location(
    "ticker_service_full", "services/ticker_service.py"
)
_ts_mod = importlib.util.module_from_spec(_ts_spec)
with mock.patch.dict(sys.modules, {"ships_ahoy.matrix_driver": mock.MagicMock()}):
    _ts_spec.loader.exec_module(_ts_mod)

_display_event = _ts_mod._display_event
_show_idle = _ts_mod._show_idle
_handle_overflow = _ts_mod._handle_overflow


def _import_build_parser():
    # Import lazily to avoid import-time driver selection running
    import importlib
    spec = importlib.util.spec_from_file_location(
        "ticker_service",
        "services/ticker_service.py",
    )
    mod = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, {"ships_ahoy.matrix_driver": mock.MagicMock()}):
        spec.loader.exec_module(mod)
    return mod._build_parser


from datetime import datetime
from ships_ahoy.db import init_db, upsert_ship, write_event
from ships_ahoy.config import Config
from ships_ahoy.ship_tracker import ShipInfo


@pytest.fixture
def conn():
    c = init_db(":memory:")
    c.execute("UPDATE settings SET value='51.5' WHERE key='home_lat'")
    c.execute("UPDATE settings SET value='0.0' WHERE key='home_lon'")
    c.commit()
    return c


@pytest.fixture
def cfg(conn):
    return Config(conn)


@pytest.fixture
def driver():
    return mock.MagicMock()


def test_build_parser_has_esp32_port_arg():
    build_parser = _import_build_parser()
    parser = build_parser()
    args = parser.parse_args(["--esp32-port", "/dev/ttyAMA0"])
    assert args.esp32_port == "/dev/ttyAMA0"

def test_build_parser_esp32_port_defaults_to_none():
    build_parser = _import_build_parser()
    parser = build_parser()
    args = parser.parse_args([])
    assert args.esp32_port is None


def test_display_event_scrolls_and_marks_displayed(conn, cfg, driver):
    """Event with matching ship -> driver.scroll_text called, event marked displayed."""
    now = datetime.now().isoformat()
    conn.execute(
        "INSERT INTO ships (mmsi, name, last_seen, first_seen) VALUES (?,?,?,?)",
        (111222333, "MV Ticker", now, now),
    )
    conn.execute(
        "INSERT INTO events (mmsi, event_type, detail, created_at) VALUES (?,?,?,?)",
        (111222333, "ARRIVED", "MV Ticker arrived", now),
    )
    conn.commit()

    event_row = conn.execute("SELECT * FROM events WHERE mmsi=111222333").fetchone()
    _display_event(conn, event_row, driver, cfg)

    driver.scroll_text.assert_called_once()
    updated = conn.execute(
        "SELECT displayed_at FROM events WHERE id=?", (event_row["id"],)
    ).fetchone()
    assert updated["displayed_at"] is not None


def test_display_event_skips_missing_ship(conn, cfg, driver):
    """Event for unknown MMSI -> no scroll, event still marked displayed."""
    now = datetime.now().isoformat()
    conn.execute(
        "INSERT INTO events (mmsi, event_type, detail, created_at) VALUES (?,?,?,?)",
        (999999999, "ARRIVED", "ghost ship", now),
    )
    conn.commit()

    event_row = conn.execute("SELECT * FROM events WHERE mmsi=999999999").fetchone()
    _display_event(conn, event_row, driver, cfg)

    driver.scroll_text.assert_not_called()
    updated = conn.execute(
        "SELECT displayed_at FROM events WHERE id=?", (event_row["id"],)
    ).fetchone()
    assert updated["displayed_at"] is not None


def test_show_idle_with_home_uses_range_count(conn, cfg, driver):
    """With home set, idle message reflects ships within distance_km."""
    now = datetime.now().isoformat()
    # Insert 2 ships close to home (lat=51.5, lon=0.0)
    for mmsi, name in [(100000001, "MV Alpha"), (100000002, "MV Beta")]:
        conn.execute(
            "INSERT INTO ships (mmsi, name, latitude, longitude, last_seen, first_seen)"
            " VALUES (?,?,?,?,?,?)",
            (mmsi, name, 51.5, 0.0, now, now),
        )
    # Insert 1 ship far away
    conn.execute(
        "INSERT INTO ships (mmsi, name, latitude, longitude, last_seen, first_seen)"
        " VALUES (?,?,?,?,?,?)",
        (100000003, "MV Faraway", 0.0, 0.0, now, now),
    )
    conn.commit()

    _show_idle(conn, driver, cfg)

    call_args = driver.show_static.call_args[0]
    msg = call_args[0]
    assert "2" in msg


def test_show_idle_without_home_uses_total_count(driver):
    """Without home location, idle message uses total ship count."""
    # Create a fresh connection with NO home_lat/lon set
    c = init_db(":memory:")
    cfg = Config(c)
    now = datetime.now().isoformat()
    for mmsi in [200000001, 200000002, 200000003]:
        c.execute(
            "INSERT INTO ships (mmsi, name, last_seen, first_seen) VALUES (?,?,?,?)",
            (mmsi, f"Ship {mmsi}", now, now),
        )
    c.commit()

    _show_idle(c, driver, cfg)

    call_args = driver.show_static.call_args[0]
    msg = call_args[0]
    assert "3" in msg


def test_handle_overflow_flushes_stale_events(conn, cfg, driver):
    """12 pending events with 11 older than 5 min -> 11 flushed, summary scrolled."""
    old_time = "2020-01-01T00:00:00"
    now = datetime.now().isoformat()

    # Insert 11 stale events
    for i in range(11):
        conn.execute(
            "INSERT INTO events (mmsi, event_type, detail, created_at) VALUES (?,?,?,?)",
            (300000000 + i, "ARRIVED", "old event", old_time),
        )
    # Insert 1 fresh event
    conn.execute(
        "INSERT INTO events (mmsi, event_type, detail, created_at) VALUES (?,?,?,?)",
        (300000099, "ARRIVED", "fresh event", now),
    )
    conn.commit()

    events = conn.execute(
        "SELECT * FROM events ORDER BY created_at ASC"
    ).fetchall()
    assert len(events) == 12

    _handle_overflow(conn, events, driver, cfg)

    # 11 stale events should now be marked displayed
    flushed = conn.execute(
        "SELECT COUNT(*) FROM events WHERE displayed_at IS NOT NULL"
    ).fetchone()[0]
    assert flushed == 11

    # Summary scroll message contains "flushed"
    call_args = driver.scroll_text.call_args[0]
    assert "flushed" in call_args[0]


def test_handle_overflow_displays_oldest_when_no_stale(conn, cfg, driver):
    """12 fresh events -> _display_event called for events[0]."""
    now = datetime.now().isoformat()
    mmsi = 400000001

    # Insert ship so _display_event can find it
    conn.execute(
        "INSERT INTO ships (mmsi, name, last_seen, first_seen) VALUES (?,?,?,?)",
        (mmsi, "MV Overflow", now, now),
    )
    # Insert 12 fresh events all for the same MMSI
    for _ in range(12):
        conn.execute(
            "INSERT INTO events (mmsi, event_type, detail, created_at) VALUES (?,?,?,?)",
            (mmsi, "ARRIVED", "event", now),
        )
    conn.commit()

    events = conn.execute(
        "SELECT * FROM events ORDER BY created_at ASC"
    ).fetchall()

    _handle_overflow(conn, events, driver, cfg)

    # driver.scroll_text called once (via _display_event for events[0])
    driver.scroll_text.assert_called_once()
    # The oldest event should be marked displayed
    oldest = conn.execute(
        "SELECT displayed_at FROM events WHERE id=?", (events[0]["id"],)
    ).fetchone()
    assert oldest["displayed_at"] is not None
