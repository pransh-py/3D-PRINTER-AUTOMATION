"""Bounded, content-aware source-model validation for the sandbox process."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from math import isfinite
from pathlib import Path, PurePosixPath
from stat import S_IFLNK, S_IFMT
from struct import Struct, unpack
from typing import Literal
from zipfile import BadZipFile, ZipFile, ZipInfo

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

ModelFormat = Literal["stl", "3mf", "obj", "step"]
AD5X_BUILD_VOLUME_UM = (220_000, 220_000, 220_000)
_BINARY_STL_TRIANGLE = Struct("<12fH")
_ARCHIVE_SUFFIXES = {".zip", ".3mf", ".7z", ".rar", ".tar", ".gz"}


class ModelValidationError(Exception):
    """Fail-closed validation error represented by one stable safe code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class ValidationLimits:
    """Hard limits enforced before a file can reach a slicer."""

    max_bytes: int = 100 * 1024 * 1024
    max_triangles: int = 2_000_000
    max_vertices: int = 5_000_000
    max_objects: int = 1_000
    max_archive_entries: int = 256
    max_archive_entry_bytes: int = 32 * 1024 * 1024
    max_archive_expanded_bytes: int = 200 * 1024 * 1024
    max_archive_compression_ratio: int = 100


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Credential-free structured evidence emitted by the validator."""

    detected_format: ModelFormat
    verified_sha256: str
    size_bytes: int
    dimensions_um: tuple[int, int, int] | None
    triangle_count: int | None
    object_count: int | None
    fits_build_volume: bool | None
    warning_codes: tuple[str, ...]


@dataclass(slots=True)
class _Bounds:
    minimum: list[float]
    maximum: list[float]
    seen: bool = False

    @classmethod
    def empty(cls) -> _Bounds:
        return cls([float("inf")] * 3, [float("-inf")] * 3)

    def include(self, coordinates: tuple[float, float, float]) -> None:
        if not all(isfinite(value) for value in coordinates):
            raise ModelValidationError("non_finite_coordinate")
        for axis, value in enumerate(coordinates):
            self.minimum[axis] = min(self.minimum[axis], value)
            self.maximum[axis] = max(self.maximum[axis], value)
        self.seen = True

    def dimensions_um(self) -> tuple[int, int, int]:
        if not self.seen:
            raise ModelValidationError("geometry_missing")
        dimensions = tuple(
            max(0, round((self.maximum[axis] - self.minimum[axis]) * 1_000))
            for axis in range(3)
        )
        return dimensions  # type: ignore[return-value]


def _safe_file_evidence(path: Path, limits: ValidationLimits) -> tuple[int, str]:
    try:
        stat = path.stat()
    except OSError as error:
        raise ModelValidationError("source_unavailable") from error
    if not path.is_file() or stat.st_size < 1:
        raise ModelValidationError("source_empty")
    if stat.st_size > limits.max_bytes:
        raise ModelValidationError("source_too_large")
    digest = sha256()
    observed = 0
    try:
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                observed += len(chunk)
                if observed > limits.max_bytes:
                    raise ModelValidationError("source_too_large")
                digest.update(chunk)
    except OSError as error:
        raise ModelValidationError("source_unavailable") from error
    if observed != stat.st_size:
        raise ModelValidationError("source_changed_during_read")
    return observed, digest.hexdigest()


def _fit(dimensions: tuple[int, int, int]) -> bool:
    return all(
        dimension <= build_axis
        for dimension, build_axis in zip(dimensions, AD5X_BUILD_VOLUME_UM, strict=True)
    )


def _result(
    *,
    detected_format: ModelFormat,
    digest: str,
    size_bytes: int,
    bounds: _Bounds | None,
    triangle_count: int | None,
    object_count: int | None,
    warning_codes: tuple[str, ...] = (),
) -> ValidationResult:
    dimensions = bounds.dimensions_um() if bounds is not None else None
    return ValidationResult(
        detected_format=detected_format,
        verified_sha256=digest,
        size_bytes=size_bytes,
        dimensions_um=dimensions,
        triangle_count=triangle_count,
        object_count=object_count,
        fits_build_volume=_fit(dimensions) if dimensions is not None else None,
        warning_codes=warning_codes,
    )


def _validate_binary_stl(
    path: Path,
    size_bytes: int,
    digest: str,
    triangle_count: int,
    limits: ValidationLimits,
) -> ValidationResult:
    if triangle_count < 1:
        raise ModelValidationError("geometry_missing")
    if triangle_count > limits.max_triangles:
        raise ModelValidationError("triangle_limit_exceeded")
    bounds = _Bounds.empty()
    try:
        with path.open("rb") as source:
            source.seek(84)
            for _ in range(triangle_count):
                record = source.read(_BINARY_STL_TRIANGLE.size)
                if len(record) != _BINARY_STL_TRIANGLE.size:
                    raise ModelValidationError("stl_truncated")
                values = _BINARY_STL_TRIANGLE.unpack(record)
                for offset in (3, 6, 9):
                    bounds.include((values[offset], values[offset + 1], values[offset + 2]))
    except OSError as error:
        raise ModelValidationError("source_unavailable") from error
    return _result(
        detected_format="stl",
        digest=digest,
        size_bytes=size_bytes,
        bounds=bounds,
        triangle_count=triangle_count,
        object_count=1,
    )


def _validate_ascii_stl(
    path: Path,
    size_bytes: int,
    digest: str,
    limits: ValidationLimits,
) -> ValidationResult:
    bounds = _Bounds.empty()
    vertex_count = 0
    facet_count = 0
    saw_solid = False
    saw_end = False
    try:
        with path.open("r", encoding="ascii", errors="strict", newline=None) as source:
            for raw_line in source:
                line = raw_line.strip()
                if not line:
                    continue
                keyword, _, remainder = line.partition(" ")
                lowered = keyword.lower()
                if lowered == "solid":
                    saw_solid = True
                elif lowered == "endsolid":
                    saw_end = True
                elif lowered == "facet":
                    facet_count += 1
                    if facet_count > limits.max_triangles:
                        raise ModelValidationError("triangle_limit_exceeded")
                elif lowered == "vertex":
                    fields = remainder.split()
                    if len(fields) != 3:
                        raise ModelValidationError("stl_structure_invalid")
                    try:
                        coordinates = tuple(float(value) for value in fields)
                    except ValueError as error:
                        raise ModelValidationError("stl_structure_invalid") from error
                    bounds.include(coordinates)  # type: ignore[arg-type]
                    vertex_count += 1
    except UnicodeError as error:
        raise ModelValidationError("stl_signature_invalid") from error
    except OSError as error:
        raise ModelValidationError("source_unavailable") from error
    if not saw_solid or not saw_end or facet_count < 1 or vertex_count != facet_count * 3:
        raise ModelValidationError("stl_structure_invalid")
    return _result(
        detected_format="stl",
        digest=digest,
        size_bytes=size_bytes,
        bounds=bounds,
        triangle_count=facet_count,
        object_count=1,
        warning_codes=("ascii_stl",),
    )


def _validate_stl(
    path: Path,
    size_bytes: int,
    digest: str,
    limits: ValidationLimits,
) -> ValidationResult:
    try:
        with path.open("rb") as source:
            header = source.read(84)
    except OSError as error:
        raise ModelValidationError("source_unavailable") from error
    if len(header) >= 84:
        triangle_count = unpack("<I", header[80:84])[0]
        expected_size = 84 + triangle_count * _BINARY_STL_TRIANGLE.size
        if expected_size == size_bytes:
            return _validate_binary_stl(path, size_bytes, digest, triangle_count, limits)
    if header.lstrip().lower().startswith(b"solid"):
        return _validate_ascii_stl(path, size_bytes, digest, limits)
    raise ModelValidationError("stl_signature_invalid")


def _parse_obj_index(token: str, vertex_count: int) -> None:
    raw_index = token.split("/", maxsplit=1)[0]
    if not raw_index:
        raise ModelValidationError("obj_face_invalid")
    try:
        index = int(raw_index)
    except ValueError as error:
        raise ModelValidationError("obj_face_invalid") from error
    if index == 0 or index > vertex_count or index < -vertex_count:
        raise ModelValidationError("obj_face_invalid")


def _validate_obj(
    path: Path,
    size_bytes: int,
    digest: str,
    limits: ValidationLimits,
) -> ValidationResult:
    bounds = _Bounds.empty()
    vertex_count = 0
    triangle_count = 0
    object_count = 0
    try:
        with path.open("r", encoding="utf-8", errors="strict", newline=None) as source:
            for raw_line in source:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                keyword, _, remainder = line.partition(" ")
                if keyword == "v":
                    fields = remainder.split()
                    if len(fields) not in {3, 4}:
                        raise ModelValidationError("obj_vertex_invalid")
                    try:
                        coordinates = tuple(float(value) for value in fields[:3])
                    except ValueError as error:
                        raise ModelValidationError("obj_vertex_invalid") from error
                    bounds.include(coordinates)  # type: ignore[arg-type]
                    vertex_count += 1
                    if vertex_count > limits.max_vertices:
                        raise ModelValidationError("vertex_limit_exceeded")
                elif keyword == "f":
                    references = remainder.split()
                    if len(references) < 3:
                        raise ModelValidationError("obj_face_invalid")
                    for reference in references:
                        _parse_obj_index(reference, vertex_count)
                    triangle_count += len(references) - 2
                    if triangle_count > limits.max_triangles:
                        raise ModelValidationError("triangle_limit_exceeded")
                elif keyword in {"o", "g"}:
                    object_count += 1
                    if object_count > limits.max_objects:
                        raise ModelValidationError("object_limit_exceeded")
                elif keyword == "mtllib":
                    raise ModelValidationError("obj_external_resource_forbidden")
                elif keyword not in {"vn", "vt", "s", "usemtl"}:
                    raise ModelValidationError("obj_statement_unsupported")
    except UnicodeError as error:
        raise ModelValidationError("obj_encoding_invalid") from error
    except OSError as error:
        raise ModelValidationError("source_unavailable") from error
    if vertex_count < 3 or triangle_count < 1:
        raise ModelValidationError("geometry_missing")
    return _result(
        detected_format="obj",
        digest=digest,
        size_bytes=size_bytes,
        bounds=bounds,
        triangle_count=triangle_count,
        object_count=max(object_count, 1),
        warning_codes=("obj_materials_ignored",),
    )


def _safe_archive_name(info: ZipInfo) -> PurePosixPath:
    filename = info.filename
    if "\\" in filename or filename.startswith("/") or "\x00" in filename:
        raise ModelValidationError("archive_path_unsafe")
    path = PurePosixPath(filename)
    if not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ModelValidationError("archive_path_unsafe")
    if S_IFMT(info.external_attr >> 16) == S_IFLNK:
        raise ModelValidationError("archive_link_forbidden")
    normalized = path.as_posix().lower()
    if normalized.endswith((".gcode", ".gcode.3mf")):
        raise ModelValidationError("sliced_artifact_forbidden")
    if not info.is_dir() and path.suffix.lower() in _ARCHIVE_SUFFIXES:
        raise ModelValidationError("nested_archive_forbidden")
    return path


def _inspect_archive(archive: ZipFile, limits: ValidationLimits) -> dict[str, ZipInfo]:
    infos = archive.infolist()
    if len(infos) > limits.max_archive_entries:
        raise ModelValidationError("archive_entry_limit_exceeded")
    total_expanded = 0
    by_name: dict[str, ZipInfo] = {}
    for info in infos:
        path = _safe_archive_name(info)
        normalized = path.as_posix()
        if normalized in by_name:
            raise ModelValidationError("archive_duplicate_entry")
        by_name[normalized] = info
        if info.file_size > limits.max_archive_entry_bytes:
            raise ModelValidationError("archive_entry_too_large")
        total_expanded += info.file_size
        if total_expanded > limits.max_archive_expanded_bytes:
            raise ModelValidationError("archive_expansion_limit_exceeded")
        if info.file_size and info.file_size / max(info.compress_size, 1) > (
            limits.max_archive_compression_ratio
        ):
            raise ModelValidationError("archive_compression_ratio_exceeded")
    return by_name


def _xml_root(data: bytes):
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ModelValidationError("xml_declaration_forbidden")
    try:
        return ElementTree.fromstring(data)
    except (DefusedXmlException, ElementTree.ParseError) as error:
        raise ModelValidationError("xml_structure_invalid") from error


def _relationship_targets(data: bytes) -> tuple[str, ...]:
    root = _xml_root(data)
    targets: list[str] = []
    for element in root.iter():
        if element.tag.rsplit("}", maxsplit=1)[-1] != "Relationship":
            continue
        if element.attrib.get("TargetMode", "Internal") != "Internal":
            raise ModelValidationError("external_relationship_forbidden")
        target = element.attrib.get("Target")
        if target is None:
            raise ModelValidationError("relationship_invalid")
        normalized = target.lstrip("/")
        if "\\" in normalized or any(
            part in {"", ".", ".."} for part in PurePosixPath(normalized).parts
        ):
            raise ModelValidationError("relationship_invalid")
        targets.append(normalized)
    return tuple(targets)


def _parse_3mf_model(
    data: bytes,
    limits: ValidationLimits,
) -> tuple[_Bounds, int, int]:
    root = _xml_root(data)
    if root.tag.rsplit("}", maxsplit=1)[-1] != "model":
        raise ModelValidationError("three_mf_model_invalid")
    unit = root.attrib.get("unit", "millimeter")
    unit_scale = {
        "micron": 0.001,
        "millimeter": 1.0,
        "centimeter": 10.0,
        "inch": 25.4,
        "foot": 304.8,
        "meter": 1000.0,
    }.get(unit)
    if unit_scale is None:
        raise ModelValidationError("three_mf_unit_invalid")
    bounds = _Bounds.empty()
    vertex_count = 0
    triangle_count = 0
    object_count = 0
    for element in root.iter():
        local_name = element.tag.rsplit("}", maxsplit=1)[-1]
        if local_name == "object":
            object_count += 1
            if object_count > limits.max_objects:
                raise ModelValidationError("object_limit_exceeded")
        elif local_name == "components":
            raise ModelValidationError("three_mf_components_unsupported")
        elif local_name == "vertex":
            try:
                coordinates = tuple(float(element.attrib[axis]) * unit_scale for axis in "xyz")
            except (KeyError, ValueError) as error:
                raise ModelValidationError("three_mf_vertex_invalid") from error
            bounds.include(coordinates)  # type: ignore[arg-type]
            vertex_count += 1
            if vertex_count > limits.max_vertices:
                raise ModelValidationError("vertex_limit_exceeded")
        elif local_name == "triangle":
            try:
                indexes = tuple(int(element.attrib[axis]) for axis in ("v1", "v2", "v3"))
            except (KeyError, ValueError) as error:
                raise ModelValidationError("three_mf_triangle_invalid") from error
            if any(index < 0 or index >= vertex_count for index in indexes):
                raise ModelValidationError("three_mf_triangle_invalid")
            triangle_count += 1
            if triangle_count > limits.max_triangles:
                raise ModelValidationError("triangle_limit_exceeded")
    if object_count < 1 or vertex_count < 3 or triangle_count < 1:
        raise ModelValidationError("geometry_missing")
    return bounds, triangle_count, object_count


def _validate_3mf(
    path: Path,
    size_bytes: int,
    digest: str,
    limits: ValidationLimits,
) -> ValidationResult:
    try:
        with ZipFile(path) as archive:
            entries = _inspect_archive(archive, limits)
            required = {"[Content_Types].xml", "_rels/.rels"}
            if not required.issubset(entries):
                raise ModelValidationError("three_mf_package_invalid")
            for name, info in entries.items():
                if name.lower().endswith((".xml", ".rels", ".model")):
                    _xml_root(archive.read(info))
            relationship_data = archive.read(entries["_rels/.rels"])
            targets = _relationship_targets(relationship_data)
            model_targets = tuple(target for target in targets if target.lower().endswith(".model"))
            if len(model_targets) != 1 or model_targets[0] not in entries:
                raise ModelValidationError("three_mf_model_missing")
            model_data = archive.read(entries[model_targets[0]])
            bounds, triangle_count, object_count = _parse_3mf_model(model_data, limits)
    except BadZipFile as error:
        raise ModelValidationError("three_mf_signature_invalid") from error
    except OSError as error:
        raise ModelValidationError("source_unavailable") from error
    return _result(
        detected_format="3mf",
        digest=digest,
        size_bytes=size_bytes,
        bounds=bounds,
        triangle_count=triangle_count,
        object_count=object_count,
    )


def _validate_step(path: Path, size_bytes: int, digest: str) -> ValidationResult:
    try:
        data = path.read_bytes()
    except OSError as error:
        raise ModelValidationError("source_unavailable") from error
    if b"\x00" in data:
        raise ModelValidationError("step_encoding_invalid")
    try:
        text = data.decode("ascii")
    except UnicodeError as error:
        raise ModelValidationError("step_encoding_invalid") from error
    normalized = text.lstrip("\ufeff\r\n\t ").upper()
    if not normalized.startswith("ISO-10303-21;") or "END-ISO-10303-21;" not in normalized:
        raise ModelValidationError("step_signature_invalid")
    if "HEADER;" not in normalized or "DATA;" not in normalized:
        raise ModelValidationError("step_structure_invalid")
    return _result(
        detected_format="step",
        digest=digest,
        size_bytes=size_bytes,
        bounds=None,
        triangle_count=None,
        object_count=None,
        warning_codes=("geometry_requires_slicer",),
    )


def validate_model(
    path: str | Path,
    declared_format: ModelFormat,
    *,
    limits: ValidationLimits | None = None,
) -> ValidationResult:
    """Validate one scratch file and return only bounded structured evidence."""
    source = Path(path)
    effective_limits = limits or ValidationLimits()
    size_bytes, digest = _safe_file_evidence(source, effective_limits)
    if declared_format == "stl":
        return _validate_stl(source, size_bytes, digest, effective_limits)
    if declared_format == "obj":
        return _validate_obj(source, size_bytes, digest, effective_limits)
    if declared_format == "3mf":
        return _validate_3mf(source, size_bytes, digest, effective_limits)
    if declared_format == "step":
        return _validate_step(source, size_bytes, digest)
    raise ModelValidationError("declared_format_unsupported")
