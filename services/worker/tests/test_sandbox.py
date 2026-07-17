"""Real subprocess-boundary tests for the installed validator command."""

from asyncio import run
from hashlib import sha256
from pathlib import Path
from struct import Struct, pack

import pytest

from xxx_worker.sandbox import SandboxValidator
from xxx_worker.validation import ModelValidationError

TRIANGLE = Struct("<12fH")


def _binary_stl() -> bytes:
    return (
        b"sandbox fixture".ljust(80, b" ")
        + pack("<I", 1)
        + TRIANGLE.pack(
            0.0,
            0.0,
            1.0,
            0.0,
            0.0,
            0.0,
            1.0,
            0.0,
            0.0,
            0.0,
            1.0,
            0.0,
            0,
        )
    )


def test_sandbox_runs_installed_validator_with_scrubbed_environment(tmp_path: Path) -> None:
    async def scenario() -> None:
        data = _binary_stl()
        source = tmp_path / "source"
        source.write_bytes(data)
        validator = SandboxValidator(command="xxx-analyzer", timeout_seconds=5)

        result = await validator.validate(
            source,
            declared_format="stl",
            expected_size=len(data),
            claimed_sha256=sha256(data).hexdigest(),
            scratch_directory=tmp_path,
        )

        assert result.detected_format == "stl"
        assert result.dimensions_um == (1000, 1000, 0)
        assert result.verified_sha256 == sha256(data).hexdigest()

    run(scenario())


def test_sandbox_returns_only_stable_rejection_code(tmp_path: Path) -> None:
    async def scenario() -> None:
        source = tmp_path / "source"
        source.write_bytes(b"not an stl")
        validator = SandboxValidator(command="xxx-analyzer", timeout_seconds=5)

        with pytest.raises(ModelValidationError) as error:
            await validator.validate(
                source,
                declared_format="stl",
                expected_size=source.stat().st_size,
                claimed_sha256=sha256(source.read_bytes()).hexdigest(),
                scratch_directory=tmp_path,
            )

        assert error.value.code == "stl_signature_invalid"
        assert str(tmp_path) not in str(error.value)

    run(scenario())
