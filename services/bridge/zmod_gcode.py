"""Single-tool subset of ZMOD's documented preprocessor wire format.

Reference: ghzserg/zmod_preprocess/zmod-preprocess.py. No tool remapping,
movement, heating or macro injection: only metadata comments plus its checksum.
SHA-256 remains the station's artifact identity; MD5 is a ZMOD compatibility field.
"""

import re
from hashlib import md5, sha256
from pathlib import Path

from services.bridge.ad5x_lan import PrinterError


def prepare_zmod_gcode(
    source: Path, destination: Path, *, material: str, colour_hex: str | None = None
) -> str:
    if not 0 < source.stat().st_size <= 200 * 1024 * 1024:
        raise PrinterError("Invalid G-code size for ZMOD preparation.")
    data = source.read_bytes()
    text = data.decode("utf-8")
    tools = {int(value) for value in re.findall(r"^T([0-9]+)(?=[\s;]|$)", text, re.MULTILINE)}
    if tools - {0}:
        raise PrinterError("This station only supports one material and tool T0.")
    colour = re.findall(r"^; filament_colour = (#[0-9a-fA-F]{6})[ \t]*\r?$", text, re.MULTILINE)
    types = re.findall(r"^; filament_type = ([A-Z0-9-]+)[ \t]*\r?$", text, re.MULTILINE)
    if (
        len(colour) != 1
        or types != [material]
        or re.search(r"^;\s*(?:MD5:|zmod_color_data\s*=)", text, re.MULTILINE | re.IGNORECASE)
    ):
        raise PrinterError("ZMOD needs unambiguous, single-material Orca metadata.")
    if colour_hex is not None:
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", colour_hex):
            raise PrinterError("Invalid commissioned single-tool colour metadata.")
        # Colour is a comment only. Keep every motion/heater/tool command unchanged;
        # the native start separately pins T0 to the verified loaded physical slot.
        text = re.sub(
            r"^; filament_colour = #[0-9a-fA-F]{6}[ \t]*(?=\r?$)",
            f"; filament_colour = {colour_hex}",
            text,
            count=1,
            flags=re.MULTILINE,
        )
        data = text.encode("utf-8")
        colour = [colour_hex]
    # Match the official preprocessor's case-folded metadata representation.
    body = f"; zmod_color_data = 0|{colour[0].lower()}|{material.lower()}\r\n".encode() + data
    compatibility_hash = md5(body, usedforsecurity=False).hexdigest()
    output = f"; MD5:{compatibility_hash}\r\n".encode() + body
    with destination.open("xb") as stream:
        stream.write(output)
    return sha256(output).hexdigest()
