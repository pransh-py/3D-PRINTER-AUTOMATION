"""Local-only upload / slice / AD5X station. No Docker, accounts or payments."""

import argparse
import fcntl
import getpass
import json
import os
import signal
import subprocess
import sys
from decimal import Decimal, InvalidOperation
from hashlib import file_digest
from pathlib import Path
from typing import Literal

import uvicorn
from pydantic import SecretStr

# Direct script execution places tools/, not the repository root, on sys.path.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from xxx_api.print_presets import read_profile_bundle  # noqa: E402

from services.bridge.ad5x_lan import AD5XLan, PrinterError  # noqa: E402
from services.bridge.moonraker_lan import MoonrakerLan  # noqa: E402
from services.bridge.print_station import (  # noqa: E402
    Connection,
    Journal,
    Mapping,
    Profile,
    StationConfig,
    StationPricing,
    create_app,
    estimate_slice,
)

DIRECTORY = ROOT / ".local" / "print-station"
CONFIG = DIRECTORY / "configuration.json"


def write_config(value):
    DIRECTORY.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (DIRECTORY / "station.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _persist_config(value)


def _persist_config(value):
    temporary = DIRECTORY / "configuration.new"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        serialized = value.model_dump(mode="json")
        if value.printer:
            serialized["printer"]["serial"] = value.printer.serial.get_secret_value()
            serialized["printer"]["check_code"] = value.printer.check_code.get_secret_value()
            serialized["printer"]["api_key"] = value.printer.api_key.get_secret_value()
        stream.write(json.dumps(serialized, indent=2))
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(CONFIG)


def read_config():
    if CONFIG.is_symlink() or not CONFIG.is_file():
        raise ValueError("Use a regular private station configuration file.")
    if CONFIG.stat().st_mode & 0o077:
        raise ValueError("Keep the station configuration private (chmod 600).")
    return StationConfig.model_validate_json(CONFIG.read_bytes())


def rupees_to_paise(value):
    try:
        amount = Decimal(value)
        if not amount.is_finite() or not 0 <= amount <= 10_000_000:
            raise ValueError
        paise = amount * 100
        if paise != paise.to_integral_value():
            raise ValueError
        return int(paise)
    except (InvalidOperation, ValueError):
        raise argparse.ArgumentTypeError(
            "Use non-negative rupees with up to two decimals."
        ) from None


def main():
    global DIRECTORY, CONFIG
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--directory",
        type=Path,
        default=DIRECTORY,
        help="Private station state directory (use the Linux filesystem under WSL).",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser(
        "init", help="Pin a slicer and standalone base profiles; starts disabled."
    )
    init.add_argument("--slicer", required=True, type=Path)
    init.add_argument("--version", required=True)
    init.add_argument("--pla-manifest", required=True, type=Path)
    init.add_argument("--petg-manifest", type=Path)
    init.add_argument("--web-port", type=int, default=3102)
    rates = commands.add_parser("rates", help="Set material/time rates for slicing estimates.")
    rates.add_argument("--filament-per-gram", type=rupees_to_paise, required=True)
    rates.add_argument("--printing-per-hour", type=rupees_to_paise, required=True)
    rates.add_argument(
        "--include-existing",
        action="store_true",
        help="Estimate already-sliced jobs that have no estimate; preserve previous estimates.",
    )
    plate = commands.add_parser(
        "plate", help="Select a build-plate type; revokes physical approvals."
    )
    plate.add_argument(
        "--type", required=True, choices=["Textured PEI Plate", "High Temp Plate", "Cool Plate"]
    )
    profiles_command = commands.add_parser(
        "profile", help="Pin a new base profile; revokes its physical approval."
    )
    profiles_command.add_argument("--material", choices=["PLA", "PETG"], required=True)
    profiles_command.add_argument("--manifest", type=Path, required=True)
    slicer_command = commands.add_parser(
        "slicer", help="Pin a reviewed local executable; revokes physical approvals."
    )
    slicer_command.add_argument("--slicer", required=True, type=Path)
    slicer_command.add_argument("--version", required=True)
    connect = commands.add_parser(
        "connect", help="Save printer LAN credentials privately, then read status only."
    )
    connect.add_argument("--host", required=True)
    connect.add_argument("--transport", choices=["moonraker", "flashforge"], default="moonraker")
    mapping = commands.add_parser(
        "map", help="Map an offered colour to an observed loaded IFS slot."
    )
    mapping.add_argument("--material", choices=["PLA", "PETG"], required=True)
    mapping.add_argument("--colour", required=True)
    mapping.add_argument("--slot", type=int, choices=[1, 2, 3, 4], required=True)
    mapping.add_argument("--hex", help="Exact colour from the ZMOD COLOR screen, e.g. '#FFFFFF'.")
    commands.add_parser(
        "approve-zmod",
        help="Record ZMOD auto-colour/silent-start review; changes no printer settings.",
    )
    approve = commands.add_parser(
        "approve-profile", help="Record physical profile review; no command is sent."
    )
    approve.add_argument("--material", choices=["PLA", "PETG"], required=True)
    commands.add_parser("probe", help="Read live printer status; never upload or start.")
    run = commands.add_parser(
        "run", help="Open the local station; slicing-only unless explicitly enabled."
    )
    run.add_argument("--enable-printer", action="store_true")
    run.add_argument("--api-only", action="store_true")
    run.add_argument(
        "--optimized-web", action="store_true", help="Use an existing station-mode Next build."
    )
    args = parser.parse_args()
    DIRECTORY = args.directory.expanduser().resolve()
    CONFIG = DIRECTORY / "configuration.json"
    if args.command == "init":
        if CONFIG.exists():
            raise ValueError("A configuration already exists. Preserve it; do not reinitialize.")
        profiles: dict[Literal["PLA", "PETG"], Profile] = {}
        for material, manifest in (
            ("PLA", args.pla_manifest),
            ("PETG", args.petg_manifest),
        ):
            if manifest:
                entries = json.loads(manifest.read_bytes())
                if not isinstance(entries, list) or len(entries) != 1:
                    raise ValueError("Select one standalone base profile per material.")
                entry = entries[0]
                profile = Profile(
                    directory=entry["profileDirectory"], sha256=entry["profileSha256"]
                )
                read_profile_bundle(profile.directory, profile.sha256)
                profiles["PLA" if material == "PLA" else "PETG"] = profile
        slicer = args.slicer.resolve(strict=True)
        with slicer.open("rb") as stream:
            digest = file_digest(stream, "sha256").hexdigest()
        write_config(
            StationConfig(
                slicer=slicer,
                slicer_sha256=digest,
                slicer_version=args.version,
                profiles=profiles,
                web_port=args.web_port,
            )
        )
        print("Private station initialized. Starts disabled. Review profiles before physical use.")
        return
    config = read_config()
    if args.command == "rates":
        config.pricing = StationPricing(
            material_rate_paise_per_gram=args.filament_per_gram,
            machine_rate_paise_per_hour=args.printing_per_hour,
        )
        # Hold the station lock across configuration and the optional one-time backfill.
        with (DIRECTORY / "station.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            _persist_config(config)
            count = 0
            journal_path = DIRECTORY / "jobs" / "jobs.sqlite3"
            if args.include_existing and journal_path.is_file():
                journal = Journal(journal_path)
                for job in journal.all():
                    if (
                        not job.get("estimate")
                        and job.get("package_sha256")
                        and job.get("filament_mg", 0) > 0
                        and job.get("duration_seconds", 0) > 0
                    ):
                        journal.update(
                            job["id"],
                            estimate=estimate_slice(
                                config.pricing, job["filament_mg"], job["duration_seconds"]
                            ),
                        )
                        count += 1
        print(f"Material/time estimate rates saved; {count} existing jobs estimated.")
        return
    driver: AD5XLan | MoonrakerLan
    if args.command == "plate":
        config.bed_type = args.type
        for profile in config.profiles.values():
            profile.approved_for_printer = False
        if config.printer:
            config.printer.zmod_start_reviewed = False
        write_config(config)
        print("Plate selected. Approvals revoked. Verify it matches the printer before approval.")
        return
    if args.command == "profile":
        entries = json.loads(args.manifest.read_bytes())
        if not isinstance(entries, list) or len(entries) != 1:
            raise ValueError("Select one standalone base profile.")
        entry = entries[0]
        profile = Profile(directory=entry["profileDirectory"], sha256=entry["profileSha256"])
        read_profile_bundle(profile.directory, profile.sha256)
        config.profiles[args.material] = profile
        if config.printer:
            config.printer.zmod_start_reviewed = False
        write_config(config)
        print("Base profile pinned. Physical approval revoked. Restart the station after review.")
        return
    if args.command == "slicer":
        executable = args.slicer.resolve(strict=True)
        with executable.open("rb") as stream:
            config.slicer_sha256 = file_digest(stream, "sha256").hexdigest()
        config.slicer = executable
        config.slicer_version = args.version
        for profile in config.profiles.values():
            profile.approved_for_printer = False
        if config.printer:
            config.printer.zmod_start_reviewed = False
        write_config(config)
        print("Slicer pinned. Physical approvals revoked. Restart the station after review.")
        return
    if args.command == "connect":
        if args.transport == "moonraker":
            api_key = getpass.getpass(
                "Moonraker API key (hidden; empty if trusted LAN access is configured): "
            )
            connection = Connection(
                host=args.host, transport="moonraker", api_key=SecretStr(api_key)
            )
            driver = MoonrakerLan(args.host, api_key)
        else:
            serial = getpass.getpass("Printer serial / ID (hidden): ")
            code = getpass.getpass("LAN check/access code (hidden): ")
            connection = Connection(
                host=args.host,
                transport="flashforge",
                serial=SecretStr(serial),
                check_code=SecretStr(code),
            )
            driver = AD5XLan(args.host, serial, code)
        status = driver.status()
        config.printer = connection
        write_config(config)
        print(f"AD5X connected: firmware {status.firmware}, state {status.state}. No print sent.")
        return
    if args.command in {"probe", "map"}:
        if config.printer is None:
            raise ValueError(
                "Run connect first. Credentials belong in this local configuration, not chat."
            )
        printer = config.printer
        driver = (
            MoonrakerLan(printer.host, printer.api_key.get_secret_value())
            if printer.transport == "moonraker"
            else AD5XLan(
                printer.host,
                printer.serial.get_secret_value(),
                printer.check_code.get_secret_value(),
            )
        )
        status = driver.status()
        if args.command == "probe":
            print(f"AD5X: firmware={status.firmware}, state={status.state}, error={status.error}")
            for slot in status.slots:
                print(
                    f"IFS slot {slot.number}: {slot.material} {slot.colour_hex}, "
                    f"loaded={slot.loaded}"
                )
        else:
            from services.bridge.print_station import STOCK

            if args.colour not in STOCK[args.material]:
                raise ValueError("Select a confirmed offered material/colour.")
            slot = next((slot for slot in status.slots if slot.number == args.slot), None)
            if printer.transport == "moonraker":
                from services.bridge.ad5x_lan import Slot

                colour = Mapping(slot=args.slot, colour_hex=args.hex).colour_hex
                slot = Slot(args.slot, args.material, colour, True)
                print(
                    "Moonraker cannot verify IFS colours. Inspect ZMOD COLOR and the actual spool."
                )
            if slot is None or not slot.loaded or slot.material != args.material:
                raise ValueError("That slot does not report the selected loaded material.")
            if (
                input(
                    f"Confirm slot {slot.number}: {args.material} {args.colour} "
                    f"({slot.colour_hex}). Type MAP: "
                )
                != "MAP"
            ):
                raise ValueError("Mapping not confirmed.")
            printer.mappings[f"{args.material}:{args.colour}"] = Mapping(
                slot=slot.number, colour_hex=slot.colour_hex
            )
            write_config(config)
            print("Mapping saved. Slot material/colour are checked again for every print.")
        return
    if args.command == "approve-zmod":
        if not config.printer or config.printer.transport != "moonraker":
            raise ValueError("Connect the ZMOD/Moonraker printer first.")
        print(
            "Review the installed ZMOD version and known-working Orca profile. In ZMOD, verify "
            "SCAN_FILE_COLORS=1, AUTO_ASSIGN_COLORS=30 and SILENT=1 with the owner; test that "
            "single-material matching and an immediate start work. Do NOT change purge, "
            "screen or safety settings blindly. This command only records your review."
        )
        if input("After a supervised successful ZMOD test, type REVIEWED: ") != "REVIEWED":
            raise ValueError("ZMOD start not reviewed.")
        config.printer.zmod_start_reviewed = True
        write_config(config)
        print("ZMOD review recorded. No printer command was sent.")
        return
    if args.command == "approve-profile":
        if config.bed_type is None:
            raise ValueError("Select the actual build plate first.")
        profile = config.profiles[args.material]
        read_profile_bundle(profile.directory, profile.sha256)
        print(
            f"Verify the actual plate is {config.bed_type}. Review every file in "
            f"{profile.directory}, the 0.4 mm AD5X nozzle, filament "
            "temperatures, start/end G-code, speeds, supports and the three allowed layer "
            "heights. Use a supervised calibration print in Orca first."
        )
        if input("After that review, type APPROVE: ") != "APPROVE":
            raise ValueError("Profile not approved.")
        profile.approved_for_printer = True
        write_config(config)
        print("Profile approval recorded. This command did not print anything.")
        return
    # One process owns this physical station. The journal additionally enforces one active job.
    with (DIRECTORY / "station.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        app = create_app(config, DIRECTORY / "jobs", enable_printer=args.enable_printer)
        web = None
        try:
            if not args.api_only:
                environment = {**os.environ, "PRINTFLOW_PRINT_STATION": "1"}
                web = subprocess.Popen(
                    [
                        "npm",
                        "run",
                        "start" if args.optimized_web else "dev",
                        "--",
                        "--hostname",
                        "127.0.0.1",
                        "--port",
                        str(config.web_port),
                    ],
                    cwd=ROOT / "apps" / "web",
                    env=environment,
                    start_new_session=True,
                )
            print(f"Local print station: http://127.0.0.1:{config.web_port}/print")
            print(
                "PHYSICAL STARTS ENABLED"
                if args.enable_printer
                else "SLICING ONLY — no printer starts"
            )
            uvicorn.run(
                app,
                host="127.0.0.1",
                port=8123,
                workers=1,
                access_log=False,
                proxy_headers=False,
            )
        finally:
            if web and web.poll() is None:
                os.killpg(web.pid, signal.SIGTERM)
                try:
                    web.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(web.pid, signal.SIGKILL)
                    web.wait()


if __name__ == "__main__":
    try:
        main()
    except PrinterError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from None
    except BlockingIOError:
        print("Stop the running print station before changing its configuration.", file=sys.stderr)
        raise SystemExit(1) from None
    except (ValueError, OSError, KeyError) as error:
        # Never serialize configuration or credentials into errors.
        print(
            f"Station setup stopped: {type(error).__name__}. Check local configuration and paths.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
