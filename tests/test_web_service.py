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
            yield c

def test_ticker_preview_content_type(client):
    """GET /ticker/preview returns text/event-stream."""
    resp = client.get("/ticker/preview", query_string={"_max_frames": "1"})
    assert "text/event-stream" in resp.content_type

def test_ticker_preview_returns_data_line(client):
    """SSE stream emits at least one data: line with valid JSON."""
    import json
    resp = client.get("/ticker/preview", query_string={"_max_frames": "1"})
    body = resp.data.decode()
    for line in body.splitlines():
        if line.startswith("data:"):
            payload = json.loads(line[5:].strip())
            assert "pixels" in payload
            assert "width" in payload
            assert "height" in payload
            return
    pytest.fail("No data: line found in SSE stream")
