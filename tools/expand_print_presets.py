"""Compile the established station choices into immutable customer quote presets.

Only layer height, infill and support enablement change. The base and existing
catalogue entries remain intact. This does not approve physical dispatch.
"""

import argparse
import json
from hashlib import sha256
from pathlib import Path
from re import fullmatch

from xxx_api.print_presets import PROFILE_FILES, profile_settings, read_profile_bundle

LAYERS = ("0.2", "0.15", "0.1")
INFILLS = (10, 15, 20, 30, 40, 50, 60, 70, 80, 90)


def expand_presets(manifest: Path, code: str, output: Path) -> Path:
    entries = json.loads(manifest.read_bytes())
    if not isinstance(entries, list) or not 1 <= len(entries) <= 4:
        raise ValueError("Select a bounded catalogue with room for 60 customization presets.")
    selected = [entry for entry in entries if entry.get("code") == code]
    if len(selected) != 1 or not fullmatch(r"[a-z0-9-]{1,20}", code):
        raise ValueError("Select one existing short preset code.")
    base = selected[0]
    source = read_profile_bundle(Path(base["profileDirectory"]), base["profileSha256"])
    if output.exists():
        raise ValueError("Choose a new output directory; existing presets are never overwritten.")
    output = output.resolve()
    output.mkdir(mode=0o700, parents=True)
    for layer in LAYERS:
        for infill in INFILLS:
            for supports in (False, True):
                variant_code = f"{code}-l{layer[2:]}-i{infill}-s{int(supports)}"
                if any(entry["code"] == variant_code for entry in entries):
                    raise ValueError("A generated preset code already exists.")
                directory = output / variant_code
                directory.mkdir(mode=0o700)
                process = json.loads(source["process.json"])
                process.update(
                    layer_height=layer,
                    sparse_infill_density=f"{infill}%",
                    enable_support=str(int(supports)),
                )
                files = {**source, "process.json": json.dumps(process, sort_keys=True).encode()}
                profile_settings(files)
                digest = sha256()
                for name in PROFILE_FILES:
                    (directory / name).write_bytes(files[name])
                    digest.update(name.encode() + b"\0" + files[name])
                entries.append(
                    {
                        **base,
                        "code": variant_code,
                        "label": (
                            f"{base['label']} · {layer} mm · {infill}% · "
                            f"supports {'on' if supports else 'off'}"
                        ),
                        "profileDirectory": str(directory),
                        "profileSha256": digest.hexdigest(),
                    }
                )
    result = output / "presets.json"
    result.write_text(json.dumps(entries, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--code", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(expand_presets(args.manifest, args.code, args.output))
