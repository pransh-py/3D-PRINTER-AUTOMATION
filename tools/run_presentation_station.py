"""Run only the outbound free queue adapter and native printer monitor (WSL/Linux)."""

import argparse
import asyncio
import fcntl
import sys
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.bridge.bridge import NoRedirect  # noqa: E402
from services.bridge.commerce_connector import read_config  # noqa: E402
from services.bridge.presentation_connector import PresentationConnector  # noqa: E402
from services.bridge.print_station import Station, StationConfig  # noqa: E402


async def serve(station, connector):
    monitor = asyncio.create_task(station.monitor())
    try:
        await connector.run()
    finally:
        monitor.cancel()
        await asyncio.gather(monitor, return_exceptions=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--station-directory", type=Path, required=True)
    parser.add_argument("--connector-config", type=Path, required=True)
    parser.add_argument("--enable-printer", action="store_true")
    args = parser.parse_args()
    directory = args.station_directory.resolve(strict=True)
    with (directory / "station.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        configuration = directory / "configuration.json"
        if configuration.is_symlink() or configuration.stat().st_mode & 0o077:
            raise ValueError("Native configuration must be private and regular.")
        config = StationConfig.model_validate_json(configuration.read_bytes())
        station = Station(
            config, directory / "jobs", enable_printer=args.enable_printer
        )
        connector = PresentationConnector(station, read_config(args.connector_config))
        connector.api.opener = build_opener(ProxyHandler({}), NoRedirect())
        print(
            "Free queue service running; each print requires fresh owner plate clearance.",
            flush=True,
        )
        asyncio.run(serve(station, connector))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError):
        print(
            "Queue service stopped. Check private configuration and the exclusive station lock.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
