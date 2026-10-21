"""User profile compilation preserves settings and enforces standalone compatibility."""

import json

import pytest
from tools.prepare_print_preset import compile_profiles, resolve_profile


def test_user_export_without_type_resolves_values(tmp_path):
    resources = tmp_path / "resources"
    resources.mkdir()
    (resources / "base.json").write_text(
        json.dumps(
            {
                "type": "machine",
                "name": "AD5X base",
                "from": "system",
                "nozzle_diameter": ["0.4"],
                "machine_start_gcode": "BASE_START",
                "machine_end_gcode": "BASE_END",
            }
        )
    )
    user = tmp_path / "user.json"
    user.write_text(
        json.dumps(
            {
                "name": "AD5X M1",
                "from": "User",
                "inherits": "AD5X base",
                "machine_start_gcode": "OWNER_START",
            }
        )
    )
    resolved = resolve_profile(user, resources, "machine")
    assert resolved["type"] == "machine"
    assert "inherits" not in resolved
    assert resolved["from"] == "User"
    assert resolved["name"] == "AD5X M1"
    assert resolved["nozzle_diameter"] == ["0.4"]
    assert resolved["machine_start_gcode"] == "OWNER_START"
    assert resolved["machine_end_gcode"] == "BASE_END"
    assert "type" not in json.loads(user.read_text())


def test_system_profiles_are_fully_resolved_without_user_identity(tmp_path):
    resources = tmp_path / "resources"
    resources.mkdir()
    (resources / "base.json").write_text(
        json.dumps(
            {
                "type": "process",
                "name": "base",
                "layer_height": "0.2",
            }
        )
    )
    selected = resources / "selected.json"
    selected.write_text(
        json.dumps(
            {
                "type": "process",
                "name": "selected",
                "from": "system",
                "inherits": "base",
            }
        )
    )
    result = resolve_profile(selected, resources, "process")
    assert result["layer_height"] == "0.2"
    assert "inherits" not in result


@pytest.mark.parametrize("incompatible", [False, True])
def test_compile_uses_standalone_identity_and_only_declared_base_compatibility(
    tmp_path, incompatible
):
    resources = tmp_path / "resources"
    resources.mkdir()
    sources = []
    for kind, settings in (
        ("machine", {"nozzle_diameter": ["0.4"], "machine_start_gcode": "BASE_START"}),
        ("process", {"layer_height": "0.2", "compatible_printers": ["machine base"]}),
        ("filament", {"filament_type": ["PLA"], "compatible_printers": ["machine base"]}),
    ):
        (resources / f"{kind}.json").write_text(
            json.dumps(
                {
                    "type": kind,
                    "name": f"{kind} base",
                    "from": "system",
                    **settings,
                }
            )
        )
        source = tmp_path / f"user-{kind}.json"
        owner = {"name": f"owner {kind}", "inherits": f"{kind} base", "from": "User"}
        if kind == "machine":
            owner["machine_start_gcode"] = "OWNER_START"
        if kind == "process" and incompatible:
            owner["compatible_printers"] = ["unrelated printer"]
        source.write_text(json.dumps(owner))
        sources.append(source)
    if incompatible:
        with pytest.raises(ValueError, match="incompatible"):
            compile_profiles(*sources, resources)
        return
    compiled = compile_profiles(*sources, resources)
    profiles = {name: json.loads(data) for name, data in compiled.items()}
    assert profiles["machine.json"]["name"] == "owner machine"
    assert profiles["machine.json"]["machine_start_gcode"] == "OWNER_START"
    assert profiles["machine.json"]["nozzle_diameter"] == ["0.4"]
    for value in profiles.values():
        assert "inherits" not in value
        assert value["from"] == "system"
    for kind in ("process", "filament"):
        assert profiles[f"{kind}.json"]["compatible_printers"] == ["machine base", "owner machine"]
    assert json.loads(sources[0].read_text())["from"] == "User"


def test_explicit_wrong_type_is_rejected(tmp_path):
    path = tmp_path / "wrong.json"
    path.write_text(json.dumps({"type": "filament", "name": "wrong"}))
    with pytest.raises(ValueError, match="type"):
        resolve_profile(path, tmp_path, "machine")


def test_missing_or_cyclic_parent_is_not_replaced_with_defaults(tmp_path):
    selected = tmp_path / "selected.json"
    selected.write_text(
        json.dumps(
            {
                "type": "machine",
                "name": "owner",
                "from": "User",
                "inherits": "missing",
            }
        )
    )
    with pytest.raises(ValueError, match="missing or ambiguous"):
        resolve_profile(selected, tmp_path, "machine")
    selected.write_text(
        json.dumps(
            {
                "type": "machine",
                "name": "owner",
                "from": "User",
                "inherits": "owner",
            }
        )
    )
    with pytest.raises(ValueError, match="cyclic"):
        resolve_profile(selected, tmp_path, "machine")
