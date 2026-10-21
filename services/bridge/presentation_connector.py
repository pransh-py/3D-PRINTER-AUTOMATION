"""Free FIFO adapter using the commissioned station's one-shot dispatch boundary."""

import asyncio
import json
import re
from hashlib import sha256
from uuid import uuid4

from services.bridge.ad5x_lan import PrinterError
from services.bridge.commerce_connector import CommerceConnector
from services.bridge.print_station import PrintOptions
from services.bridge.zmod_gcode import prepare_zmod_gcode


class PresentationConnector(CommerceConnector):
    job_kind = "presentation"
    dispatch_path = "/api/v1/bridge/presentation/dispatches"
    heartbeat_path = "/api/v1/bridge/presentation/heartbeat"

    async def request(self, path, body=None, *, binary=False):
        if path == self.heartbeat_path:
            state = "offline"
            try:
                driver = self.station.driver
                if driver is not None:
                    status = await asyncio.to_thread(driver.status)
                    state = (
                        "ready"
                        if status.state in {"ready", "completed"}
                        and not status.error
                        and not status.heaters_active
                        else "busy"
                    )
            except (OSError, ValueError, PrinterError):
                state = "offline"
            body = {"state": state}
        return await super().request(path, body, binary=binary)

    def verify(self, claim, raw):
        specification = claim["specification"]
        settings = specification["settings"]
        material = specification["materialCode"].upper()
        options = PrintOptions(
            client_token=uuid4(),
            filename="presentation.stl",
            size=1,
            source_sha256="0" * 64,
            material=material,
            colour=specification["colour"],
            layer_height=settings["layerHeightMm"],
            infill=settings["infillPercent"],
            supports=settings["supports"],
            print_now=True,
            readiness_confirmed=True,
        )
        self.station.validate_options(options)
        profile, original = self.station.profile(material)
        if not profile.approved_for_printer or not self.station.enabled:
            raise ValueError("profile_not_approved")
        files = claim["profile"]
        digest = sha256()
        for name in ("machine.json", "process.json", "filament.json"):
            data = files[name].encode("utf-8")
            if len(data) > 1048576:
                raise ValueError("profile_invalid")
            digest.update(name.encode() + b"\0" + data)
        if digest.hexdigest() != specification["profileSha256"]:
            raise ValueError("profile_hash_mismatch")
        for name in ("machine.json", "filament.json"):
            if json.loads(files[name]) != json.loads(original[name]):
                raise ValueError("profile_not_derived_from_commissioned_base")
        process = json.loads(original["process.json"])
        process.update(
            layer_height=options.layer_height,
            sparse_infill_density=f"{options.infill}%",
            enable_support=str(int(options.supports)),
            curr_bed_type=self.station.config.bed_type,
        )
        if json.loads(files["process.json"]) != process:
            raise ValueError("process_not_derived_from_commissioned_base")
        if sha256(raw).hexdigest() != claim["artifactSha256"]:
            raise ValueError("artifact_hash_mismatch")
        text = raw.decode("utf-8")
        for key, expected in [
            ("curr_bed_type", self.station.config.bed_type),
            ("filament_type", material),
            ("layer_height", options.layer_height),
            ("sparse_infill_density", f"{options.infill}%"),
            ("enable_support", str(int(options.supports))),
        ]:
            values = re.findall(rf"^; {key} = ([^\r\n]+)\r?$", text, re.MULTILINE)
            if len(values) != 1 or values[0].strip() != expected:
                raise ValueError("gcode_metadata_mismatch")
        return options, self.station.mapping(options)

    def prepare_wire(self, source, destination, options, mapping):
        return prepare_zmod_gcode(
            source,
            destination,
            material=options.material,
            colour_hex=mapping.colour_hex,
        )
