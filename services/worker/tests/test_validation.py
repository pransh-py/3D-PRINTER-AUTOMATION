"""Behavioral tests for the bounded model-validator contract."""

from __future__ import annotations

import struct
from hashlib import sha256
from math import inf
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

import pytest

from xxx_worker.validation import ModelValidationError, ValidationLimits, validate_model

_TRIANGLE_RECORD = struct.Struct("<12fH")
Vec3 = tuple[float, float, float]


def _binary_stl_bytes(triangles: list[tuple[Vec3, Vec3, Vec3]]) -> bytes:
    header = b"binary stl fixture".ljust(80, b" ")
    body = struct.pack("<I", len(triangles))
    for v1, v2, v3 in triangles:
        body += _TRIANGLE_RECORD.pack(0.0, 0.0, 1.0, *v1, *v2, *v3, 0)
    return header + body


def _write(tmp_path: Path, name: str, data: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def _write_zip(
    tmp_path: Path,
    name: str,
    entries: dict[str, bytes],
    compress_type: int = ZIP_STORED,
) -> Path:
    path = tmp_path / name
    with ZipFile(path, "w") as archive:
        for entry_name, data in entries.items():
            archive.writestr(entry_name, data, compress_type=compress_type)
    return path


_CONTENT_TYPES_XML = (
    b'<?xml version="1.0" encoding="UTF-8"?>'
    b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    b'<Default Extension="rels" '
    b'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    b'<Default Extension="model" '
    b'ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
    b"</Types>"
)

_MODEL_XML = (
    b'<?xml version="1.0" encoding="UTF-8"?>'
    b'<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" unit="millimeter">'
    b'<resources><object id="1" type="model"><mesh>'
    b'<vertices><vertex x="0" y="0" z="0"/><vertex x="1" y="0" z="0"/>'
    b'<vertex x="0" y="1" z="0"/></vertices>'
    b'<triangles><triangle v1="0" v2="1" v3="2"/></triangles>'
    b"</mesh></object></resources>"
    b'<build><item objectid="1"/></build>'
    b"</model>"
)

_RELS_XML = (
    b'<?xml version="1.0" encoding="UTF-8"?>'
    b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    b'<Relationship Id="rel0" '
    b'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel" '
    b'Target="/3D/3dmodel.model"/>'
    b"</Relationships>"
)


def _valid_3mf_entries() -> dict[str, bytes]:
    return {
        "[Content_Types].xml": _CONTENT_TYPES_XML,
        "_rels/.rels": _RELS_XML,
        "3D/3dmodel.model": _MODEL_XML,
    }


# --- Success cases -----------------------------------------------------


def test_binary_stl_reports_geometry_and_digest(tmp_path: Path) -> None:
    data = _binary_stl_bytes([((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 3.0, 0.0))])
    path = _write(tmp_path, "cube.stl", data)

    result = validate_model(path, "stl")

    assert result.detected_format == "stl"
    assert result.triangle_count == 1
    assert result.object_count == 1
    assert result.dimensions_um == (2000, 3000, 0)
    assert result.fits_build_volume is True
    assert result.verified_sha256 == sha256(data).hexdigest()


def test_ascii_stl_succeeds_with_warning(tmp_path: Path) -> None:
    content = (
        "solid ascii_fixture\n"
        "facet normal 0 0 1\n"
        "outer loop\n"
        "vertex 0 0 0\n"
        "vertex 1 0 0\n"
        "vertex 0 1 0\n"
        "endloop\n"
        "endfacet\n"
        "endsolid ascii_fixture\n"
    ).encode("ascii")
    path = _write(tmp_path, "ascii.stl", content)

    result = validate_model(path, "stl")

    assert result.detected_format == "stl"
    assert result.triangle_count == 1
    assert result.object_count == 1
    assert "ascii_stl" in result.warning_codes


def test_obj_triangle_face_succeeds(tmp_path: Path) -> None:
    content = b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n"
    path = _write(tmp_path, "triangle.obj", content)

    result = validate_model(path, "obj")

    assert result.detected_format == "obj"
    assert result.triangle_count == 1
    assert result.object_count == 1


def test_obj_quad_face_triangulates_to_two_triangles(tmp_path: Path) -> None:
    content = b"v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nf 1 2 3 4\n"
    path = _write(tmp_path, "quad.obj", content)

    result = validate_model(path, "obj")

    assert result.triangle_count == 2


def test_source_3mf_succeeds_with_counts_and_dimensions(tmp_path: Path) -> None:
    path = _write_zip(tmp_path, "model.3mf", _valid_3mf_entries())

    result = validate_model(path, "3mf")

    assert result.detected_format == "3mf"
    assert result.triangle_count == 1
    assert result.object_count == 1
    assert result.dimensions_um == (1000, 1000, 0)
    assert result.fits_build_volume is True


def test_step_envelope_succeeds_with_slicer_required_warning(tmp_path: Path) -> None:
    content = "ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n".encode(
        "ascii"
    )
    path = _write(tmp_path, "part.step", content)

    result = validate_model(path, "step")

    assert result.detected_format == "step"
    assert result.dimensions_um is None
    assert result.triangle_count is None
    assert result.object_count is None
    assert "geometry_requires_slicer" in result.warning_codes


# --- Fail-closed cases ---------------------------------------------------


def test_stl_bad_signature_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, "bad.stl", b"this is not a recognizable stl payload")

    with pytest.raises(ModelValidationError) as excinfo:
        validate_model(path, "stl")

    assert excinfo.value.code == "stl_signature_invalid"


