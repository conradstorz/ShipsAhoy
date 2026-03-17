import sys
from unittest import mock


def _import_build_parser():
    # Import lazily to avoid import-time driver selection running
    import importlib
    spec = importlib.util.spec_from_file_location(
        "ticker_service",
        "services/ticker_service.py",
    )
    mod = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, {"ships_ahoy.matrix_driver": mock.MagicMock()}):
        spec.loader.exec_module(mod)
    return mod._build_parser


def test_build_parser_has_esp32_port_arg():
    build_parser = _import_build_parser()
    parser = build_parser()
    args = parser.parse_args(["--esp32-port", "/dev/ttyAMA0"])
    assert args.esp32_port == "/dev/ttyAMA0"

def test_build_parser_esp32_port_defaults_to_none():
    build_parser = _import_build_parser()
    parser = build_parser()
    args = parser.parse_args([])
    assert args.esp32_port is None
