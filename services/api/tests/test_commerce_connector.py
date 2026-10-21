"""Use the unchanged real driver against a loopback-only AD5X protocol simulator."""

import asyncio
from hashlib import sha256
from uuid import uuid4

import pytest
from services.bridge.commerce_connector import ApprovedProfile, CommerceConnector, ConnectorConfig
from services.bridge.print_station import Station
from test_print_station import configuration, paired_moonraker, simulated_printer

RAW = (
    b"; curr_bed_type = Textured PEI Plate\n; filament_type = PLA\n"
    b"; filament_colour = #FF0000\nG28\n"
)


class API:
    def __init__(self, claim, *, reject_sent=False, reject_event=None):
        self.claim = claim
        self.events = []
        self.reject_sent = reject_sent
        self.reject_event = reject_event

    def request(self, path, body=None, *, binary=False):
        if path.endswith("/claim"):
            return self.claim
        if binary:
            return RAW
        if path.endswith("/events"):
            self.events.append(body)
            if body["state"] == "sent" and self.reject_sent:
                raise OSError("fictional API outage")
            if body["state"] == self.reject_event:
                raise OSError("fictional telemetry outage")
            return {}
        return {"items": []}


def setup(tmp_path, port, **changes):
    config = configuration(tmp_path)
    config.printer.transport = "moonraker"
    config.printer.zmod_start_reviewed = True
    station = Station(config, tmp_path / "jobs", enable_printer=True, driver=paired_moonraker(port))
    auth, job = str(uuid4()), str(uuid4())
    claim = {
        "jobId": job,
        "artifactSha256": sha256(RAW).hexdigest(),
        "downloadUrl": f"/api/v1/bridge/dispatches/{auth}/artifact",
        "specification": {"materialCode": "pla", "colour": "red", "profileSha256": "b" * 64},
    }
    api = API(claim, **changes)
    connector = CommerceConnector(
        station,
        ConnectorConfig(
            api_origin="http://127.0.0.1:1",
            credential="fictional-not-production",
            approved_profiles=[
                ApprovedProfile(
                    profileSha256="b" * 64, material="PLA", stationBedType="Textured PEI Plate"
                )
            ],
        ),
        api=api,
    )
    row, created = connector.reserve(auth, job)
    assert created
    return connector, row, api


def test_connector_uploads_once_and_replays_exact_telemetry_without_resending(tmp_path):
    with simulated_printer(moonraker=True) as (port, events, _detail):
        connector, row, api = setup(tmp_path, port)
        asyncio.run(connector.dispatch(row))
        assert [event["state"] for event in api.events] == ["sent", "awaiting_start"]
        assert len([event for event in events if event[0] == "/server/files/upload"]) == 1
        assert len([event for event in events if event[0] == "/printGcode"]) == 1
        current = connector.station.journal.get(row["id"])
        assert current["start_intent"] and current["phase"] == "awaiting_start"
        wire = (connector.station.directory / row["id"] / "zmod.gcode").read_bytes()
        assert wire.endswith(RAW) and wire.startswith(b"; MD5:")
        assert sha256(wire).hexdigest() == current["dispatch_sha256"]
        assert connector.reserve(row["authorization_id"], row["commerce_job_id"])[1] is False
        connector.station.journal.recover()
        asyncio.run(connector.tick())
        assert len([event for event in events if event[0] == "/printGcode"]) == 1
        assert connector.station.journal.get(row["id"])["phase"] == "needs_attention"


def test_uncertain_api_ack_makes_zero_uploads_and_keeps_identical_event(tmp_path):
    with simulated_printer(moonraker=True) as (port, events, _):
        connector, row, api = setup(tmp_path, port, reject_sent=True)
        asyncio.run(connector.dispatch(row))
        current = connector.station.journal.get(row["id"])
        assert current["phase"] == "needs_attention"
        assert current["start_intent"]
        assert not [
            event for event in events if event[0] in {"/server/files/upload", "/printGcode"}
        ]
        assert api.events[0] == api.events[1]
        api.reject_sent = False
        asyncio.run(connector.tick())
        assert api.events[0] == api.events[2]
        assert not [event for event in events if event[0] == "/printGcode"]


