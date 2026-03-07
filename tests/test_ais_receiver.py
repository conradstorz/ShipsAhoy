"""Tests for ships_ahoy.ais_receiver."""

from unittest.mock import MagicMock, patch

import pytest

from ships_ahoy.ais_receiver import AISReceiver, DEFAULT_HOST, DEFAULT_TCP_PORT, DEFAULT_UDP_PORT


class TestAISReceiverDefaults:
    def test_default_host(self):
        r = AISReceiver()
        assert r.host == DEFAULT_HOST

    def test_default_port(self):
        r = AISReceiver()
        assert r.port == DEFAULT_TCP_PORT

    def test_default_tcp_not_udp(self):
        r = AISReceiver()
        assert r.use_udp is False

    def test_custom_host_and_port(self):
        r = AISReceiver(host="192.168.1.50", port=9999)
        assert r.host == "192.168.1.50"
        assert r.port == 9999

    def test_udp_flag(self):
        r = AISReceiver(use_udp=True)
        assert r.use_udp is True


class TestAISReceiverMessages:
    """Test AISReceiver.messages() using mocked pyais stream classes."""

    def _make_decoded_msg(self, mmsi: int):
        msg = MagicMock()
        msg.mmsi = mmsi
        return msg

    def _make_nmea_msg(self, mmsi: int):
        nmea = MagicMock()
        nmea.decode.return_value = self._make_decoded_msg(mmsi)
        return nmea

    @patch("ships_ahoy.ais_receiver.TCPConnection")
    def test_tcp_connection_used_by_default(self, MockTCP):
        mock_stream = MagicMock()
        mock_stream.__enter__ = MagicMock(return_value=iter([]))
        mock_stream.__exit__ = MagicMock(return_value=False)
        MockTCP.return_value = mock_stream

        receiver = AISReceiver(host="localhost", port=10110)
        list(receiver.messages())

        MockTCP.assert_called_once_with("localhost", 10110)

    @patch("ships_ahoy.ais_receiver.UDPReceiver")
    def test_udp_receiver_used_when_flag_set(self, MockUDP):
        mock_stream = MagicMock()
        mock_stream.__enter__ = MagicMock(return_value=iter([]))
        mock_stream.__exit__ = MagicMock(return_value=False)
        MockUDP.return_value = mock_stream

        receiver = AISReceiver(host="0.0.0.0", port=10110, use_udp=True)
        list(receiver.messages())

        MockUDP.assert_called_once_with("0.0.0.0", 10110)

    @patch("ships_ahoy.ais_receiver.TCPConnection")
    def test_yields_decoded_messages(self, MockTCP):
        nmea_msgs = [self._make_nmea_msg(100), self._make_nmea_msg(200)]
        mock_stream = MagicMock()
        mock_stream.__enter__ = MagicMock(return_value=iter(nmea_msgs))
        mock_stream.__exit__ = MagicMock(return_value=False)
        MockTCP.return_value = mock_stream

        receiver = AISReceiver()
        results = list(receiver.messages())

        assert len(results) == 2
        assert results[0].mmsi == 100
        assert results[1].mmsi == 200

    @patch("ships_ahoy.ais_receiver.TCPConnection")
    def test_skips_messages_that_fail_to_decode(self, MockTCP):
        bad_nmea = MagicMock()
        bad_nmea.decode.side_effect = Exception("decode error")

        good_nmea = self._make_nmea_msg(999)

        mock_stream = MagicMock()
        mock_stream.__enter__ = MagicMock(return_value=iter([bad_nmea, good_nmea]))
        mock_stream.__exit__ = MagicMock(return_value=False)
        MockTCP.return_value = mock_stream

        receiver = AISReceiver()
        results = list(receiver.messages())

        assert len(results) == 1
        assert results[0].mmsi == 999

    @patch("ships_ahoy.ais_receiver.TCPConnection")
    def test_connection_refused_propagates(self, MockTCP):
        MockTCP.side_effect = ConnectionRefusedError("refused")

        receiver = AISReceiver()
        with pytest.raises(ConnectionRefusedError):
            list(receiver.messages())
