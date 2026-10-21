"""Pair an outbound order connector and run the unchanged local station (WSL/Linux/macOS)."""

import argparse
import asyncio
import fcntl
import getpass
import sys
from pathlib import Path

import uvicorn
from pydantic import SecretStr

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from xxx_api.print_presets import profile_settings, read_profile_bundle  # noqa: E402

from services.bridge.bridge import ManualBridge  # noqa: E402
from services.bridge.commerce_connector import (  # noqa: E402
    ApprovedProfile,
    CommerceConnector,
    ConnectorConfig,
    read_config,
    save_config,
)
from services.bridge.print_station import StationConfig, create_app  # noqa: E402


async def serve(app, connector, port):
    server = uvicorn.Server(
        uvicorn.Config(
            app, host="127.0.0.1", port=port, access_log=False, proxy_headers=False
        )
    )
    task = asyncio.create_task(connector.run())
    try:
        await server.serve()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--station-directory", type=Path, default=ROOT / ".local/print-station"
    )
    parser.add_argument(
        "--connector-directory", type=Path, default=ROOT / ".local/commerce-station"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    pair = commands.add_parser("pair")
    pair.add_argument("--api", required=True)
    approve = commands.add_parser("approve-profile")
    approve.add_argument("--directory", type=Path, required=True)
    approve.add_argument("--sha256", required=True)
    approve.add_argument("--material", choices=["PLA", "PETG"], required=True)
    run = commands.add_parser("run")
    run.add_argument("--enable-printer", action="store_true")
    run.add_argument("--port", type=int, default=8123)
    args = parser.parse_args()
    station_dir = args.station_directory.resolve(strict=True)
    path = args.connector_directory.resolve() / "commerce-connector.json"
    # Exactly the native runner lock, never a parallel physical controller.
    with (station_dir / "station.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.command == "pair":
            if path.exists():
                raise ValueError(
                    "Connector configuration exists; preserve it before re-pairing."
                )
            api = ManualBridge(args.api)
            result = api.request(
                "/api/v1/bridge/pair",
                {
                    "token": getpass.getpass("One-use owner pairing token (hidden): "),
                    "adapter": "station-zmod-v1",
                },
            )
            save_config(
                path,
                ConnectorConfig(
                    api_origin=args.api, credential=SecretStr(result["credential"])
                ),
            )
            print(
                "Paired privately. No printer command sent; profile approval is still required."
            )
            return
        connector_config = read_config(path)
        configuration = station_dir / "configuration.json"
        if configuration.is_symlink() or configuration.stat().st_mode & 0o077:
            raise ValueError("Keep native station configuration private and regular.")
        config = StationConfig.model_validate_json(configuration.read_bytes())
        if args.command == "approve-profile":
            files = read_profile_bundle(
                args.directory.resolve(strict=True), args.sha256
            )
            settings = profile_settings(files)
            import json

            machine = json.loads(files["machine.json"])
            if (
                not config.bed_type
                or settings["filamentType"].upper() != args.material
                or settings["nozzleDiameterMm"] != "0.4"
                or "AD5X" not in str(machine.get("name", "")).upper()
            ):
                raise ValueError(
                    "A matching standalone AD5X / 0.4 mm / material profile is required."
                )
            print(
                f"Review this exact commerce bundle, G-code and actual {config.bed_type} plate."
            )
            if (
                input(
                    "After a supervised calibration and profile review, type APPROVE: "
                )
                != "APPROVE"
            ):
                raise ValueError("Not approved.")
            entry = ApprovedProfile(
                profileSha256=args.sha256,
                material=args.material,
                stationBedType=config.bed_type,
            )
            connector_config.approved_profiles = [
                item
                for item in connector_config.approved_profiles
                if item.profile_sha256 != entry.profile_sha256
            ] + [entry]
            save_config(path, connector_config)
            print(
                "Commerce profile approved separately. Native configuration unchanged."
            )
            return
        app = create_app(
            config, station_dir / "jobs", enable_printer=args.enable_printer
        )
        connector = CommerceConnector(app.state.station, connector_config)
        print(
            "Outbound commerce connector running. Do not run the native station concurrently."
        )
        print(
            "Physical starts enabled."
            if args.enable_printer
            else "Physical starts disabled."
        )
        asyncio.run(serve(app, connector, args.port))


if __name__ == "__main__":
    try:
        main()
    except BlockingIOError:
        print(
            "Station is already running. Stop it deliberately before switching runners.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    except (OSError, ValueError, KeyError):
        print(
            "Connector stopped. Check private pairing, reviewed profiles and local paths.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
