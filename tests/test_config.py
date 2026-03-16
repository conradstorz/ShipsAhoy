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
