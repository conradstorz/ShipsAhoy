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
    assert 338 < km < 345


def test_haversine_same_point_is_zero():
    assert haversine_km(51.5, -0.1, 51.5, -0.1) == pytest.approx(0.0, abs=1e-6)


def test_haversine_is_symmetric():
    a = haversine_km(*LONDON, *PARIS)
    b = haversine_km(*PARIS, *LONDON)
    assert a == pytest.approx(b, rel=1e-6)


def test_bearing_london_to_paris():
    bearing = bearing_degrees(*LONDON, *PARIS)
    assert 145 < bearing < 162


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
    assert bearing_to_cardinal(156.0) == "SSE"


def test_bearing_to_cardinal_wsw():
    assert bearing_to_cardinal(247.0) == "WSW"


def test_is_noteworthy_within_range():
    assert is_noteworthy(*PARIS, *LONDON, threshold_km=400.0) is True


def test_is_noteworthy_outside_range():
    assert is_noteworthy(*PARIS, *LONDON, threshold_km=200.0) is False


def test_is_noteworthy_exactly_on_boundary():
    km = haversine_km(*LONDON, *PARIS)
    assert is_noteworthy(*PARIS, *LONDON, threshold_km=km) is True
