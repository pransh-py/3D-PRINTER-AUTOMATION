"""Start the actual local service with private files and dedicated development state.

No payment, model-analysis or production records are fabricated. Configuration and secrets
remain in the ignored .local/service directory. No existing configuration is overwritten.
"""

import argparse
import json
import os
import signal
import subprocess
import sys
from hashlib import file_digest
from pathlib import Path
from secrets import token_urlsafe
from shutil import which
from time import sleep

from pydantic import SecretStr

from xxx_api.config import Settings
from xxx_api.print_presets import load_print_presets

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".local/service"
CONFIG = STATE / "configuration.json"
PYTHON = ROOT / ".venv313/bin/python"
PORTS = {
    "PRINTFLOW_POSTGRES_PORT": "55432",
    "PRINTFLOW_REDIS_PORT": "56379",
    "PRINTFLOW_SMTP_PORT": "51025",
    "PRINTFLOW_MAIL_UI_PORT": "58025",
}


def save_configuration(values: dict[str, object], *, create: bool) -> None:
    settings = Settings(_env_file=None, **values)
    serialized = settings.model_dump(mode="json")
    for name in Settings.model_fields:
        value = getattr(settings, name)
        if isinstance(value, SecretStr):
            serialized[name] = value.get_secret_value()
    if create:
        descriptor = os.open(CONFIG, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            json.dump(serialized, stream, indent=2)
    else:
        temporary = STATE / "configuration.pending.json"
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            json.dump(serialized, stream, indent=2)
        temporary.replace(CONFIG)


def read_configuration() -> dict[str, object]:
    if not CONFIG.is_file() or CONFIG.is_symlink():
        raise ValueError(
            "Run init first. Use the ignored local service configuration only."
        )
    if os.name != "nt" and CONFIG.stat().st_mode & 0o077:
        raise ValueError("Local configuration permissions must be private (0600).")
    values = json.loads(CONFIG.read_text())
    if not isinstance(values, dict):
        raise ValueError("Invalid local configuration.")
    settings = Settings(_env_file=None, **values)
    if settings.environment != "development" or settings.storage_backend != "local":
        raise ValueError(
            "This launcher only operates the isolated local development service."
        )
    if (
        settings.database_url
        != "postgresql+psycopg://xxx:development-postgres@127.0.0.1:55432/xxx"
    ):
        raise ValueError(
            "Refusing to operate a database outside this dedicated local setup."
        )
    return values


def runtime_environment(values: dict[str, object]) -> dict[str, str]:
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("XXX_")
    }
    environment["PRINTFLOW_IGNORE_DOTENV"] = "1"
    for key, value in values.items():
        if value is not None:
            environment[f"XXX_{key.upper()}"] = (
                json.dumps(value)
                if isinstance(value, (list, dict, bool))
                else str(value)
            )
    return environment


