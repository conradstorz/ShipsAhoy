"""Tests for ships_ahoy.ship_tracker."""

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from ships_ahoy.ship_tracker import ShipInfo, ShipTracker


# ---------------------------------------------------------------------------
# Helper: build a mock decoded AIS message
# ---------------------------------------------------------------------------

def _make_msg(**kwargs):
    """Return a MagicMock that mimics a decoded pyais message."""
    msg = MagicMock(spec=[])          # spec=[] means no pre-defined attrs
    for key, value in kwargs.items():
        setattr(msg, key, value)
    return msg


# ---------------------------------------------------------------------------
# ShipInfo
# ---------------------------------------------------------------------------

class TestShipInfo:
    def test_position_when_both_coords_set(self):
        ship = ShipInfo(mmsi=123456789, latitude=51.5, longitude=-0.1)
        assert ship.position == (51.5, -0.1)

    def test_position_none_when_no_coords(self):
        ship = ShipInfo(mmsi=123456789)
        assert ship.position is None

    def test_position_none_when_only_latitude(self):
        ship = ShipInfo(mmsi=123456789, latitude=51.5)
        assert ship.position is None

    def test_position_none_when_only_longitude(self):
        ship = ShipInfo(mmsi=123456789, longitude=-0.1)
        assert ship.position is None

    def test_default_name(self):
        ship = ShipInfo(mmsi=123456789)
        assert ship.name == "Unknown"

    def test_last_seen_set_on_creation(self):
        before = datetime.now()
        ship = ShipInfo(mmsi=123456789)
        after = datetime.now()
        assert before <= ship.last_seen <= after


# ---------------------------------------------------------------------------
# ShipTracker — initial state
# ---------------------------------------------------------------------------

class TestShipTrackerInitial:
    def test_empty_on_creation(self):
        tracker = ShipTracker()
        assert tracker.ship_count() == 0

    def test_ships_empty_dict(self):
        tracker = ShipTracker()
        assert tracker.ships == {}

    def test_get_ship_unknown_returns_none(self):
        tracker = ShipTracker()
        assert tracker.get_ship(123456789) is None


# ---------------------------------------------------------------------------
# ShipTracker.update — position messages
# ---------------------------------------------------------------------------

