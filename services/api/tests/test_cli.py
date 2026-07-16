"""Deployment identity CLI input-boundary tests."""

import pytest

from xxx_api import cli


def test_provision_owner_reads_matching_passwords_interactively(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    supplied = iter(["correct horse battery staple", "correct horse battery staple"])
    captured: dict[str, str] = {}

    async def fake_provision(email: str, display_name: str, password: str) -> None:
        captured.update(email=email, display_name=display_name, password=password)

    monkeypatch.setattr(cli.getpass, "getpass", lambda _prompt: next(supplied))
    monkeypatch.setattr(cli, "_provision", fake_provision)

    cli.main(
        [
            "provision-owner",
            "--email",
            "owner@example.com",
            "--display-name",
            "Owner",
        ]
    )

    assert captured == {
        "email": "owner@example.com",
        "display_name": "Owner",
        "password": "correct horse battery staple",
    }


def test_provision_owner_rejects_mismatched_passwords(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    supplied = iter(["correct horse battery staple", "different secure password"])
    monkeypatch.setattr(cli.getpass, "getpass", lambda _prompt: next(supplied))

    with pytest.raises(SystemExit) as raised:
        cli.main(
            [
                "provision-owner",
                "--email",
                "owner@example.com",
                "--display-name",
                "Owner",
            ]
        )

    assert raised.value.code == 2
