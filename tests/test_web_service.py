import sys
import pytest
from unittest import mock
from datetime import datetime

from ships_ahoy.db import upsert_ship, add_quip, get_all_quips, toggle_quip
from ships_ahoy.ship_tracker import ShipInfo

@pytest.fixture
def client(tmp_path):
    """Flask test client with an in-memory database."""
    db_path = str(tmp_path / "test.db")
    # Configure the matrix_driver mock with concrete values so json.dumps works.
    matrix_mock = mock.MagicMock()
    matrix_mock.ESP32_DISPLAY_WIDTH = 320
    matrix_mock.ESP32_DISPLAY_HEIGHT = 8
    # get_current_frame must return a 2-D list of [R,G,B] pixels.
    dummy_frame = [[[0, 0, 0]] * 320] * 8
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


def test_quips_page_returns_200(client):
    c, conn = client
    resp = c.get("/quips")
    assert resp.status_code == 200


def test_quips_page_shows_table(client):
    c, conn = client
    add_quip(conn, "A funny joke", "quip")
    resp = c.get("/quips")
    assert b"A funny joke" in resp.data


def test_add_quip_via_post_redirects(client):
    c, conn = client
    resp = c.post("/quips/add", data={"text": "Hello river!", "category": "location"})
    assert resp.status_code == 302


def test_add_quip_via_post_persists_to_db(client):
    c, conn = client
    c.post("/quips/add", data={"text": "Hello river!", "category": "location"})
    rows = get_all_quips(conn)
    assert any(r["text"] == "Hello river!" for r in rows)


def test_toggle_quip_via_post_deactivates(client):
    c, conn = client
    qid = add_quip(conn, "Toggle me", "quip")
    c.post(f"/quips/{qid}/toggle")
    row = conn.execute("SELECT active FROM quips WHERE id=?", (qid,)).fetchone()
    assert row["active"] == 0


def test_delete_quip_via_post_removes_row(client):
    c, conn = client
    qid = add_quip(conn, "Delete me", "quip")
    c.post(f"/quips/{qid}/delete")
    rows = get_all_quips(conn)
    assert not any(r["id"] == qid for r in rows)


def test_add_quip_ignores_empty_text(client):
    c, conn = client
    c.post("/quips/add", data={"text": "   ", "category": "quip"})
    assert get_all_quips(conn) == []


def test_ticker_preview_uses_build_playlist(client):
    """SSE preview calls build_playlist; frames are emitted for each chunk."""
    import json as _json
    c, conn = client
    # Insert a ship so build_playlist returns ship chunks
    from ships_ahoy.ship_tracker import ShipInfo
    from datetime import datetime
    upsert_ship(conn, ShipInfo(
        mmsi=987654321, name="MV Preview",
        latitude=51.5, longitude=0.1,
        last_seen=datetime.now(),
    ))
    conn.execute("UPDATE settings SET value='51.5' WHERE key='home_lat'")
    conn.execute("UPDATE settings SET value='0.1' WHERE key='home_lon'")
    conn.execute("UPDATE settings SET value='100' WHERE key='distance_km'")
    conn.commit()

    resp = c.get("/ticker/preview", query_string={"_max_frames": "2"})
    body = resp.data.decode()
    data_lines = [l for l in body.splitlines() if l.startswith("data:")]
    assert len(data_lines) == 2
    payload = _json.loads(data_lines[0][5:].strip())
    assert "pixels" in payload
