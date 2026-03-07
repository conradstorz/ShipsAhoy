"""AIS message receiver using a Software Defined Radio (SDR) source.

Connects to a TCP or UDP endpoint produced by a tool such as ``rtl_ais``
and yields decoded AIS message objects ready for processing
by :class:`~ships_ahoy.ship_tracker.ShipTracker`.

Typical hardware setup
----------------------
1. Plug in an RTL-SDR USB dongle with a marine-band antenna.
2. Install ``rtl_ais`` (https://github.com/dgiardini/rtl-ais) on the host.
3. Run ``rtl_ais`` to start decoding on the default TCP port::

       rtl_ais -n -T -p 0 -d 0 2>/dev/null

4. Start ShipsAhoy (default connects to localhost:10110)::

       python main.py

The default port 10110 is the standard NMEA network port used by ``rtl_ais``
when started with the ``-T`` flag.
"""

import logging
from typing import Generator, Union

from pyais.messages import ANY_MESSAGE
from pyais.stream import TCPConnection, UDPReceiver

logger = logging.getLogger(__name__)

DEFAULT_HOST = "localhost"
DEFAULT_TCP_PORT = 10110
DEFAULT_UDP_PORT = 10110


class AISReceiver:
    """Receive and decode AIS messages from an SDR source over TCP or UDP.

    Parameters
    ----------
    host:
        Hostname or IP address of the AIS data source.
    port:
        Port number of the AIS data source.
    use_udp:
        When *True* use a UDP socket instead of TCP.  Useful when
        ``rtl_ais`` is started without the ``-T`` flag.
    """

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_TCP_PORT,
        use_udp: bool = False,
    ) -> None:
        self.host = host
        self.port = port
        self.use_udp = use_udp

    def messages(self) -> Generator[ANY_MESSAGE, None, None]:
        """Connect to the AIS source and yield decoded messages.

        Yields
        ------
        Msg
            A decoded AIS message (e.g. :class:`~pyais.messages.MessageType1`).

        Raises
        ------
        ConnectionRefusedError
            If a TCP connection cannot be established.
        """
        if self.use_udp:
            logger.info("Listening for AIS UDP datagrams on %s:%d", self.host, self.port)
            connection: Union[UDPReceiver, TCPConnection] = UDPReceiver(self.host, self.port)
        else:
            logger.info("Connecting to AIS TCP source at %s:%d", self.host, self.port)
            connection = TCPConnection(self.host, self.port)

        with connection as stream:
            for nmea_msg in stream:
                try:
                    decoded = nmea_msg.decode()
                    yield decoded
                except Exception as exc:
                    logger.debug("Could not decode AIS message: %s", exc)
