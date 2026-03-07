"""ShipsAhoy — entry point.

Connects to an AIS data source (produced by a tool such as ``rtl_ais``),
decodes the incoming messages, and displays live ship information in the
terminal.

Quick start
-----------
1. Attach an RTL-SDR dongle with a marine VHF antenna.
2. Install and run ``rtl_ais``::

       rtl_ais -n -T -p 0 -d 0 2>/dev/null

3. In a separate terminal::

       python main.py

Press **Ctrl-C** to stop.
"""

import argparse
import logging
import sys
import time

from ships_ahoy.ais_receiver import AISReceiver, DEFAULT_HOST, DEFAULT_TCP_PORT, DEFAULT_UDP_PORT
from ships_ahoy.display import display_ships
from ships_ahoy.ship_tracker import ShipTracker

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s  %(name)s  %(levelname)s  %(message)s",
)
logger = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ships_ahoy",
        description=(
            "ShipsAhoy — monitor nearby shipping traffic using AIS broadcasts "
            "received via a Software Defined Radio (SDR)."
        ),
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        metavar="HOST",
        help=f"Hostname or IP of the AIS data source (default: {DEFAULT_HOST})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_TCP_PORT,
        metavar="PORT",
        help=f"Port of the AIS data source (default: {DEFAULT_TCP_PORT})",
    )
    parser.add_argument(
        "--udp",
        action="store_true",
        help="Use UDP instead of TCP to receive AIS data",
    )
    parser.add_argument(
        "--refresh",
        type=float,
        default=2.0,
        metavar="SECONDS",
        help="Display refresh interval in seconds (default: 2.0)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose/debug logging",
    )
    return parser


def main() -> None:
    """Application entry point."""
    args = _build_parser().parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    tracker = ShipTracker()
    receiver = AISReceiver(host=args.host, port=args.port, use_udp=args.udp)

    protocol = "UDP" if args.udp else "TCP"
    print(f"ShipsAhoy starting — connecting to {protocol} {args.host}:{args.port}")
    print("Press Ctrl-C to quit.\n")

    last_display: float = 0.0

    try:
        for msg in receiver.messages():
            tracker.update(msg)

            now = time.monotonic()
            if now - last_display >= args.refresh:
                display_ships(tracker.ships)
                last_display = now

    except KeyboardInterrupt:
        print("\nShipsAhoy stopped.")
        sys.exit(0)

    except ConnectionRefusedError:
        protocol = "UDP" if args.udp else "TCP"
        print(
            f"\nError: could not connect to AIS source at {protocol} "
            f"{args.host}:{args.port}\n\n"
            "Make sure an AIS decoder is running and forwarding data to that address.\n"
            "Example using rtl_ais over TCP:\n\n"
            "    rtl_ais -n -T -p 0 -d 0 2>/dev/null\n",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
