import sys
import pytest
from unittest import mock

@pytest.fixture
def client(tmp_path):
    """Flask test client with an in-memory database."""
    db_path = str(tmp_path / "test.db")
    # Configure the matrix_driver mock with concrete values so json.dumps works.
    matrix_mock = mock.MagicMock()
    matrix_mock.ESP32_DISPLAY_WIDTH = 600
    matrix_mock.ESP32_DISPLAY_HEIGHT = 32
    # get_current_frame must return a 2-D list of [R,G,B] pixels.
    dummy_frame = [[[0, 0, 0]] * 600] * 32
    matrix_mock.PreviewDriver.return_value.get_current_frame.return_value = dummy_frame

    with mock.patch.dict(sys.modules, {
        "ships_ahoy.matrix_driver": matrix_mock,
    }):
        import importlib
        # Reload to get fresh module state
        import services.web_service as ws
        importlib.reload(ws)
        ws._conn = __import__("ships_ahoy.db", fromlist=["init_db"]).init_db(db_path)
        ws._cfg = __import__("ships_ahoy.config", fromlist=["Config"]).Config(ws._conn)
        ws._db_path = db_path
        ws.app.config["TESTING"] = True
        with ws.app.test_client() as c:
            yield c, ws._conn

def test_ticker_preview_content_type(client):
    """GET /ticker/preview returns text/event-stream."""
    c, conn = client
    resp = c.get("/ticker/preview", query_string={"_max_frames": "1"})
    assert "text/event-stream" in resp.content_type

def test_ticker_preview_returns_data_line(client):
    """SSE stream emits at least one data: line with valid JSON."""
    import json
    c, conn = client
    resp = c.get("/ticker/preview", query_string={"_max_frames": "1"})
    body = resp.data.decode()
    for line in body.splitlines():
        if line.startswith("data:"):
            payload = json.loads(line[5:].strip())
            assert "pixels" in payload
            assert "width" in payload
            assert "height" in payload
            return
    pytest.fail("No data: line found in SSE stream")


from datetime import datetime
from ships_ahoy.db import upsert_ship
from ships_ahoy.ship_tracker import ShipInfo


def _make_ship(mmsi=123456789, name="MV Web Test"):
    return ShipInfo(mmsi=mmsi, name=name, last_seen=datetime.now())


def test_index_returns_200(client):
    c, conn = client
    resp = c.get("/")
    assert resp.status_code == 200


def test_index_shows_ship_name(client):
    c, conn = client
    upsert_ship(conn, _make_ship(name="MV Visible Ship"))
    resp = c.get("/")
    assert b"MV Visible Ship" in resp.data


def test_ship_detail_returns_200(client):
    c, conn = client
    upsert_ship(conn, _make_ship(mmsi=555000001))
    resp = c.get("/ship/555000001")
    assert resp.status_code == 200


def test_ship_detail_404_for_unknown(client):
    c, conn = client
    resp = c.get("/ship/9999999")
    assert resp.status_code == 404


def test_events_returns_200(client):
    c, conn = client
    resp = c.get("/events")
    assert resp.status_code == 200


def test_settings_get_returns_200(client):
    c, conn = client
    resp = c.get("/settings")
    assert resp.status_code == 200


def test_settings_post_saves_values(client):
    c, conn = client
    resp = c.post("/settings", data={"distance_km": "25.0"})
    assert resp.status_code == 302  # redirect

    from ships_ahoy.config import Config
    cfg = Config(conn)
    assert cfg.distance_km == 25.0


def test_settings_post_ignores_invalid_float(client):
    c, conn = client
    from ships_ahoy.config import Config
    original = Config(conn).distance_km

    resp = c.post("/settings", data={"distance_km": "notanumber"})
    assert resp.status_code == 302  # no crash

    assert Config(conn).distance_km == original