@pytest.mark.parametrize(
    "issue", ["hash", "profile", "bed", "colour", "busy", "disabled", "approval", "petg"]
)
def test_connector_refuses_before_send_on_invalid_evidence(tmp_path, issue):
    with simulated_printer(moonraker=True) as (port, events, detail):
        connector, row, api = setup(tmp_path, port)
        if issue == "hash":
            api.claim["artifactSha256"] = "c" * 64
        if issue == "profile":
            api.claim["specification"]["profileSha256"] = "c" * 64
        if issue == "bed":
            connector.station.config.bed_type = "Cool Plate"
        if issue == "colour":
            connector.station.config.printer.mappings["PLA:red"].colour_hex = "#000000"
        if issue == "busy":
            detail["status"] = "busy"
        if issue == "disabled":
            connector.station.enabled = False
        if issue == "approval":
            connector.station.config.printer.zmod_start_reviewed = False
        if issue == "petg":
            api.claim["specification"]["materialCode"] = "petg"
        asyncio.run(connector.dispatch(row))
        assert connector.station.journal.get(row["id"])["phase"] == "failed"
        assert api.events[-1]["state"] == "refused"
        assert not [
            event for event in events if event[0] in {"/server/files/upload", "/printGcode"}
        ]


def test_native_start_cannot_accept_a_commerce_journal_row(tmp_path):
    from pydantic import ValidationError
    from services.bridge.print_station import PrintOptions

    with simulated_printer(moonraker=True) as (port, _, _):
        _connector, row, _ = setup(tmp_path, port)
        with pytest.raises(ValidationError):
            PrintOptions.model_validate(row["options"])


def test_post_upload_api_outage_retries_only_identical_event_not_the_print(tmp_path):
    with simulated_printer(moonraker=True) as (port, events, _):
        connector, row, api = setup(tmp_path, port, reject_event="awaiting_start")
        asyncio.run(connector.dispatch(row))
        pending = connector.station.journal.get(row["id"])["outbox"][0]
        assert pending["state"] == "awaiting_start"
        api.reject_event = None
        asyncio.run(connector.tick())
        assert pending == api.events[-1]
        assert connector.station.journal.get(row["id"])["outbox"] == []
        assert len([item for item in events if item[0] == "/printGcode"]) == 1


def test_connector_runner_refuses_the_native_station_lock_without_reading_configuration(tmp_path):
    import fcntl
    import subprocess
    import sys
    from pathlib import Path

    station = tmp_path / "station"
    station.mkdir()
    with (station / "station.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve().parents[3] / "tools/run_commerce_station.py"),
                "--station-directory",
                str(station),
                "--connector-directory",
                str(tmp_path / "connector"),
                "run",
                "--enable-printer",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        assert result.returncode == 1
        assert "already running" in result.stderr
        assert not (tmp_path / "connector").exists()


@pytest.mark.parametrize("status", [401, 404, 409])
def test_rejected_claim_releases_local_active_slot_without_a_send_intent(tmp_path, status):
    from urllib.error import HTTPError

    with simulated_printer(moonraker=True) as (port, events, _):
        connector, row, api = setup(tmp_path, port)
        original = api.request

        def request(path, body=None, *, binary=False):
            if path.endswith("/claim") or path.endswith("/events"):
                raise HTTPError(
                    "http://127.0.0.1/fixture", status, "fictional rejection", None, None
                )
            return original(path, body, binary=binary)

        api.request = request
        asyncio.run(connector.dispatch(row))
        actual = connector.station.journal.get(row["id"])
        assert actual["phase"] == "failed" and not actual.get("start_intent")
        assert not [
            event for event in events if event[0] in {"/server/files/upload", "/printGcode"}
        ]
        assert connector.reserve(str(uuid4()), str(uuid4()))[1] is True
