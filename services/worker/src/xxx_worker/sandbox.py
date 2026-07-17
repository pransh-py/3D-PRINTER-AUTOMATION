"""Explicit subprocess boundary for credential-free model validation."""

from __future__ import annotations

from asyncio import create_subprocess_exec, wait_for
from dataclasses import dataclass
from json import JSONDecodeError, loads
from os import environ
from pathlib import Path
from shutil import which
from subprocess import PIPE
from sysconfig import get_path
from typing import cast

from xxx_worker.validation import ModelFormat, ModelValidationError, ValidationResult

MAX_VALIDATOR_OUTPUT_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class SandboxValidator:
    """Run the trusted validator executable without a shell or application secrets."""

    command: str
    timeout_seconds: int
    sandbox_mode: str = "process"
    bubblewrap_command: str = "bwrap"

    async def validate(
        self,
        source: Path,
        *,
        declared_format: ModelFormat,
        expected_size: int,
        claimed_sha256: str,
        scratch_directory: Path,
    ) -> ValidationResult:
        environment = {
            "PATH": "/usr/bin:/bin",
            "PYTHONHASHSEED": "random",
            "PYTHONNOUSERSITE": "1",
            "TMPDIR": str(scratch_directory),
        }
        if environ.get("SYSTEMROOT"):
            environment["SYSTEMROOT"] = environ["SYSTEMROOT"]
        executable = self.command if Path(self.command).is_absolute() else which(self.command)
        if executable is None:
            environment_script = Path(get_path("scripts")) / self.command
            if environment_script.is_file():
                executable = str(environment_script)
        if executable is None:
            raise ModelValidationError("worker_internal")
        command = self._isolated_command(executable, scratch_directory)
        process = await create_subprocess_exec(
            *command,
            str(source),
            "--declared-format",
            declared_format,
            "--expected-size",
            str(expected_size),
            "--claimed-sha256",
            claimed_sha256,
            cwd=scratch_directory,
            env=environment,
            stdin=PIPE,
            stdout=PIPE,
            stderr=PIPE,
        )
        try:
            stdout, stderr = await wait_for(
                process.communicate(),
                timeout=self.timeout_seconds,
            )
        except TimeoutError:
            process.kill()
            await process.wait()
            raise ModelValidationError("validator_timeout") from None
        if len(stdout) > MAX_VALIDATOR_OUTPUT_BYTES or len(stderr) > MAX_VALIDATOR_OUTPUT_BYTES:
            raise ModelValidationError("validator_output_invalid")
        if process.returncode == 2:
            raise ModelValidationError(_failure_code(stderr))
        if process.returncode != 0:
            raise ModelValidationError("worker_internal")
        return _validation_result(stdout)

    def _isolated_command(
        self,
        validator_executable: str,
        scratch_directory: Path,
    ) -> tuple[str, ...]:
        if self.sandbox_mode == "process":
            return (validator_executable,)
        if self.sandbox_mode != "bubblewrap":
            raise ModelValidationError("worker_internal")
        wrapper = (
            self.bubblewrap_command
            if Path(self.bubblewrap_command).is_absolute()
            else which(self.bubblewrap_command)
        )
        if wrapper is None:
            raise ModelValidationError("worker_internal")
        return (
            wrapper,
            "--die-with-parent",
            "--new-session",
            "--unshare-net",
            "--unshare-pid",
            "--unshare-ipc",
            "--unshare-uts",
            "--ro-bind",
            "/",
            "/",
            "--bind",
            str(scratch_directory),
            str(scratch_directory),
            "--chdir",
            str(scratch_directory),
            "--",
            validator_executable,
        )


def _json_object(data: bytes) -> dict[str, object]:
    try:
        value = loads(data)
    except (UnicodeError, JSONDecodeError) as error:
        raise ModelValidationError("validator_output_invalid") from error
    if not isinstance(value, dict):
        raise ModelValidationError("validator_output_invalid")
    return cast(dict[str, object], value)


def _failure_code(stderr: bytes) -> str:
    payload = _json_object(stderr)
    if set(payload) != {"status", "failureCode"} or payload.get("status") != "rejected":
        raise ModelValidationError("validator_output_invalid")
    code = payload.get("failureCode")
    if not isinstance(code, str) or not code or len(code) > 64:
        raise ModelValidationError("validator_output_invalid")
    return code


def _optional_nonnegative_int(value: object) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ModelValidationError("validator_output_invalid")
    return value


def _validation_result(stdout: bytes) -> ValidationResult:
    payload = _json_object(stdout)
    expected_fields = {
        "detected_format",
        "dimensions_um",
        "fits_build_volume",
        "object_count",
        "size_bytes",
        "status",
        "triangle_count",
        "verified_sha256",
        "warning_codes",
    }
    if set(payload) != expected_fields or payload.get("status") != "validated":
        raise ModelValidationError("validator_output_invalid")
    detected_format = payload["detected_format"]
    if detected_format not in {"stl", "3mf", "obj", "step"}:
        raise ModelValidationError("validator_output_invalid")
    digest = payload["verified_sha256"]
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise ModelValidationError("validator_output_invalid")
    dimensions_value = payload["dimensions_um"]
    dimensions = None
    if dimensions_value is not None:
        if not isinstance(dimensions_value, list) or len(dimensions_value) != 3:
            raise ModelValidationError("validator_output_invalid")
        parsed_dimensions = tuple(_optional_nonnegative_int(value) for value in dimensions_value)
        if any(value is None for value in parsed_dimensions):
            raise ModelValidationError("validator_output_invalid")
        dimensions = cast(tuple[int, int, int], parsed_dimensions)
    fit = payload["fits_build_volume"]
    if fit is not None and not isinstance(fit, bool):
        raise ModelValidationError("validator_output_invalid")
    warnings = payload["warning_codes"]
    if (
        not isinstance(warnings, list)
        or len(warnings) > 32
        or any(not isinstance(code, str) or not code or len(code) > 64 for code in warnings)
    ):
        raise ModelValidationError("validator_output_invalid")
    size_bytes = _optional_nonnegative_int(payload["size_bytes"])
    if size_bytes is None or size_bytes < 1:
        raise ModelValidationError("validator_output_invalid")
    return ValidationResult(
        detected_format=cast(ModelFormat, detected_format),
        verified_sha256=digest,
        size_bytes=size_bytes,
        dimensions_um=dimensions,
        triangle_count=_optional_nonnegative_int(payload["triangle_count"]),
        object_count=_optional_nonnegative_int(payload["object_count"]),
        fits_build_volume=cast(bool | None, fit),
        warning_codes=tuple(cast(list[str], warnings)),
    )