def compose(*arguments: str) -> None:
    subprocess.run(
        [
            "docker",
            "compose",
            "--project-name",
            "printflow-local-service",
            "--file",
            str(ROOT / "compose.yaml"),
            *arguments,
        ],
        cwd=ROOT,
        env={**os.environ, **PORTS},
        check=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "init",
        help="create isolated configuration once and start dedicated dependencies",
    )
    commands.add_parser(
        "migrate", help="apply migrations only to this launcher's database"
    )
    run_parser = commands.add_parser(
        "run", help="run the real API, worker and web together"
    )
    run_parser.add_argument(
        "component", choices=["all", "api", "worker", "web"], nargs="?", default="all"
    )
    owner = commands.add_parser(
        "owner", help="provision the actual local owner interactively"
    )
    owner.add_argument("--email", required=True)
    owner.add_argument("--name", required=True)
    profiles = commands.add_parser(
        "profiles", help="configure reviewed standalone slicer offerings"
    )
    profiles.add_argument("--manifest", required=True, type=Path)
    profiles.add_argument("--slicer", required=True, type=Path)
    profiles.add_argument("--version", required=True)
    commands.add_parser("check", help="show non-secret local configuration readiness")
    args = parser.parse_args()
    try:
        if args.command == "init":
            STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
            if not CONFIG.exists():
                save_configuration(
                    {
                        "environment": "development",
                        "app_name": "PrintFlow 3D API",
                        "database_url": "postgresql+psycopg://xxx:development-postgres@127.0.0.1:55432/xxx",
                        "redis_url": "redis://127.0.0.1:56379/0",
                        "storage_backend": "local",
                        "storage_local_directory": str(STATE / "objects"),
                        "public_web_url": "http://127.0.0.1:3100",
                        "allowed_origins": ["http://127.0.0.1:3100"],
                        "jwt_signing_secret": token_urlsafe(48),
                        "token_hash_secret": token_urlsafe(48),
                        "mfa_encryption_secret": token_urlsafe(48),
                        "email_sender_name": "PrintFlow 3D local",
                        "smtp_port": 51025,
                        "analysis_validator_command": str(
                            ROOT / ".venv313/bin/xxx-analyzer"
                        ),
                    },
                    create=True,
                )
            read_configuration()
            compose("up", "-d", "--wait", "postgres", "redis", "mailpit")
            print(
                "Local dependencies ready. Run migrate, then owner, then run. Mail inbox: http://127.0.0.1:58025"
            )
            return
        values = read_configuration()
        environment = runtime_environment(values)
        if args.command == "profiles":
            manifest, binary = args.manifest.resolve(), args.slicer.resolve()
            if not binary.is_file():
                raise ValueError("The reviewed slicer executable does not exist.")
            with binary.open("rb") as stream:
                digest = file_digest(stream, "sha256").hexdigest()
            values.update(
                {
                    "analysis_preset_manifest": str(manifest),
                    "analysis_slicer_command": str(binary),
                    "analysis_slicer_version": args.version,
                    "analysis_slicer_sha256": digest,
                    "analysis_lease_seconds": int(values["max_models_per_quote"])
                    * int(values["analysis_slicer_timeout_seconds"])
                    + 120,
                }
            )
            settings = Settings(_env_file=None, **values)
            presets = load_print_presets(settings)
            save_configuration(values, create=False)
            print(
                f"Configured {len(presets)} reviewed print offerings. Activate matching material rates in Operations, then restart API/worker."
            )
        elif args.command == "check":
            settings = Settings(_env_file=None, **values)
            print(
                json.dumps(
                    {
                        "web": "http://127.0.0.1:3100",
                        "api": "http://127.0.0.1:8011",
                        "privateStorage": "local folder",
                        "configuredPresets": len(load_print_presets(settings)),
                        "razorpayEnabled": settings.razorpay_enabled,
                        "razorpayMode": settings.razorpay_mode,
                        "printerDispatch": False,
                        "scope": "Local configuration only; not hardware, gateway or production acceptance.",
                    },
                    indent=2,
                )
            )
        elif args.command == "migrate":
            subprocess.run(
                [
                    str(PYTHON),
                    "-m",
                    "alembic",
                    "-c",
                    "services/api/alembic.ini",
                    "upgrade",
                    "head",
                ],
                cwd=ROOT,
                env=environment,
                check=True,
            )
        elif args.command == "owner":
            subprocess.run(
                [
                    str(ROOT / ".venv313/bin/xxx-api"),
                    "provision-owner",
                    "--email",
                    args.email,
                    "--display-name",
                    args.name,
                ],
                cwd=ROOT,
                env=environment,
                check=True,
            )
        elif args.command == "run":
            npm = which("npm")
            if not npm:
                raise ValueError(
                    "Install Node/npm before starting the web application."
                )
            children = []
            processes = {
                "api": (
                    [
                        str(PYTHON),
                        "-m",
                        "uvicorn",
                        "xxx_api.main:app",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        "8011",
                    ],
                    environment,
                ),
                "worker": ([str(ROOT / ".venv313/bin/xxx-worker")], environment),
                # Never send API, payment or authentication secrets to the web process.
                "web": (
                    [
                        npm,
                        "--prefix",
                        "apps/web",
                        "run",
                        "dev",
                        "--",
                        "--hostname",
                        "127.0.0.1",
                        "--port",
                        "3100",
                    ],
                    {
                        **{
                            key: value
                            for key, value in os.environ.items()
                            if not key.startswith("XXX_")
                        },
                        "API_INTERNAL_URL": "http://127.0.0.1:8011",
                    },
                ),
            }
            try:
                for name, (command, child_environment) in processes.items():
                    if args.component in {"all", name}:
                        children.append(
                            subprocess.Popen(
                                command,
                                cwd=ROOT,
                                env=child_environment,
                                start_new_session=os.name != "nt",
                            )
                        )
                while all(child.poll() is None for child in children):
                    sleep(0.5)
                raise ValueError("A local service stopped. Review the output above.")
            finally:
                for child in children:
                    if child.poll() is None:
                        if os.name == "nt":
                            child.send_signal(signal.SIGINT)
                        else:
                            os.killpg(child.pid, signal.SIGINT)
                for child in children:
                    try:
                        child.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        if os.name == "nt":
                            child.terminate()
                        else:
                            os.killpg(child.pid, signal.SIGTERM)
                        child.wait(timeout=5)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        # Validation/configuration failures must not print secret-bearing Settings input.
        print(
            f"Local setup stopped ({type(error).__name__}). Check paths, private configuration and service availability.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    except KeyboardInterrupt:
        print(
            "Local service stopped. Its database, private files and configuration are retained."
        )


if __name__ == "__main__":
    main()
