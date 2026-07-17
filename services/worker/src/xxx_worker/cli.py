"""Credential-free JSON command for the model-validation sandbox."""

from __future__ import annotations

from argparse import ArgumentParser
from dataclasses import asdict
from json import dumps
from pathlib import Path
from sys import stderr
from typing import cast

from xxx_worker.validation import ModelFormat, ModelValidationError, validate_model


def _parser() -> ArgumentParser:
    parser = ArgumentParser(prog="xxx-analyzer")
    parser.add_argument("source", type=Path)
    parser.add_argument(
        "--declared-format",
        required=True,
        choices=("stl", "3mf", "obj", "step"),
    )
    parser.add_argument("--expected-size", required=True, type=int)
    parser.add_argument("--claimed-sha256", required=True)
    return parser


def main() -> None:
    """Emit one bounded JSON result or one stable failure code."""
    args = _parser().parse_args()
    try:
        result = validate_model(
            args.source,
            cast(ModelFormat, args.declared_format),
        )
        if result.size_bytes != args.expected_size:
            raise ModelValidationError("size_mismatch")
        if result.verified_sha256 != args.claimed_sha256:
            raise ModelValidationError("digest_mismatch")
    except ModelValidationError as error:
        print(dumps({"status": "rejected", "failureCode": error.code}), file=stderr)
        raise SystemExit(2) from None
    payload = asdict(result)
    payload["status"] = "validated"
    print(dumps(payload, separators=(",", ":"), sort_keys=True))


if __name__ == "__main__":
    main()
