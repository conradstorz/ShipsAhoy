"""Tests for the ticker_service continuous cycle loop."""
import sys
import pytest
from unittest import mock
import importlib.util


def _load_ticker_service():
    """Load ticker_service with matrix_driver mocked to prevent hardware import errors."""
    spec = importlib.util.spec_from_file_location(
        "ticker_service", "services/ticker_service.py"
    )
    mod = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, {"ships_ahoy.matrix_driver": mock.MagicMock()}):
        spec.loader.exec_module(mod)
    return mod


_ts_mod = _load_ticker_service()


def test_build_parser_esp32_port_arg():
    args = _ts_mod._build_parser().parse_args(["--esp32-port", "/dev/ttyAMA0"])
    assert args.esp32_port == "/dev/ttyAMA0"


def test_build_parser_esp32_port_defaults_to_none():
    args = _ts_mod._build_parser().parse_args([])
    assert args.esp32_port is None


def test_main_calls_scroll_text_for_each_chunk():
    """main() calls driver.scroll_text once per playlist chunk, then stops."""
    driver = mock.MagicMock()
    playlist = ["MV Test is a cargo vessel flying the US flag",
                "MV Test is traveling at 8.5 knots heading west"]
    scroll_calls = []

    def scroll_and_stop(text, speed_px_per_sec):
        scroll_calls.append(text)
        if len(scroll_calls) >= len(playlist):
            raise KeyboardInterrupt

    driver.scroll_text.side_effect = scroll_and_stop

    with mock.patch("sys.argv", ["ticker_service"]):
        with mock.patch.object(_ts_mod, "init_db", return_value=mock.MagicMock()):
            with mock.patch.object(_ts_mod, "Config", return_value=mock.MagicMock()):
                with mock.patch.object(_ts_mod, "build_playlist", return_value=playlist):
                    with mock.patch.object(_ts_mod, "_DriverClass", return_value=driver):
                        with pytest.raises(SystemExit) as exc:
                            _ts_mod.main()

    assert scroll_calls == playlist
    assert exc.value.code == 0


def test_main_clears_display_on_keyboard_interrupt():
    """KeyboardInterrupt triggers driver.clear() and sys.exit(0)."""
    driver = mock.MagicMock()
    driver.scroll_text.side_effect = KeyboardInterrupt

    with mock.patch("sys.argv", ["ticker_service"]):
        with mock.patch.object(_ts_mod, "init_db", return_value=mock.MagicMock()):
            with mock.patch.object(_ts_mod, "Config", return_value=mock.MagicMock()):
                with mock.patch.object(_ts_mod, "build_playlist", return_value=["chunk"]):
                    with mock.patch.object(_ts_mod, "_DriverClass", return_value=driver):
                        with pytest.raises(SystemExit) as exc:
                            _ts_mod.main()

    driver.clear.assert_called_once()
    assert exc.value.code == 0
