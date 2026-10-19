"""Owner-reviewed offerings derived from the exact files used by the slicer."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from json import JSONDecodeError, loads
from pathlib import Path
from re import fullmatch
from typing import Any

from xxx_api.config import Settings

PROFILE_FILES = ("machine.json", "process.json", "filament.json")


class PresetConfigurationError(ValueError):
    """A missing, changed or ambiguous profile must not become a saleable offering."""

    def __init__(self, message: str, *, code: str = "slicer_profile_invalid") -> None:
        super().__init__(message)
        self.code = code


def read_profile_bundle(directory: Path, expected_hash: str) -> dict[str, bytes]:
    digest = sha256()
    files = {}
    try:
        for name in PROFILE_FILES:
            source = directory / name
            if (
                source.is_symlink()
                or not source.is_file()
                or not 0 < source.stat().st_size <= 1048576
            ):
                raise PresetConfigurationError("A standalone profile file is missing or invalid.")
            data = source.read_bytes()
            value = loads(data)
            if not isinstance(value, dict) or value.get("inherits"):
                raise PresetConfigurationError("Export standalone profiles without inheritance.")
            digest.update(name.encode() + b"\0" + data)
            files[name] = data
    except (OSError, JSONDecodeError, UnicodeError) as error:
        raise PresetConfigurationError("The configured print profiles cannot be read.") from error
    if digest.hexdigest() != expected_hash:
        raise PresetConfigurationError(
            "The print profile hash has changed. Review it again.", code="slicer_profile_changed"
        )
    return files


def _text(value: Any, *, limit: int = 120) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise PresetConfigurationError("A print preset label is invalid.")
    if any(ord(char) < 32 for char in value):
        raise PresetConfigurationError("Print preset labels cannot contain control characters.")
    return value.strip()


def _single(profile: dict[str, Any], name: str) -> str:
    value = profile.get(name)
    if isinstance(value, list) and len(value) == 1:
        value = value[0]
    if not isinstance(value, str):
        raise PresetConfigurationError(f"The standalone profile must define {name}.")
    return value


def profile_settings(files: dict[str, bytes]) -> dict[str, object]:
    machine, process, filament = (loads(files[name]) for name in PROFILE_FILES)
    try:
        nozzle = Decimal(_single(machine, "nozzle_diameter"))
        layer = Decimal(_single(process, "layer_height"))
        infill_text = _single(process, "sparse_infill_density")
        support = _single(process, "enable_support")
        walls_text = _single(process, "wall_loops")
        if not fullmatch(r"(?:100|[0-9]{1,2})%", infill_text) or support not in {"0", "1"}:
            raise ValueError
        if not fullmatch(r"[0-9]{1,2}", walls_text):
            raise ValueError
        walls = int(walls_text)
        if not nozzle.is_finite() or not layer.is_finite():
            raise ValueError
        if not Decimal("0.1") <= nozzle <= Decimal("1.2") or not 0 < layer <= nozzle:
            raise ValueError
        if not 1 <= walls <= 20:
            raise ValueError
        return {
            "nozzleDiameterMm": str(nozzle.normalize()),
            "layerHeightMm": str(layer.normalize()),
            "infillPercent": int(infill_text[:-1]),
            "supports": support == "1",
            "wallLoops": walls,
            "filamentType": _text(_single(filament, "filament_type"), limit=64),
        }
    except (InvalidOperation, ValueError) as error:
        raise PresetConfigurationError(
            "The print profile settings are incomplete or invalid."
        ) from error


@dataclass(frozen=True)
class PrintPreset:
    code: str
    label: str
    material_code: str
    colours: tuple[str, ...]
    profile_directory: Path
    profile_sha256: str
    settings: dict[str, object]

    def public(self) -> dict[str, object]:
        return {
            "code": self.code,
            "label": self.label,
            "materialCode": self.material_code,
            "colours": list(self.colours),
            "profileSha256": self.profile_sha256,
            "settings": dict(self.settings),
        }

    def specification(self, colour: str | None) -> dict[str, object]:
        if (self.colours and colour not in self.colours) or (
            not self.colours and colour is not None
        ):
            raise PresetConfigurationError("Choose an available colour for this print preset.")
        return {
            "presetCode": self.code,
            "presetLabel": self.label,
            "materialCode": self.material_code,
            "profileSha256": self.profile_sha256,
            "colour": colour,
            "settings": dict(self.settings),
        }


def load_print_presets(settings: Settings) -> list[PrintPreset]:
    manifest = settings.analysis_preset_manifest
    entries: object
    if manifest is None:
        # Existing installations keep their one reviewed profile; no colours are invented.
        if not settings.analysis_profile_directory or not settings.analysis_profile_sha256:
            return []
        entries = [
            {
                "code": "standard",
                "label": "Standard print",
                "materialCode": settings.analysis_material_code,
                "colours": [],
                "profileDirectory": str(settings.analysis_profile_directory),
                "profileSha256": settings.analysis_profile_sha256,
            }
        ]
    else:
        try:
            if not manifest.is_absolute() or not 0 < manifest.stat().st_size <= 262144:
                raise PresetConfigurationError("Use an absolute, bounded preset manifest.")
            entries = loads(manifest.read_bytes())
        except (OSError, JSONDecodeError, UnicodeError) as error:
            raise PresetConfigurationError(
                "The print catalogue is not configured correctly."
            ) from error
    if not isinstance(entries, list) or not 1 <= len(entries) <= 64:
        raise PresetConfigurationError("Configure between one and 64 print presets.")
    presets = []
    codes = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise PresetConfigurationError("Invalid print preset entry.")
        code = _text(entry.get("code"), limit=32)
        material = _text(entry.get("materialCode"), limit=32)
        digest = _text(entry.get("profileSha256"), limit=64)
        if code in codes or not fullmatch(r"[a-z0-9-]{1,32}", code):
            raise PresetConfigurationError("Preset codes must be unique lowercase identifiers.")
        if not fullmatch(r"[a-z0-9-]{1,32}", material) or not fullmatch(r"[0-9a-f]{64}", digest):
            raise PresetConfigurationError("Invalid material code or profile hash.")
        raw_colours = entry.get("colours", [])
        if not isinstance(raw_colours, list) or len(raw_colours) > 32:
            raise PresetConfigurationError("Invalid available-colour list.")
        colours = tuple(_text(colour, limit=64) for colour in raw_colours)
        if len(set(colours)) != len(colours):
            raise PresetConfigurationError("Available colours must be unique.")
        directory = Path(_text(entry.get("profileDirectory"), limit=4096))
        if not directory.is_absolute():
            raise PresetConfigurationError("Profile directories must be absolute.")
        files = read_profile_bundle(directory, digest)
        presets.append(
            PrintPreset(
                code,
                _text(entry.get("label")),
                material,
                colours,
                directory,
                digest,
                profile_settings(files),
            )
        )
        codes.add(code)
    return presets
