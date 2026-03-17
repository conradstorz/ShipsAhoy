"""Tests for ships_ahoy.config."""
import pytest
from ships_ahoy.db import init_db
from ships_ahoy.config import Config


@pytest.fixture
def config():
    conn = init_db(":memory:")
    return Config(conn)


def test_config_can_be_instantiated(config):
    assert config is not None


# ---------------------------------------------------------------------------
# get / set
# ---------------------------------------------------------------------------

def test_config_get_returns_seeded_default(config):
    assert config.get("distance_km") == "50"


def test_config_get_returns_provided_default_for_missing_key(config):
    assert config.get("nonexistent_key", "fallback") == "fallback"


def test_config_get_returns_none_for_null_value(config):
    # home_lat is seeded as NULL
    assert config.get("home_lat") is None


def test_config_set_persists_value(config):
    config.set("distance_km", "100")
    assert config.get("distance_km") == "100"


def test_config_set_inserts_new_key(config):
    config.set("custom_key", "custom_value")
    assert config.get("custom_key") == "custom_value"


# ---------------------------------------------------------------------------
# home_location
# ---------------------------------------------------------------------------

def test_config_home_location_returns_none_when_unset(config):
    assert config.home_location is None


def test_config_home_location_returns_none_when_only_lat_set(config):
    config.set("home_lat", "51.5")
    assert config.home_location is None


def test_config_home_location_returns_tuple_when_both_set(config):
    config.set("home_lat", "51.5")
    config.set("home_lon", "-0.1")
    loc = config.home_location
    assert loc is not None
    assert abs(loc[0] - 51.5) < 0.0001
    assert abs(loc[1] - (-0.1)) < 0.0001


# ---------------------------------------------------------------------------
# typed properties
# ---------------------------------------------------------------------------

def test_config_distance_km_returns_float(config):
    assert config.distance_km == 50.0


def test_config_stale_ship_hours_returns_float(config):
    assert config.stale_ship_hours == 1.0


def test_config_scroll_speed_returns_float(config):
    assert config.scroll_speed == 40.0


def test_config_enrichment_delay_sec_returns_float(config):
    assert config.enrichment_delay_sec == 10.0


def test_config_enrichment_max_attempts_returns_int(config):
    assert config.enrichment_max_attempts == 3
    assert isinstance(config.enrichment_max_attempts, int)


def test_config_properties_reflect_updated_values(config):
    config.set("distance_km", "75")
    assert config.distance_km == 75.0
