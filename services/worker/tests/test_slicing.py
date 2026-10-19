"""Measured slicing metadata must not be replaced with guessed numbers."""

from asyncio import run
from hashlib import sha256
from pathlib import Path
from sys import executable

import pytest
from xxx_api.config import Settings

from xxx_worker.slicing import OrcaSlicer, gcode_metrics
from xxx_worker.validation import ModelValidationError


def test_orca_metrics_use_integer_units_and_all_filaments() -> None:
    mass, seconds = gcode_metrics(
        b"; filament used [g] = 1.001, 2.500\n"
        b"; estimated printing time (normal mode) = 1h 2m 3s\nG1 X1\n"
    )
    assert mass == 3501
    assert seconds == 3723


@pytest.mark.parametrize(
    "payload",
    [
        b"G1 X1\n",
        b"; filament used [g] = 0\n; estimated printing time (normal mode) = 2m\n",
        b"; filament used [g] = 1\n; estimated printing time (normal mode) = unknown\n",
    ],
)
def test_missing_or_invalid_metrics_fail_closed(payload: bytes) -> None:
    with pytest.raises(ModelValidationError):
        gcode_metrics(payload)


def fixture_settings(tmp_path: Path, *, measured: bool = True) -> Settings:
    """Exercise the real subprocess/zip boundary, not real Orca geometry or hardware."""
    profile = tmp_path / "profiles"
    profile.mkdir()
    digest = sha256()
    for name in ("machine.json", "process.json", "filament.json"):
        data = b'{"fixtureOnly":true}'
        (profile / name).write_bytes(data)
        digest.update(name.encode() + b"\0" + data)
    binary = tmp_path / "fixture-orca"
    metrics = (
        b"; filament used [g] = 12.500\n; estimated printing time (normal mode) = 30m\n"
        if measured
        else b"; no measured metrics\n"
    )
    script = (
        f"#!{executable}\nimport os,sys,zipfile,json\n"
        "with open('invocation.json','w') as output: json.dump(sys.argv,output)\n"
        "assert not any(key.startswith('XXX_') for key in os.environ)\n"
        "assert '--skip-modified-gcodes' in sys.argv\n"
        "if '--clone-objects' in sys.argv:\n"
        "    assert sys.argv[sys.argv.index('--clone-objects')+1]=='2'\n"
        "    assert '--repetitions' not in sys.argv\n"
        "    assert sys.argv[sys.argv.index('--slice')+1]=='0'\n"
        "target=sys.argv[sys.argv.index('--export-3mf')+1]\n"
        "with zipfile.ZipFile(target,'w') as archive:\n"
        f"    archive.writestr('Metadata/plate_1.gcode',{metrics!r})\n"
    )
    binary.write_text(script)
    binary.chmod(0o700)
    return Settings(
        _env_file=None,
        environment="test",
        analysis_slicer_command=binary,
        analysis_slicer_version="LAB ONLY subprocess fixture",
        analysis_slicer_sha256=sha256(binary.read_bytes()).hexdigest(),
        analysis_profile_directory=profile,
        analysis_profile_sha256=digest.hexdigest(),
        analysis_material_code="lab-pla",
        analysis_slicer_timeout_seconds=10,
    )


@pytest.mark.parametrize("quantity", [1, 2])
def test_pinned_subprocess_exports_measured_artifact_without_credentials(
    tmp_path, monkeypatch, quantity
):
    settings = fixture_settings(tmp_path)
    monkeypatch.setenv("XXX_TEST_SECRET", "must-not-reach-child")
    source = tmp_path / "source.stl"
    source.write_bytes(b"LAB ONLY input transport fixture")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    output = run(OrcaSlicer(settings).slice(source, scratch, quantity=quantity))
    import json

    invocation = json.loads((scratch / "invocation.json").read_text())
    assert ("--clone-objects" in invocation) == (quantity > 1)
    assert (output.filament_mg, output.duration_seconds) == (12500, 1800)
    assert sha256(output.artifact.read_bytes()).hexdigest() == output.artifact_sha256
    assert output.profile_sha256 == settings.analysis_profile_sha256


def test_changed_profile_and_missing_metrics_fail_closed(tmp_path):
    settings = fixture_settings(tmp_path, measured=False)
    source = tmp_path / "source.stl"
    source.write_bytes(b"fixture")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    with pytest.raises(ModelValidationError, match="slicer_metrics_missing"):
        run(OrcaSlicer(settings).slice(source, scratch))
    (settings.analysis_profile_directory / "machine.json").write_bytes(b'{"changed":true}')
    with pytest.raises(ModelValidationError, match="slicer_profile_changed"):
        run(OrcaSlicer(settings).slice(source, scratch))
