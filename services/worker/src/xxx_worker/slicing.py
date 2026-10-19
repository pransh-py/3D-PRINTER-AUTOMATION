"""Headless Orca execution with pinned owner profiles and measured output only."""

import re
from asyncio import CancelledError, create_subprocess_exec, wait_for
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from hashlib import file_digest, sha256
from pathlib import Path
from subprocess import DEVNULL
from sys import executable as python_executable
from zipfile import BadZipFile, ZipFile

from xxx_api.config import Settings
from xxx_api.print_presets import PresetConfigurationError, read_profile_bundle

from xxx_worker.validation import ModelValidationError


@dataclass(frozen=True)
class SliceResult:
    artifact: Path
    artifact_sha256: str
    filament_mg: int
    duration_seconds: int
    profile_sha256: str
    preview: Path | None = None


def gcode_metrics(data: bytes) -> tuple[int, int]:
    """Require Orca's measured mass and normal-mode duration; never infer either."""
    text = data.decode("utf-8", errors="strict")
    mass = re.search(
        r"^;\s*(?:total )?filament used \[g\]\s*=\s*([0-9.,; ]+)\s*$", text, re.MULTILINE
    )
    duration = re.search(
        r"^;\s*estimated printing time \(normal mode\)\s*=\s*([^\r\n]+)", text, re.MULTILINE
    )
    if mass is None or duration is None:
        raise ModelValidationError("slicer_metrics_missing")
    try:
        grams = sum((Decimal(value.strip()) for value in re.split(r"[,;]", mass[1])), Decimal(0))
        if not grams.is_finite() or grams <= 0:
            raise ValueError
        filament_mg = int((grams * 1000).to_integral_value(rounding=ROUND_CEILING))
    except (InvalidOperation, ValueError) as error:
        raise ModelValidationError("slicer_metrics_invalid") from error
    tokens = re.findall(r"(\d+)\s*([dhms])", duration[1])
    if not tokens or re.sub(r"\d+\s*[dhms]|\s", "", duration[1]):
        raise ModelValidationError("slicer_metrics_invalid")
    seconds = sum(
        int(value) * {"d": 86400, "h": 3600, "m": 60, "s": 1}[unit] for value, unit in tokens
    )
    if not 0 < seconds <= 30 * 86400 or not 0 < filament_mg <= 100_000_000:
        raise ModelValidationError("slicer_metrics_invalid")
    return filament_mg, seconds


def copy_profiles(settings: Settings, scratch: Path) -> str:
    if settings.analysis_profile_directory is None or settings.analysis_profile_sha256 is None:
        raise ModelValidationError("slicer_profile_unavailable")
    try:
        files = read_profile_bundle(
            settings.analysis_profile_directory, settings.analysis_profile_sha256
        )
    except PresetConfigurationError as error:
        raise ModelValidationError(error.code) from error
    for filename, data in files.items():
        (scratch / filename).write_bytes(data)
    return settings.analysis_profile_sha256


