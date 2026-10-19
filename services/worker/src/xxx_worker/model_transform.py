"""Prepare an explicit transformed mesh; originals and their integrity evidence stay intact."""

from math import cos, radians, sin
from pathlib import Path
from struct import Struct, pack, unpack

from xxx_api.schemas.model_options import ModelOptions

from xxx_worker.validation import ModelValidationError

TRIANGLE = Struct("<12fH")


def transform_point(
    point: tuple[float, float, float], options: ModelOptions, *, normal: bool = False
) -> tuple[float, float, float]:
    scale = 1 if normal or options.source_unit == "mm" else 25.4
    x, y, z = (value * scale for value in point)
    rx, ry = radians(options.rotation_x), radians(options.rotation_y)
    # This exact X-then-Y convention is also used by the browser's geometry matrix.
    y, z = y * cos(rx) - z * sin(rx), y * sin(rx) + z * cos(rx)
    x, z = x * cos(ry) + z * sin(ry), -x * sin(ry) + z * cos(ry)
    return x, y, z


def prepare_transformed_model(
    source: Path,
    destination: Path,
    *,
    model_format: str,
    triangle_count: int | None,
    options: ModelOptions,
) -> None:
    """Accept only already-validated STL/OBJ and write one new scratch file, never overwrite."""
    if model_format == "stl":
        assert triangle_count is not None
        with source.open("rb") as stream:
            header = stream.read(84)
        binary = (
            len(header) == 84 and 84 + unpack("<I", header[80:84])[0] * 50 == source.stat().st_size
        )
        with destination.open("xb") as output:
            output.write(b"PrintFlow transformed mesh".ljust(80, b" ") + pack("<I", triangle_count))
            if binary:
                with source.open("rb") as stream:
                    stream.seek(84)
                    for _ in range(triangle_count):
                        values = TRIANGLE.unpack(stream.read(50))
                        points = [
                            transform_point((values[i], values[i + 1], values[i + 2]), options)
                            for i in (3, 6, 9)
                        ]
                        output.write(TRIANGLE.pack(0, 0, 0, *points[0], *points[1], *points[2], 0))
            else:
                points = []
                observed = 0
                with source.open("r", encoding="ascii") as stream:
                    for line in stream:
                        fields = line.split()
                        if fields and fields[0].lower() == "vertex":
                            points.append(
                                transform_point(
                                    (float(fields[1]), float(fields[2]), float(fields[3])), options
                                )
                            )
                            if len(points) == 3:
                                output.write(
                                    TRIANGLE.pack(0, 0, 0, *points[0], *points[1], *points[2], 0)
                                )
                                observed += 1
                                points = []
                if points or observed != triangle_count:
                    raise ModelValidationError("stl_structure_invalid")
    elif model_format == "obj":
        with (
            source.open("r", encoding="utf-8") as stream,
            destination.open("x", encoding="utf-8") as output,
        ):
            for line in stream:
                fields = line.split()
                if fields and fields[0] in {"v", "vn"}:
                    transformed = transform_point(
                        (float(fields[1]), float(fields[2]), float(fields[3])),
                        options,
                        normal=fields[0] == "vn",
                    )
                    output.write(
                        " ".join(
                            [fields[0], *(f"{value:.12g}" for value in transformed), *fields[4:]]
                        )
                        + "\n"
                    )
                else:
                    output.write(line)
    else:
        raise ModelValidationError("model_transform_unsupported")
