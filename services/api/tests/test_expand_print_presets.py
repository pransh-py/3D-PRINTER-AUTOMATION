import json
from hashlib import sha256

import pytest
from xxx_api.config import Settings
from xxx_api.print_presets import load_print_presets, read_profile_bundle

from tools.expand_print_presets import expand_presets


def test_customization_preserves_base_and_pins_all_sixty_combinations(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    values = {
        "machine.json": {"nozzle_diameter": ["0.4"], "machine_start_gcode": "owner start"},
        "process.json": {
            "layer_height": "0.2",
            "sparse_infill_density": "20%",
            "enable_support": "0",
            "wall_loops": "3",
            "curr_bed_type": "Textured PEI Plate",
            "outer_wall_speed": "100",
        },
        "filament.json": {"filament_type": ["PLA"], "nozzle_temperature": ["220"]},
    }
    digest = sha256()
    original = {}
    for name, value in values.items():
        data = json.dumps(value).encode()
        original[name] = data
        (base / name).write_bytes(data)
        digest.update(name.encode() + b"\0" + data)
    entry = {
        "code": "pla",
        "label": "PLA",
        "materialCode": "pla",
        "colours": ["red", "white"],
        "profileDirectory": str(base),
        "profileSha256": digest.hexdigest(),
    }
    manifest = tmp_path / "base.json"
    manifest.write_text(json.dumps([entry]))
    expanded = expand_presets(manifest, "pla", tmp_path / "custom")
    settings = Settings(
        _env_file=None,
        analysis_slicer_command=tmp_path / "orca",
        analysis_slicer_sha256="a" * 64,
        analysis_slicer_version="test",
        analysis_preset_manifest=expanded,
        analysis_lease_seconds=1320,
    )
    presets = load_print_presets(settings)
    assert len(presets) == 61
    assert json.loads(expanded.read_bytes())[0] == entry
    combinations = set()
    for preset in presets[1:]:
        files = read_profile_bundle(preset.profile_directory, preset.profile_sha256)
        assert files["machine.json"] == original["machine.json"]
        assert files["filament.json"] == original["filament.json"]
        process = json.loads(files["process.json"])
        assert {
            key: value
            for key, value in process.items()
            if key not in {"layer_height", "sparse_infill_density", "enable_support"}
        } == {
            key: value
            for key, value in values["process.json"].items()
            if key not in {"layer_height", "sparse_infill_density", "enable_support"}
        }
        combinations.add(
            (
                preset.settings["layerHeightMm"],
                preset.settings["infillPercent"],
                preset.settings["supports"],
            )
        )
    assert len(combinations) == 60
    assert ("0.1", 90, True) in combinations
    assert all((base / name).read_bytes() == data for name, data in original.items())
    with pytest.raises(ValueError, match="never overwritten"):
        expand_presets(manifest, "pla", tmp_path / "custom")
