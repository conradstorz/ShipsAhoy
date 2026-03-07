"""Tests for ships_ahoy.display."""

from unittest.mock import patch

import pytest

from ships_ahoy.display import (
    format_ship,
    get_nav_status_name,
    get_ship_type_name,
    display_ships,
)
from ships_ahoy.ship_tracker import ShipInfo


class TestGetShipTypeName:
    def test_cargo(self):
        assert get_ship_type_name(70) == "Cargo"

    def test_tanker(self):
        assert get_ship_type_name(80) == "Tanker"

    def test_passenger(self):
        assert get_ship_type_name(60) == "Passenger"

    def test_fishing(self):
        assert get_ship_type_name(30) == "Fishing"

    def test_special_craft(self):
        assert get_ship_type_name(50) == "Special Craft"

    def test_towing(self):
        assert get_ship_type_name(40) == "Towing"

    def test_wing_in_ground(self):
        assert get_ship_type_name(20) == "Wing In Ground"

    def test_other(self):
        assert get_ship_type_name(90) == "Other"

    def test_unknown_when_none(self):
        assert get_ship_type_name(None) == "Unknown"

    def test_unrecognised_type_includes_number(self):
        result = get_ship_type_name(15)
        assert "15" in result


class TestGetNavStatusName:
    def test_under_way_engine(self):
        assert "engine" in get_nav_status_name(0).lower()

    def test_at_anchor(self):
        assert "anchor" in get_nav_status_name(1).lower()

    def test_moored(self):
        assert "moored" in get_nav_status_name(5).lower()

    def test_unknown_status_includes_number(self):
        result = get_nav_status_name(99)
        assert "99" in result


class TestFormatShip:
    def test_shows_mmsi(self):
        ship = ShipInfo(mmsi=123456789)
        assert "123456789" in format_ship(ship)

    def test_shows_default_name(self):
        ship = ShipInfo(mmsi=123456789)
        assert "Unknown" in format_ship(ship)

    def test_shows_custom_name(self):
        ship = ShipInfo(mmsi=123456789, name="ENTERPRISE")
        assert "ENTERPRISE" in format_ship(ship)

    def test_shows_position_when_available(self):
        ship = ShipInfo(mmsi=123456789, latitude=51.5074, longitude=-0.1278)
        result = format_ship(ship)
        assert "51.50740" in result
        assert "-0.12780" in result

    def test_hides_position_when_unavailable(self):
        ship = ShipInfo(mmsi=123456789)
        assert "Position" not in format_ship(ship)

    def test_shows_speed_when_available(self):
        ship = ShipInfo(mmsi=123456789, speed=12.5)
        result = format_ship(ship)
        assert "12.5" in result
        assert "knots" in result

    def test_hides_speed_when_unavailable(self):
        ship = ShipInfo(mmsi=123456789)
        assert "knots" not in format_ship(ship)

    def test_shows_heading_when_available(self):
        ship = ShipInfo(mmsi=123456789, heading=270.0)
        result = format_ship(ship)
        assert "270" in result

    def test_shows_course_when_available(self):
        ship = ShipInfo(mmsi=123456789, course=180.5)
        result = format_ship(ship)
        assert "180.5" in result

    def test_shows_nav_status_when_available(self):
        ship = ShipInfo(mmsi=123456789, status=0)
        result = format_ship(ship)
        assert "engine" in result.lower()

    def test_shows_ship_type_when_available(self):
        ship = ShipInfo(mmsi=123456789, ship_type=70)
        assert "Cargo" in format_ship(ship)

    def test_shows_last_seen(self):
        ship = ShipInfo(mmsi=123456789)
        assert "Last seen" in format_ship(ship)


class TestDisplayShips:
    @patch("ships_ahoy.display.os.system")
    def test_no_ships_shows_waiting_message(self, _mock_cls, capsys):
        display_ships({})
        out = capsys.readouterr().out
        assert "No ships detected" in out

    @patch("ships_ahoy.display.os.system")
    def test_shows_ship_count(self, _mock_cls, capsys):
        ships = {111: ShipInfo(mmsi=111, name="SHIP_A")}
        display_ships(ships)
        out = capsys.readouterr().out
        assert "1" in out

    @patch("ships_ahoy.display.os.system")
    def test_shows_ship_name(self, _mock_cls, capsys):
        ships = {222: ShipInfo(mmsi=222, name="VOYAGER")}
        display_ships(ships)
        out = capsys.readouterr().out
        assert "VOYAGER" in out

    @patch("ships_ahoy.display.os.system")
    def test_shows_header(self, _mock_cls, capsys):
        display_ships({})
        out = capsys.readouterr().out
        assert "ShipsAhoy" in out

    @patch("ships_ahoy.display.os.system")
    def test_clears_screen(self, mock_sys, capsys):
        display_ships({})
        mock_sys.assert_called_once()