class OrcaSlicer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def slice(self, source: Path, scratch: Path, *, quantity: int = 1) -> SliceResult:
        if type(quantity) is not int or not 1 <= quantity <= 10:
            raise ModelValidationError("slicer_quantity_invalid")
        settings = self.settings
        executable = settings.analysis_slicer_command
        if executable is None or not executable.is_file():
            raise ModelValidationError("slicer_unavailable")
        with executable.open("rb") as binary:
            if file_digest(binary, "sha256").hexdigest() != settings.analysis_slicer_sha256:
                raise ModelValidationError("slicer_unavailable")
        profile_hash = copy_profiles(settings, scratch)
        command = [
            str(executable),
            "--load-settings",
            f"{scratch / 'machine.json'};{scratch / 'process.json'}",
            "--load-filaments",
            str(scratch / "filament.json"),
            "--skip-modified-gcodes",
            "--slice",
            "0",
            "--export-3mf",
            str(scratch / "result.3mf"),
            str(source),
        ]
        if quantity > 1:
            if source.suffix.lower() not in {".stl", ".obj"}:
                raise ModelValidationError("slicer_quantity_invalid")
            # Repetitions only works on saved Orca plates, not raw STL/OBJ input.
            # Clone the single input model before arranging and slicing all plates;
            # the output gate below rejects anything requiring more than one plate.
            command[1:1] = ["--clone-objects", str(quantity), "--arrange", "1"]
        launcher = Path(__file__).with_name("slicer_launcher.py")
        python = str(Path(python_executable).resolve())
        command = [python, str(launcher), str(settings.analysis_slicer_timeout_seconds), *command]
        if settings.analysis_sandbox_mode == "bubblewrap":
            if executable.parent in {
                Path("/"),
                Path("/opt"),
                Path("/home"),
                Path("/Users"),
                Path("/etc"),
            }:
                raise ModelValidationError("slicer_unavailable")
            # No application files or credentials are mounted in the slicer namespace.
            mounts = [
                str(path) for path in (Path("/usr"), Path("/lib"), Path("/lib64")) if path.exists()
            ]
            wrapper = [
                settings.analysis_bubblewrap_command,
                "--die-with-parent",
                "--new-session",
                "--unshare-all",
                "--proc",
                "/proc",
                "--dev",
                "/dev",
                "--tmpfs",
                "/tmp",
                "--ro-bind",
                str(launcher),
                "/slicer_launcher.py",
            ]
            for mount in mounts:
                wrapper.extend(["--ro-bind", mount, mount])
            if not str(executable).startswith("/usr/"):
                wrapper.extend(["--ro-bind", str(executable.parent), str(executable.parent)])
            command[1] = "/slicer_launcher.py"
            wrapper.extend(["--bind", str(scratch), str(scratch), "--chdir", str(scratch), "--"])
            command = wrapper + command
        process = await create_subprocess_exec(
            *command,
            cwd=scratch,
            env={"PATH": "/usr/bin:/bin", "HOME": str(scratch), "TMPDIR": str(scratch)},
            stdin=DEVNULL,
            stdout=DEVNULL,
            stderr=DEVNULL,
        )
        try:
            await wait_for(process.wait(), settings.analysis_slicer_timeout_seconds)
        except CancelledError:
            if process.returncode is None:
                process.kill()
            await process.wait()
            raise
        except TimeoutError:
            process.kill()
            await process.wait()
            raise ModelValidationError("slicer_timeout") from None
        if process.returncode != 0:
            raise ModelValidationError("slicer_failed")
        package = scratch / "result.3mf"
        if not package.is_file() or package.stat().st_size > 200 * 1024 * 1024:
            raise ModelValidationError("slicer_output_invalid")
        try:
            with ZipFile(package) as archive:
                entries = archive.infolist()
                if len(entries) > 512:
                    raise ModelValidationError("slicer_output_invalid")
                gcodes = [
                    entry
                    for entry in entries
                    if re.fullmatch(r"Metadata/plate_\d+\.gcode", entry.filename)
                ]
                if len(gcodes) != 1 or not 0 < gcodes[0].file_size <= 200 * 1024 * 1024:
                    raise ModelValidationError("slicer_multiple_plates_unsupported")
                data = archive.read(gcodes[0])
                filament_mg, duration = gcode_metrics(data)
                artifact = scratch / "approved.gcode"
                artifact.write_bytes(data)
                preview = None
                thumbnail = next(
                    (entry for entry in entries if entry.filename == "Metadata/plate_1.png"), None
                )
                if thumbnail and 0 < thumbnail.file_size <= 2 * 1024 * 1024:
                    preview_data = archive.read(thumbnail)
                    if (
                        len(preview_data) >= 24
                        and preview_data.startswith(b"\x89PNG\r\n\x1a\n")
                        and preview_data[12:16] == b"IHDR"
                        and 0 < int.from_bytes(preview_data[16:20], "big") <= 4096
                        and 0 < int.from_bytes(preview_data[20:24], "big") <= 4096
                    ):
                        preview = scratch / "preview.png"
                        preview.write_bytes(preview_data)
        except (BadZipFile, UnicodeError, OSError) as error:
            raise ModelValidationError("slicer_output_invalid") from error
        return SliceResult(
            artifact, sha256(data).hexdigest(), filament_mg, duration, profile_hash, preview
        )
