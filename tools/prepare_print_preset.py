"""Resolve an explicitly selected profile set for owner review, without printing anything."""

import argparse
import json
from hashlib import sha256
from pathlib import Path

from xxx_api.print_presets import PROFILE_FILES, profile_settings


def resolve_profile(path: Path, resources: Path, expected_kind: str) -> dict:
    if path.is_symlink() or path.stat().st_size > 1048576:
        raise ValueError("Select a regular profile file up to 1 MiB.")
    selected = json.loads(path.read_bytes())
    if not isinstance(selected, dict):
        raise ValueError("A profile must be a JSON object.")
    # Orca user exports omit type; the explicit --machine/--process/--filament argument
    # supplies it. An explicitly conflicting type remains an error.
    kind = selected.get("type", expected_kind)
    if kind != expected_kind:
        raise ValueError("The selected profile type does not match its argument.")
    selected["type"] = kind
    index = {}
    candidates = list(resources.rglob("*.json"))
    if len(candidates) > 10000:
        raise ValueError("Select a narrower vendor profile directory.")
    for candidate in candidates:
        if candidate.is_symlink() or candidate.stat().st_size > 1048576:
            continue
        value = json.loads(candidate.read_bytes())
        if (
            isinstance(value, dict)
            and value.get("type") == kind
            and isinstance(value.get("name"), str)
        ):
            alternatives = index.setdefault(value["name"], [])
            if value not in alternatives:
                alternatives.append(value)

    def merge(value: dict, chain: tuple[str, ...]) -> dict:
        parent = value.get("inherits")
        if parent:
            if not isinstance(parent, str) or parent in chain or len(chain) > 24:
                raise ValueError("Unsupported or cyclic profile inheritance.")
            if len(index.get(parent, [])) != 1:
                raise ValueError(
                    "An inherited profile is missing or ambiguous in the selected resources."
                )
            result = merge(index[parent][0], (*chain, parent))
        else:
            result = {}
        result.update(value)
        result.pop("inherits", None)
        return result

    return merge(selected, ())


def compile_profiles(
    machine: Path, process: Path, filament: Path, resources: Path
) -> dict[str, bytes]:
    """Materialize settings and compile Orca identity metadata for standalone CLI use."""
    paths = {"machine.json": machine, "process.json": process, "filament.json": filament}
    resolved = {name: resolve_profile(path, resources, name[:-5]) for name, path in paths.items()}
    source_machine = json.loads(machine.read_bytes())
    machine_name = resolved["machine.json"].get("name")
    parent = source_machine.get("inherits")
    for value in resolved.values():
        if str(value.get("from", "")).casefold() == "user":
            # Orca CLI treats User without inherits as an unknown system identity.
            # These compiled files contain all resolved values and are loaded independently;
            # the original user export remains the provenance of the settings.
            value["from"] = "system"
    for name in ("process.json", "filament.json"):
        compatible = resolved[name].get("compatible_printers")
        if compatible and machine_name not in compatible:
            if not isinstance(compatible, list) or not parent or parent not in compatible:
                raise ValueError("The selected profiles are incompatible with this printer.")
            # Retain the base's declared compatibility for this specific derived printer.
            resolved[name]["compatible_printers"] = [*compatible, machine_name]
    return {name: json.dumps(resolved[name], indent=2).encode() for name in PROFILE_FILES}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resources", type=Path, required=True)
    parser.add_argument("--machine", type=Path, required=True)
    parser.add_argument("--process", type=Path, required=True)
    parser.add_argument("--filament", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--code", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--material-code", required=True)
    parser.add_argument("--colours", nargs="*", default=[])
    args = parser.parse_args()
    try:
        profiles = compile_profiles(args.machine, args.process, args.filament, args.resources)
        displayed = profile_settings(profiles)
        output = args.output.resolve()
        output.mkdir(mode=0o700, parents=True, exist_ok=False)
        digest = sha256()
        for filename, data in profiles.items():
            (output / filename).write_bytes(data)
            digest.update(filename.encode() + b"\0" + data)
        manifest = [
            {
                "code": args.code,
                "label": args.label,
                "materialCode": args.material_code,
                "colours": args.colours,
                "profileDirectory": str(output),
                "profileSha256": digest.hexdigest(),
            }
        ]
        (output / "presets.json").write_text(json.dumps(manifest, indent=2))
        print(
            json.dumps(
                {
                    "settings": displayed,
                    "profileSha256": digest.hexdigest(),
                    "manifest": str(output / "presets.json"),
                    "reviewRequired": (
                        "Review the full profiles, loaded filament and a supervised test print "
                        "before approving physical use. No printer was contacted."
                    ),
                },
                indent=2,
            )
        )
    except (OSError, ValueError, KeyError, TypeError):
        parser.exit(
            1,
            "Preset preparation stopped. Check the selected profile files, "
            "inheritance and new output directory.\n",
        )


if __name__ == "__main__":
    main()
