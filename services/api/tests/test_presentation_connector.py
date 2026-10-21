"""Exact free-queue profiles and physical-slot selection, using a loopback printer only."""

import asyncio
import json
from hashlib import sha256
from uuid import uuid4

import pytest
from services.bridge.commerce_connector import ConnectorConfig
from services.bridge.presentation_connector import PresentationConnector
from services.bridge.print_station import Mapping, Station
from test_print_station import configuration, paired_moonraker, simulated_printer


def setup(tmp_path, port, colour, slot, colour_hex):
    config = configuration(tmp_path)
    config.printer.transport = "moonraker"
    config.printer.zmod_start_reviewed = True
    config.printer.mappings[f"PLA:{colour}"] = Mapping(slot=slot, colour_hex=colour_hex)
    station = Station(config, tmp_path / "jobs", enable_printer=True, driver=paired_moonraker(port))
    _, files = station.profile("PLA")
    files["process.json"] = json.dumps(
        {
            **json.loads(files["process.json"]),
            "layer_height": "0.15",
            "sparse_infill_density": "30%",
            "enable_support": "1",
            "curr_bed_type": config.bed_type,
        },
        sort_keys=True,
    ).encode()
    digest = sha256()
    for name in ("machine.json", "process.json", "filament.json"):
        digest.update(name.encode() + b"\0" + files[name])
    raw = (
        b"; curr_bed_type = Textured PEI Plate\n; filament_type = PLA\n"
        b"; filament_colour = #FF0000\n; layer_height = 0.15\n"
        b"; sparse_infill_density = 30%\n; enable_support = 1\n\nT0\nG28\nG1 X1 Y2 E0.1\n"
    )
    identifier = str(uuid4())
    claim = {
        "jobId": identifier,
        "artifactSha256": sha256(raw).hexdigest(),
        "downloadUrl": f"/api/v1/bridge/presentation/dispatches/{identifier}/artifact",
        "specification": {
            "materialCode": "pla",
            "colour": colour,
            "profileSha256": digest.hexdigest(),
            "settings": {"layerHeightMm": "0.15", "infillPercent": 30, "supports": True},
        },
        "profile": {name: data.decode() for name, data in files.items()},
    }

    class API:
        def __init__(self):
            self.events = []

        def request(self, path, body=None, *, binary=False):
            if path.endswith("/claim"):
                return claim
            if binary:
                return raw
            if path.endswith("/events"):
                self.events.append(body)
            return {"items": []}

    api = API()
    connector = PresentationConnector(
        station, ConnectorConfig(api_origin="http://127.0.0.1:1", credential="fictional"), api=api
    )
    row, _ = connector.reserve(identifier, identifier)
    return connector, row, api, claim, raw


@pytest.mark.parametrize("colour,slot,colour_hex", [("white", 4, "#FFFFFF"), ("red", 3, "#F72224")])
def test_queue_uses_commissioned_colour_slot_and_sends_once(tmp_path, colour, slot, colour_hex):
    with simulated_printer(moonraker=True) as (port, events, detail):
        detail["matlStationInfo"]["slotInfos"] = [
            {
                "slotId": slot,
                "materialName": "PLA",
                "materialColor": colour_hex,
                "hasFilament": True,
            }
        ]
        connector, row, api, _, raw = setup(tmp_path, port, colour, slot, colour_hex)
        asyncio.run(connector.dispatch(row))
        assert [item["state"] for item in api.events] == ["sent", "awaiting_start"]
        wire = (connector.station.directory / row["id"] / "zmod.gcode").read_bytes()
        assert f"0|{colour_hex.lower()}|pla".encode() in wire
        assert [line for line in wire.splitlines() if line and not line.startswith(b";")] == [
            line for line in raw.splitlines() if line and not line.startswith(b";")
        ]
        start = json.loads(next(item[2] for item in events if item[0] == "/printGcode"))
        assert start["materialMappings"] == [
            {
                "toolId": 0,
                "slotId": slot,
                "materialName": "PLA",
                "toolMaterialColor": colour_hex,
                "slotMaterialColor": colour_hex,
            }
        ]
        asyncio.run(connector.dispatch(row))
        assert len([item for item in events if item[0] == "/printGcode"]) == 1


@pytest.mark.parametrize("change", ["profile", "artifact", "settings", "command_profile"])
def test_unapproved_profile_or_artifact_never_reaches_upload(tmp_path, change):
    with simulated_printer(moonraker=True) as (port, events, _):
        connector, row, api, claim, _ = setup(tmp_path, port, "red", 1, "#FF0000")
        if change == "profile":
            claim["specification"]["profileSha256"] = "f" * 64
        if change == "artifact":
            claim["artifactSha256"] = "f" * 64
        if change == "settings":
            claim["specification"]["settings"]["infillPercent"] = 40
        if change == "command_profile":
            machine = json.loads(claim["profile"]["machine.json"])
            machine["machine_start_gcode"] = "UNREVIEWED"
            claim["profile"]["machine.json"] = json.dumps(machine)
            digest = sha256()
            for name in ("machine.json", "process.json", "filament.json"):
                digest.update(name.encode() + b"\0" + claim["profile"][name].encode())
            claim["specification"]["profileSha256"] = digest.hexdigest()
        asyncio.run(connector.dispatch(row))
        assert api.events[-1]["state"] == "refused"
        assert not [item for item in events if item[0] in {"/server/files/upload", "/printGcode"}]