class TestShipTrackerUpdate:
    def test_returns_none_when_no_mmsi(self):
        tracker = ShipTracker()
        result = tracker.update(_make_msg())
        assert result is None
        assert tracker.ship_count() == 0

    def test_creates_new_ship_on_first_message(self):
        tracker = ShipTracker()
        msg = _make_msg(mmsi=366053242, lat=37.8, lon=-122.4, speed=0.0)
        ship = tracker.update(msg)
        assert ship is not None
        assert ship.mmsi == 366053242
        assert tracker.ship_count() == 1

    def test_updates_position(self):
        tracker = ShipTracker()
        msg = _make_msg(mmsi=111111111, lat=51.5074, lon=-0.1278)
        ship = tracker.update(msg)
        assert ship.latitude == pytest.approx(51.5074)
        assert ship.longitude == pytest.approx(-0.1278)

    def test_ignores_unavailable_lat(self):
        tracker = ShipTracker()
        msg = _make_msg(mmsi=111111111, lat=91.0)
        ship = tracker.update(msg)
        assert ship.latitude is None

    def test_ignores_unavailable_lon(self):
        tracker = ShipTracker()
        msg = _make_msg(mmsi=111111111, lon=181.0)
        ship = tracker.update(msg)
        assert ship.longitude is None

    def test_ignores_unavailable_speed(self):
        tracker = ShipTracker()
        msg = _make_msg(mmsi=111111111, speed=102.3)
        ship = tracker.update(msg)
        assert ship.speed is None

    def test_ignores_unavailable_heading(self):
        tracker = ShipTracker()
        msg = _make_msg(mmsi=111111111, heading=511)
        ship = tracker.update(msg)
        assert ship.heading is None

    def test_ignores_unavailable_course(self):
        tracker = ShipTracker()
        msg = _make_msg(mmsi=111111111, course=360.0)
        ship = tracker.update(msg)
        assert ship.course is None

    def test_updates_speed(self):
        tracker = ShipTracker()
        msg = _make_msg(mmsi=222222222, speed=12.5)
        ship = tracker.update(msg)
        assert ship.speed == pytest.approx(12.5)

    def test_updates_heading(self):
        tracker = ShipTracker()
        msg = _make_msg(mmsi=333333333, heading=270)
        ship = tracker.update(msg)
        assert ship.heading == pytest.approx(270.0)

    def test_updates_course(self):
        tracker = ShipTracker()
        msg = _make_msg(mmsi=333333333, course=180.5)
        ship = tracker.update(msg)
        assert ship.course == pytest.approx(180.5)

    def test_updates_ship_name(self):
        tracker = ShipTracker()
        msg = _make_msg(mmsi=444444444, shipname="TITANIC      ")
        ship = tracker.update(msg)
        assert ship.name == "TITANIC"

    def test_updates_ship_name_from_name_field(self):
        """msg type 21 uses 'name' attribute instead of 'shipname'."""
        tracker = ShipTracker()
        msg = _make_msg(mmsi=444444445, name="BUOY 7       ")
        ship = tracker.update(msg)
        assert ship.name == "BUOY 7"

    def test_updates_ship_type(self):
        tracker = ShipTracker()
        msg = _make_msg(mmsi=555555555, ship_type=70)
        ship = tracker.update(msg)
        assert ship.ship_type == 70

    def test_updates_nav_status(self):
        tracker = ShipTracker()
        msg = _make_msg(mmsi=666666666, status=0)
        ship = tracker.update(msg)
        assert ship.status == 0

    def test_same_mmsi_does_not_duplicate(self):
        tracker = ShipTracker()
        msg1 = _make_msg(mmsi=777777777, lat=10.0, lon=20.0)
        msg2 = _make_msg(mmsi=777777777, lat=10.1, lon=20.1)
        tracker.update(msg1)
        tracker.update(msg2)
        assert tracker.ship_count() == 1

    def test_last_seen_updated_on_each_message(self):
        tracker = ShipTracker()
        msg = _make_msg(mmsi=888888888)
        ship = tracker.update(msg)
        first_seen = ship.last_seen

        ship = tracker.update(msg)
        assert ship.last_seen >= first_seen

    def test_multiple_ships_tracked(self):
        tracker = ShipTracker()
        for mmsi in (100, 200, 300):
            tracker.update(_make_msg(mmsi=mmsi))
        assert tracker.ship_count() == 3

    def test_ships_returns_copy(self):
        """Mutating the returned dict should not affect the tracker."""
        tracker = ShipTracker()
        tracker.update(_make_msg(mmsi=111))
        snapshot = tracker.ships
        snapshot.clear()
        assert tracker.ship_count() == 1

    def test_get_ship_returns_correct_ship(self):
        tracker = ShipTracker()
        tracker.update(_make_msg(mmsi=999999999))
        ship = tracker.get_ship(999999999)
        assert ship is not None
        assert ship.mmsi == 999999999


# ---------------------------------------------------------------------------
# Integration: real pyais decoded messages
# ---------------------------------------------------------------------------

class TestShipTrackerWithRealMessages:
    """Use pyais to decode real NMEA sentences and feed them to ShipTracker."""

    def test_type1_message(self):
        from pyais import decode

        nmea = "!AIVDM,1,1,,B,15M67N`P00G?Uf6E`FepT@3n00Sa,0*73"
        decoded = decode(nmea)

        tracker = ShipTracker()
        ship = tracker.update(decoded)

        assert ship is not None
        assert ship.mmsi == 366053242
        assert ship.latitude == pytest.approx(37.802118, abs=1e-4)
        assert ship.longitude == pytest.approx(-122.423568, abs=1e-4)
