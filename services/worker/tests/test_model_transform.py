"""The configured transformation changes real geometry, not only a browser camera."""

from hashlib import sha256

import pytest
from xxx_api.schemas.model_options import ModelOptions

from xxx_worker.model_transform import prepare_transformed_model, transform_point
from xxx_worker.validation import validate_model


@pytest.mark.parametrize("kind", ["stl", "obj"])
def test_prepared_mesh_units_rotation_and_original_are_consistent(tmp_path, kind):
    if kind == "stl":
        data = (
            b"solid t\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\n"
            b"vertex 2 0 0\nvertex 0 3 4\nendloop\nendfacet\nendsolid t\n"
        )
    else:
        data = b"v 0 0 0\nv 2 0 0\nv 0 3 4\nf 1 2 3\n"
    source = tmp_path / f"original.{kind}"
    source.write_bytes(data)
    target = tmp_path / f"configured.{kind}"
    original = validate_model(source, kind)
    options = ModelOptions(sourceUnit="inch", rotationX=90, rotationY=0)
    prepare_transformed_model(
        source, target, model_format=kind, triangle_count=original.triangle_count, options=options
    )
    result = validate_model(target, kind)
    assert result.dimensions_um == (50800, 101600, 76200)
    assert source.read_bytes() == data
    assert original.verified_sha256 == sha256(data).hexdigest()
    assert result.verified_sha256 != original.verified_sha256


def test_rotation_order_is_x_then_y_and_angles_are_bounded():
    assert transform_point((0, 1, 0), ModelOptions(rotationX=90, rotationY=90)) == pytest.approx(
        (1, 0, 0), abs=1e-12
    )
    with pytest.raises(ValueError):
        ModelOptions(rotationX=181)
