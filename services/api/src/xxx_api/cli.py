"""Deployment-only identity administration commands."""

import argparse
import getpass
import sys
from asyncio import run
from collections.abc import Sequence

from xxx_api.config import get_settings
from xxx_api.database import create_database_engine, create_session_factory
from xxx_api.services.owner_security import (
    InvalidOwnerPasswordError,
    OwnerAccessDeniedError,
    OwnerAlreadyProvisionedError,
    OwnerProvisioningConflictError,
    provision_owner,
    reset_owner_mfa,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="xxx-api")
    commands = parser.add_subparsers(dest="command", required=True)
    provision = commands.add_parser(
        "provision-owner",
        help="create the singleton owner using an interactively entered password",
    )
    provision.add_argument("--email", required=True)
    provision.add_argument("--display-name", required=True)
    reset = commands.add_parser(
        "reset-owner-mfa",
        help="remove owner MFA and revoke every owner session",
    )
    reset.add_argument("--email", required=True)
    return parser


def _confirmed_password(prompt: str, confirmation_prompt: str) -> str:
    password = getpass.getpass(prompt)
    confirmation = getpass.getpass(confirmation_prompt)
    if password != confirmation:
        raise ValueError("passwords do not match")
    return password


async def _provision(email: str, display_name: str, password: str) -> None:
    settings = get_settings()
    engine = create_database_engine(settings)
    sessions = create_session_factory(engine)
    try:
        async with sessions() as session:
            owner_id = await provision_owner(
                session,
                settings,
                email=email,
                display_name=display_name,
                password=password,
            )
        print(f"Primary owner provisioned: {owner_id}")
    finally:
        await engine.dispose()


async def _reset_mfa(email: str, password: str) -> None:
    settings = get_settings()
    engine = create_database_engine(settings)
    sessions = create_session_factory(engine)
    try:
        async with sessions() as session:
            await reset_owner_mfa(
                session,
                settings,
                email=email,
                password=password,
            )
        print("Owner MFA reset; every owner session was revoked.")
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> None:
    """Run one explicit, interactive deployment administration command."""
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "provision-owner":
            password = _confirmed_password("Owner password: ", "Confirm owner password: ")
            run(_provision(arguments.email, arguments.display_name, password))
            return
        confirmation = input("Type RESET to remove owner MFA and revoke every session: ")
        if confirmation != "RESET":
            raise ValueError("MFA reset cancelled")
        password = getpass.getpass("Current owner password: ")
        run(_reset_mfa(arguments.email, password))
    except (
        InvalidOwnerPasswordError,
        OwnerAccessDeniedError,
        OwnerAlreadyProvisionedError,
        OwnerProvisioningConflictError,
        ValueError,
    ) as error:
        reason = str(error) or error.__class__.__name__
        print(f"Owner administration failed: {reason}", file=sys.stderr)
        raise SystemExit(2) from error


if __name__ == "__main__":
    main()