def test_stl_non_finite_coordinate_rejected(tmp_path: Path) -> None:
    data = _binary_stl_bytes([((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, inf))])
    path = _write(tmp_path, "bad_coord.stl", data)

    with pytest.raises(ModelValidationError) as excinfo:
        validate_model(path, "stl")

    assert excinfo.value.code == "non_finite_coordinate"


def test_obj_mtllib_rejected(tmp_path: Path) -> None:
    content = b"v 0 0 0\nv 1 0 0\nv 0 1 0\nmtllib materials.mtl\nf 1 2 3\n"
    path = _write(tmp_path, "material.obj", content)

    with pytest.raises(ModelValidationError) as excinfo:
        validate_model(path, "obj")

    assert excinfo.value.code == "obj_external_resource_forbidden"


def test_obj_out_of_range_face_rejected(tmp_path: Path) -> None:
    content = b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 5\n"
    path = _write(tmp_path, "bad_face.obj", content)

    with pytest.raises(ModelValidationError) as excinfo:
        validate_model(path, "obj")

    assert excinfo.value.code == "obj_face_invalid"


def test_3mf_path_traversal_rejected(tmp_path: Path) -> None:
    path = _write_zip(tmp_path, "traversal.3mf", {"../evil.txt": b"data"})

    with pytest.raises(ModelValidationError) as excinfo:
        validate_model(path, "3mf")

    assert excinfo.value.code == "archive_path_unsafe"


def test_3mf_symlink_entry_rejected(tmp_path: Path) -> None:
    path = tmp_path / "symlink.3mf"
    info = ZipInfo("link.txt")
    info.external_attr = 0o120777 << 16
    with ZipFile(path, "w") as archive:
        archive.writestr(info, "target")

    with pytest.raises(ModelValidationError) as excinfo:
        validate_model(path, "3mf")

    assert excinfo.value.code == "archive_link_forbidden"


def test_3mf_nested_archive_entry_rejected(tmp_path: Path) -> None:
    path = _write_zip(tmp_path, "nested.3mf", {"resource.zip": b"data"})

    with pytest.raises(ModelValidationError) as excinfo:
        validate_model(path, "3mf")

    assert excinfo.value.code == "nested_archive_forbidden"


def test_3mf_gcode_entry_rejected(tmp_path: Path) -> None:
    path = _write_zip(tmp_path, "gcode.3mf", {"print.gcode": b"G1 X0 Y0"})

    with pytest.raises(ModelValidationError) as excinfo:
        validate_model(path, "3mf")

    assert excinfo.value.code == "sliced_artifact_forbidden"


def test_3mf_external_relationship_rejected(tmp_path: Path) -> None:
    entries = {
        "[Content_Types].xml": _CONTENT_TYPES_XML,
        "_rels/.rels": (
            b'<?xml version="1.0" encoding="UTF-8"?>'
            b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            b'<Relationship Id="rel0" '
            b'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel" '
            b'Target="http://example.com/evil" TargetMode="External"/>'
            b"</Relationships>"
        ),
    }
    path = _write_zip(tmp_path, "external_rel.3mf", entries)

    with pytest.raises(ModelValidationError) as excinfo:
        validate_model(path, "3mf")

    assert excinfo.value.code == "external_relationship_forbidden"


def test_3mf_xml_doctype_rejected(tmp_path: Path) -> None:
    entries = {
        "[Content_Types].xml": _CONTENT_TYPES_XML,
        "_rels/.rels": (
            b'<?xml version="1.0"?>'
            b'<!DOCTYPE Relationships [<!ENTITY xxe "test">]>'
            b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'
        ),
    }
    path = _write_zip(tmp_path, "doctype.3mf", entries)

    with pytest.raises(ModelValidationError) as excinfo:
        validate_model(path, "3mf")

    assert excinfo.value.code == "xml_declaration_forbidden"


def test_3mf_doctype_in_content_types_is_rejected(tmp_path: Path) -> None:
    entries = _valid_3mf_entries()
    entries["[Content_Types].xml"] = (
        b'<?xml version="1.0"?>'
        b'<!DOCTYPE Types [<!ENTITY unsafe "expanded">]>'
        b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>'
    )
    path = _write_zip(tmp_path, "content_types_doctype.3mf", entries)

    with pytest.raises(ModelValidationError) as excinfo:
        validate_model(path, "3mf")

    assert excinfo.value.code == "xml_declaration_forbidden"


def test_3mf_compression_ratio_limit_rejected(tmp_path: Path) -> None:
    entries = {"payload.bin": b"A" * 50_000}
    path = _write_zip(tmp_path, "ratio.3mf", entries, compress_type=ZIP_DEFLATED)
    limits = ValidationLimits(max_archive_compression_ratio=2)

    with pytest.raises(ModelValidationError) as excinfo:
        validate_model(path, "3mf", limits=limits)

    assert excinfo.value.code == "archive_compression_ratio_exceeded"


def test_source_byte_limit_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, "oversized.stl", b"x" * 64)
    limits = ValidationLimits(max_bytes=10)

    with pytest.raises(ModelValidationError) as excinfo:
        validate_model(path, "stl", limits=limits)

    assert excinfo.value.code == "source_too_large"


def test_binary_stl_triangle_limit_rejected(tmp_path: Path) -> None:
    data = _binary_stl_bytes(
        [
            ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
            ((0.0, 0.0, 1.0), (1.0, 0.0, 1.0), (0.0, 1.0, 1.0)),
        ]
    )
    path = _write(tmp_path, "too_many_triangles.stl", data)
    limits = ValidationLimits(max_triangles=1)

    with pytest.raises(ModelValidationError) as excinfo:
        validate_model(path, "stl", limits=limits)

    assert excinfo.value.code == "triangle_limit_exceeded"
