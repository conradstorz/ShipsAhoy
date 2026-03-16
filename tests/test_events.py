"""Tests for ships_ahoy.events."""
import sqlite3
import pytest
from ships_ahoy.events import EventType, detect_events, format_ticker_message
from ships_ahoy.ship_tracker import ShipInfo


def make_ship(**kwargs):
    defaults = dict(mmsi=123456789, name="TEST VESSEL", status=0)
    defaults.update(kwargs)
    return ShipInfo(**defaults)


def test_event_type_arrived():
    assert EventType.ARRIVED == "ARRIVED"


def test_event_type_departed():
    assert EventType.DEPARTED == "DEPARTED"


def test_event_type_status_change():
    assert EventType.STATUS_CHANGE == "STATUS_CHANGE"


def test_event_type_enriched():
    assert EventType.ENRICHED == "ENRICHED"


def test_detect_events_no_change_returns_empty():
    ship = make_ship()
    with pytest.raises(NotImplementedError):
        detect_events(ship, ship)


def test_detect_events_status_change_detected():
    old = make_ship(status=1)
    new = make_ship(status=0)
    with pytest.raises(NotImplementedError):
        detect_events(old, new)


def test_detect_events_not_called_for_new_ships():
    """ARRIVED is written directly by ais_service; detect_events is never called
    with a 'new' ship."""
    ship = make_ship()
    with pytest.raises((TypeError, NotImplementedError)):
        detect_events(None, ship)  # type: ignore[arg-type]


def test_format_ticker_message_raises():
    with pytest.raises((NotImplementedError, TypeError)):
        format_ticker_message(None, None, None)
