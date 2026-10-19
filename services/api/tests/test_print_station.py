"""Physical commands target only a loopback HTTP simulator, never a printer.

Station slicing here is a deterministic fixture; genuine Orca is exercised by the
local browser acceptance run, not claimed by these unit/transport tests.
"""

import asyncio
import json
import os
import threading
import time
from contextlib import contextmanager
from hashlib import md5, sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from xxx_worker.slicing import SliceResult

from services.bridge.ad5x_lan import AD5XLan, PrinterError, PrinterStatus
from services.bridge.moonraker_lan import MoonrakerLan
from services.bridge.print_station import (
    Connection,
    Journal,
    Mapping,
    PrintOptions,
    Profile,
    StationConfig,
    StationPricing,
    create_app,
    estimate_slice,
    private_lan_ipv4,
)
from services.bridge.zmod_gcode import prepare_zmod_gcode


@contextmanager
def simulated_printer(*, moonraker=False, ambiguous=False):
    events = []
    detail = {
        "pid": "38",
        "status": "ready",
        "firmwareVersion": "SIMULATOR",
        "hasMatlStation": True,
        "matlStationInfo": {
            "slotInfos": [
                {
                    "slotId": 1,
                    "materialName": "PLA",
                    "materialColor": "#FF0000",
                    "hasFilament": True,
                }
            ]
        },
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path == "/server/job_queue/status":
                self.reply(
                    {"result": {"queue_state": "paused", "queued_jobs": detail.get("_queue", [])}}
                )
            elif self.path.startswith("/server/history/list"):
                self.reply({"result": {"jobs": detail.get("_history", [])}})
            else:
                self.reply({"result": {"state": "ready", "software_version": "SIMULATOR"}})

        def do_POST(self):
            data = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            events.append((self.path, dict(self.headers), data))
            if self.path == "/detail":
                self.reply({"code": 0, "detail": detail})
            elif self.path == "/printer/objects/query":
                self.reply(
                    {
                        "result": {
                            "status": detail.get(
                                "_moonraker",
                                {
                                    "print_stats": {"state": "standby", "filename": ""},
                                    "virtual_sdcard": {"progress": 0, "is_active": False},
                                    "idle_timeout": {"state": "Ready"},
                                    "extruder": {"target": 0},
                                    "heater_bed": {"target": 0},
                                },
                            )
                        }
                    }
                )
            elif ambiguous:
                self.connection.shutdown(2)
            elif moonraker:
                import re

                name = re.search(rb'filename="([^"]+)"', data)[1].decode()
                self.reply(
                    {"item": {"path": name}, "print_started": True, "print_queued": False}, 201
                )
            else:
                self.reply({"code": 0})

        def reply(self, payload, status=200):
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port, events, detail
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.parametrize(
    "host", ["8.8.8.8", "127.0.0.1", "169.254.1.2", "example.com", "0.0.0.0", "100.64.0.1"]
)
def test_no_public_dns_linklocal_or_implicit_loopback(host):
    with pytest.raises(ValueError):
        AD5XLan(host, "local-test", "local-test")
    with pytest.raises(ValueError):
        MoonrakerLan(host)


def test_stock_transport_validates_identity_ready_spool_and_uploads_once(tmp_path):
    with simulated_printer() as (port, events, detail):
        driver = AD5XLan(
            "127.0.0.1", "simulation-id", "simulation-code", port=port, allow_loopback_test=True
        )
        status = driver.status()
        slot = driver.require_ready(status, slot=1, material="PLA", colour_hex="#FF0000")
        with pytest.raises(PrinterError):
            driver.require_ready(status, slot=1, material="PETG", colour_hex="#FF0000")
        package = tmp_path / "fixture.3mf"
        package.write_bytes(b"TRANSPORT FIXTURE ONLY")
        driver.upload_and_print(package, filename=f"pf_{uuid4().hex}_{'a' * 12}.3mf", slot=slot)
        assert [e[0] for e in events] == ["/detail", "/uploadGcode"]
        assert events[-1][1]["printNow"] == "true"
        detail["pid"] = "35"
        with pytest.raises(PrinterError):
            driver.status()


def test_zmod_uses_gcode_checksum_and_immediate_start_not_3mf(tmp_path):
    with simulated_printer(moonraker=True) as (port, events, _):
        driver = MoonrakerLan("127.0.0.1", port=port, allow_loopback_test=True)
        status = driver.status()
        slot = driver.require_ready(status, slot=1, material="PLA", colour_hex="#FF0000")
        source = tmp_path / "fixture.gcode"
        source.write_bytes(b"; TRANSPORT FIXTURE ONLY\n")
        driver.upload_and_print(source, filename=f"pf_{uuid4().hex}_{'a' * 12}.gcode", slot=slot)
        path, _, body = events[-1]
        assert path == "/server/files/upload"
        assert (
            b'name="checksum"' in body and sha256(source.read_bytes()).hexdigest().encode() in body
        )
        assert b'name="print"\r\n\r\ntrue' in body
        assert b".3mf" not in body


def configuration(tmp_path):
    directory = tmp_path / "profiles"
    directory.mkdir()
    values = {
        "machine.json": {"name": "Flashforge AD5X 0.4 nozzle", "nozzle_diameter": ["0.4"]},
        "process.json": {
            "layer_height": "0.2",
            "sparse_infill_density": "20%",
            "enable_support": "0",
            "wall_loops": "2",
        },
        "filament.json": {"filament_type": ["PLA"]},
    }
    digest = sha256()
    for name, value in values.items():
        data = json.dumps(value).encode()
        (directory / name).write_bytes(data)
        digest.update(name.encode() + b"\0" + data)
    return StationConfig(
        slicer=Path("/not-executed-fixture"),
        slicer_sha256="a" * 64,
        slicer_version="SIMULATOR",
        bed_type="Textured PEI Plate",
        profiles={
            "PLA": Profile(
                directory=directory, sha256=digest.hexdigest(), approved_for_printer=True
            )
        },
        printer=Connection(
            transport="flashforge",
            host="192.168.1.2",
            serial="simulation",
            check_code="simulation",
            mappings={"PLA:red": Mapping(slot=1, colour_hex="#FF0000")},
        ),
    )


SOURCE = (
    b"solid t\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 1 0 1\n"
    b"vertex 0 1 0\nendloop\nendfacet\nendsolid t\n"
)


def options(**changes):
    return PrintOptions(
        client_token=uuid4(),
        filename="fixture.stl",
        size=len(SOURCE),
        source_sha256=sha256(SOURCE).hexdigest(),
        material="PLA",
        colour="red",
        **changes,
    )


def test_journal_rejects_duplicate_changed_payload_concurrent_job_and_recovers_intent(tmp_path):
    journal = Journal(tmp_path / "jobs.sqlite3")
    chosen = options()
    job, created = journal.create(chosen)
    assert created and not journal.create(chosen)[1]
    with pytest.raises(Exception, match="different settings"):
        journal.create(chosen.model_copy(update={"infill": 50}))
    with pytest.raises(Exception, match="current job"):
        journal.create(options())
    journal.update(job["id"], phase="starting", start_intent=1)
    journal.recover()
    assert journal.get(job["id"])["phase"] == "needs_attention"


@pytest.mark.parametrize("ambiguous", [False, True])
@pytest.mark.parametrize("moonraker", [False, True])
def test_full_station_job_duplicate_and_ambiguous_start_never_resends(
    tmp_path, monkeypatch, ambiguous, moonraker
):
    async def fixture_slice(self, source, scratch, *, quantity=1):
        (scratch / "result.3mf").write_bytes(b"SLICED PACKAGE FIXTURE ONLY")
        artifact = scratch / "approved.gcode"
        artifact.write_bytes(
            b"; GCODE FIXTURE ONLY\n; filament_colour = #FF0000\n; filament_type = PLA\n"
        )
        return SliceResult(artifact, sha256(artifact.read_bytes()).hexdigest(), 1000, 60, "a" * 64)

    monkeypatch.setattr("services.bridge.print_station.OrcaSlicer.slice", fixture_slice)
    with simulated_printer(ambiguous=ambiguous, moonraker=moonraker) as (port, events, _):
        driver = (
            MoonrakerLan("127.0.0.1", port=port, allow_loopback_test=True)
            if moonraker
            else AD5XLan(
                "127.0.0.1", "simulation", "simulation", port=port, allow_loopback_test=True
            )
        )
        config = configuration(tmp_path)
        config.pricing = StationPricing(
            material_rate_paise_per_gram=300, machine_rate_paise_per_hour=1000
        )
        if moonraker:
            config.printer.transport = "moonraker"
            config.printer.zmod_start_reviewed = True
        app = create_app(config, tmp_path / "jobs", enable_printer=True, driver=driver)
        with TestClient(app, base_url="http://127.0.0.1:8123") as client:
            assert client.post("/api/printer/jobs").status_code == 403
            status = client.get("/api/printer/status").json()
            chosen = options(print_now=True, readiness_confirmed=True)
            headers = {
                "Origin": "http://127.0.0.1:3102",
                "X-Station-Token": status["token"],
                "X-Print-Options": chosen.model_dump_json(),
            }
            assert (
                client.post(
                    "/api/printer/jobs",
                    content=SOURCE,
                    headers={**headers, "Origin": "https://evil.example"},
                ).status_code
                == 403
            )
            first = client.post("/api/printer/jobs", content=SOURCE, headers=headers)
            assert first.status_code == 202
            job_id = first.json()["id"]

            async def wait_done():
                for _ in range(100):
                    if app.state.station.journal.get(job_id)["phase"] in {
                        "awaiting_start",
                        "needs_attention",
                        "failed",
                    }:
                        return
                    await asyncio.sleep(0.02)
                raise AssertionError("Fixture job timed out")

            client.portal.call(wait_done)
            job = app.state.station.journal.get(job_id)
            assert job["phase"] == ("needs_attention" if ambiguous else "awaiting_start"), job
            assert job["estimate"]["material_paise"] == 300
            assert job["estimate"]["machine_paise"] == 17
            assert job["estimate"]["total_paise"] == 317
            again = client.post("/api/printer/jobs", content=SOURCE, headers=headers)
            assert again.status_code == 202 and again.json()["id"] == job_id
            upload_endpoint = "/server/files/upload" if moonraker else "/uploadGcode"
            assert sum(e[0] == upload_endpoint for e in events) == 1
            station = app.state.station
            station.reconcile(
                PrinterStatus("completed", 56, "SIMULATOR", "wrong-file", 1, False, ())
            )
            assert station.journal.get(job_id)["phase"] != "completed"
            if not ambiguous:
                station.reconcile(
                    PrinterStatus(
                        "printing", 56, "SIMULATOR", job["printer_filename"], 0.2, False, ()
                    )
                )
                assert station.journal.get(job_id)["phase"] == "printing"
                station.reconcile(
                    PrinterStatus(
                        "completed", 56, "SIMULATOR", job["printer_filename"], 1, False, ()
                    )
                )
                assert station.journal.get(job_id)["phase"] == "completed"


@pytest.mark.parametrize(
    "issue,expected_http,expected_phase",
    [
        ("none", 202, "awaiting_start"),
        ("ambiguous", 202, "needs_attention"),
        ("rates_changed", 202, "awaiting_start"),
        ("wrong_price", 409, "sliced"),
        ("not_ready", 422, "sliced"),
        ("artifact_changed", 202, "failed"),
        ("mapping_changed", 202, "failed"),
        ("plate_changed", 202, "failed"),
        ("profile_changed", 202, "failed"),
        ("unapproved", 409, "sliced"),
        ("disabled", 409, "sliced"),
        ("another_active", 409, "sliced"),
        ("no_estimate", 409, "sliced"),
    ],
)
def test_estimate_then_print_reuses_accepted_bytes_and_price_once(
    tmp_path, monkeypatch, issue, expected_http, expected_phase
):
    slices = []

    async def fixture_slice(self, source, scratch, *, quantity=1):
        slices.append(quantity)
        (scratch / "result.3mf").write_bytes(b"PREPARED PACKAGE FIXTURE")
        artifact = scratch / "approved.gcode"
        artifact.write_bytes(b"; FIXTURE\n; filament_colour = #FF0000\n; filament_type = PLA\n")
        return SliceResult(artifact, sha256(artifact.read_bytes()).hexdigest(), 1000, 60, "a" * 64)

    monkeypatch.setattr("services.bridge.print_station.OrcaSlicer.slice", fixture_slice)
    with simulated_printer(moonraker=True, ambiguous=issue == "ambiguous") as (port, events, _):
        config = configuration(tmp_path)
        config.pricing = StationPricing(
            material_rate_paise_per_gram=300, machine_rate_paise_per_hour=1000
        )
        config.printer.transport = "moonraker"
        config.printer.zmod_start_reviewed = True
        driver = MoonrakerLan("127.0.0.1", port=port, allow_loopback_test=True)
        app = create_app(config, tmp_path / "jobs", enable_printer=True, driver=driver)
        with TestClient(app, base_url="http://127.0.0.1:8123") as client:
            station = app.state.station
            headers = {"Origin": "http://127.0.0.1:3102", "X-Station-Token": station.token}
            chosen = options(print_now=False)
            response = client.post(
                "/api/printer/jobs",
                content=SOURCE,
                headers={**headers, "X-Print-Options": chosen.model_dump_json()},
            )
            assert response.status_code == 202
            job_id = response.json()["id"]

            async def wait_phase(phases):
                for _ in range(200):
                    job = station.journal.get(job_id)
                    if job["phase"] in phases:
                        return job
                    await asyncio.sleep(0.01)
                raise AssertionError("Prepared-print fixture timed out")

            job = client.portal.call(wait_phase, {"sliced", "failed"})
            assert job["phase"] == "sliced", job
            assert job["estimate"]["total_paise"] == 317
            assert not any(event[0] == "/server/files/upload" for event in events)
            prepared = (tmp_path / "jobs" / job_id / job["gcode_name"]).read_bytes()
            payload = {
                "client_token": str(uuid4()),
                "expected_total_paise": 317,
                "readiness_confirmed": True,
            }
            endpoint = f"/api/printer/jobs/{job_id}/start"
            assert client.post(endpoint, json=payload).status_code == 403
            assert (
                client.post(
                    endpoint, json=payload, headers={**headers, "Origin": "https://evil.example"}
                ).status_code
                == 403
            )
            if issue == "wrong_price":
                payload["expected_total_paise"] = 1
            elif issue == "not_ready":
                payload["readiness_confirmed"] = False
            elif issue == "artifact_changed":
                (tmp_path / "jobs" / job_id / job["gcode_name"]).write_bytes(b"TAMPERED")
            elif issue == "mapping_changed":
                config.printer.mappings["PLA:red"].slot = 2
            elif issue == "plate_changed":
                config.bed_type = "High Temp Plate"
            elif issue == "profile_changed":
                profile = config.profiles["PLA"]
                process = profile.directory / "process.json"
                process.write_text(
                    json.dumps({**json.loads(process.read_bytes()), "wall_loops": "3"})
                )
                digest = sha256()
                for name in ("machine.json", "process.json", "filament.json"):
                    digest.update(name.encode() + b"\0" + (profile.directory / name).read_bytes())
                profile.sha256 = digest.hexdigest()
            elif issue == "unapproved":
                config.profiles["PLA"].approved_for_printer = False
            elif issue == "disabled":
                station.enabled = False
            elif issue == "another_active":
                station.journal.create(options())
            elif issue == "no_estimate":
                station.journal.update(job_id, estimate=None)
            elif issue == "rates_changed":
                config.pricing.material_rate_paise_per_gram = 900
            result = client.post(endpoint, json=payload, headers=headers)
            assert result.status_code == expected_http, result.text
            job = client.portal.call(wait_phase, {expected_phase})
            uploads = [event for event in events if event[0] == "/server/files/upload"]
            assert slices == [1], "Starting a quote must not re-slice it."
            if issue in {"none", "ambiguous", "rates_changed"}:
                assert len(uploads) == 1 and prepared in uploads[0][2]
                assert job["estimate"]["total_paise"] == 317
                assert client.post(endpoint, json=payload, headers=headers).status_code == 202
                assert (
                    client.post(
                        endpoint, json={**payload, "client_token": str(uuid4())}, headers=headers
                    ).status_code
                    == 409
                )
                assert sum(event[0] == "/server/files/upload" for event in events) == 1
                station.journal.recover()
                assert station.journal.get(job_id)["phase"] == "needs_attention"
                assert client.post(endpoint, json=payload, headers=headers).status_code == 202
                assert sum(event[0] == "/server/files/upload" for event in events) == 1
            else:
                assert not uploads
                assert not job.get("start_intent")


@pytest.mark.parametrize(
    "scenario,expected_phase",
    [
        ("native_idle", "stopped"),
        ("cleared_moonraker_file", "stopped"),
        ("explicit_cancel", "cancelled"),
        ("history_cancel", "cancelled"),
        ("history_complete", "completed"),
        ("heating", None),
        ("executing", None),
        ("paused", None),
        ("native_busy", None),
        ("native_cancel", None),
        ("native_canceling", None),
        ("native_canceling_after_cancelled", None),
        ("native_printing_after_cancelled", None),
        ("native_error_state", None),
        ("native_paused", None),
        ("native_printing_other_file", None),
        ("native_printing_no_file", None),
        ("native_other_file", None),
        ("other_moonraker_file", None),
        ("native_error", None),
        ("queued", None),
        ("unpaired", None),
        ("initial_delay", None),
        ("reset_observations", "stopped"),
        ("disconnect_reset", "stopped"),
    ],
)
def test_automatic_terminal_detection_requires_consistent_inactive_printer_evidence(
    tmp_path, monkeypatch, scenario, expected_phase
):
    clock = [time.time()]
    monkeypatch.setattr("services.bridge.print_station.time.time", lambda: clock[0])
    monkeypatch.setattr("services.bridge.print_station.monotonic", lambda: clock[0])
    with simulated_printer(moonraker=True) as (port, events, detail):
        detail.update(pid=38, name="AD5X", printFileName="")
        native = AD5XLan(
            "127.0.0.1", "simulation", "simulation", port=port, allow_loopback_test=True
        )
        driver = MoonrakerLan(
            "127.0.0.1",
            port=port,
            allow_loopback_test=True,
            native=None if scenario == "unpaired" else native,
        )
        config = configuration(tmp_path)
        app = create_app(config, tmp_path / "jobs", enable_printer=True, driver=driver)
        with TestClient(app, base_url="http://127.0.0.1:8123") as client:
            station = app.state.station
            job, _ = station.journal.create(options())
            filename = f"pf_{job['id']}_{'b' * 12}.gcode"
            station.journal.update(
                job["id"],
                phase="awaiting_start",
                start_intent=clock[0] - 120,
                printer_filename=filename,
            )
            if scenario == "initial_delay":
                station.journal.update(job["id"], start_intent=clock[0] - 30)
            detail["_moonraker"] = {
                "print_stats": {"state": "standby", "filename": filename},
                "virtual_sdcard": {"is_active": False, "progress": 0},
                "idle_timeout": {"state": "Ready"},
                "extruder": {"target": 0},
                "heater_bed": {"target": 0},
            }
            moon = detail["_moonraker"]
            if scenario == "cleared_moonraker_file":
                moon["print_stats"]["filename"] = ""
            elif scenario == "explicit_cancel":
                moon["print_stats"]["state"] = "cancelled"
            elif scenario in {"history_cancel", "history_complete"}:
                detail["_history"] = [
                    {
                        "filename": filename,
                        "status": "cancelled" if scenario == "history_cancel" else "completed",
                    }
                ]
            elif scenario == "heating":
                moon["heater_bed"]["target"] = 55
            elif scenario == "executing":
                moon["virtual_sdcard"]["is_active"] = True
            elif scenario == "paused":
                moon["print_stats"]["state"] = "paused"
            elif scenario == "native_busy":
                detail["status"] = "busy"
            elif scenario in {"native_cancel", "native_canceling", "native_paused"}:
                detail["status"] = {
                    "native_cancel": "cancel",
                    "native_canceling": "canceling",
                    "native_paused": "pause",
                }[scenario]
            elif scenario in {"native_printing_other_file", "native_printing_no_file"}:
                detail["status"] = "printing"
                if scenario == "native_printing_other_file":
                    detail["printFileName"] = "external-job.gcode"
            elif scenario in {
                "native_canceling_after_cancelled",
                "native_printing_after_cancelled",
            }:
                moon["print_stats"]["state"] = "cancelled"
                detail["status"] = (
                    "canceling" if scenario == "native_canceling_after_cancelled" else "printing"
                )
                detail["printFileName"] = filename
            elif scenario == "native_error_state":
                moon["print_stats"]["state"] = "cancelled"
                detail["status"] = "error"
            elif scenario == "native_other_file":
                detail["printFileName"] = "external-job.gcode"
            elif scenario == "other_moonraker_file":
                moon["print_stats"]["filename"] = "external-job.gcode"
            elif scenario == "native_error":
                detail["errorCode"] = "SIMULATED_ERROR"
            elif scenario == "queued":
                detail["_queue"] = [{"filename": "external-job.gcode"}]

            client.get("/api/printer/status")
            clock[0] += 6
            client.get("/api/printer/status")
            if scenario not in {"explicit_cancel", "history_cancel", "history_complete"}:
                assert station.journal.get(job["id"])["phase"] not in {
                    "stopped",
                    "cancelled",
                    "completed",
                }
            if scenario in {"reset_observations", "disconnect_reset"}:
                if scenario == "reset_observations":
                    moon["heater_bed"]["target"] = 55
                    client.get("/api/printer/status")
                    moon["heater_bed"]["target"] = 0
                else:

                    def disconnected(self):
                        raise PrinterError("SIMULATED native disconnect")

                    with monkeypatch.context() as connection_patch:
                        connection_patch.setattr(AD5XLan, "status", disconnected)
                        assert client.get("/api/printer/status").json()["printer"] is None
                assert not station.idle_observations
                clock[0] += 20
                client.get("/api/printer/status")
                assert station.journal.get(job["id"])["phase"] != "stopped"
            clock[0] += 13
            client.get("/api/printer/status")
            client.get("/api/printer/status")
            result = station.journal.get(job["id"])
            if expected_phase:
                assert result["phase"] == expected_phase, result
                station.journal.create(options())  # The terminal job releases the active-job lock.
            else:
                assert result["phase"] not in {"stopped", "cancelled", "completed"}, result
                if scenario in {"native_printing_other_file", "native_printing_no_file"}:
                    assert result["phase"] != "printing", result
                with pytest.raises(Exception, match="current job"):
                    station.journal.create(options())
            assert not any(event[0] in {"/server/files/upload", "/uploadGcode"} for event in events)


def test_native_numeric_ad5x_identity_and_live_spool_verification():
    with simulated_printer(moonraker=True) as (port, _, detail):
        detail.update(pid=38, name="AD5X", printFileName="")
        native = AD5XLan(
            "127.0.0.1", "simulation", "simulation", port=port, allow_loopback_test=True
        )
        driver = MoonrakerLan("127.0.0.1", port=port, allow_loopback_test=True, native=native)
        status = driver.status()
        assert status.model_pid == 38 and status.native_state == "ready"
        assert driver.require_ready(status, slot=1, material="PLA", colour_hex="#FF0000")
        with pytest.raises(PrinterError, match="IFS slot"):
            driver.require_ready(status, slot=3, material="PLA", colour_hex="#FF0000")
        detail["name"] = "OTHER_MODEL"
        with pytest.raises(PrinterError, match="AD5X"):
            native.status()


def test_physical_start_disabled_and_unconfirmed_colours_rejected(tmp_path):
    config = configuration(tmp_path)
    config.printer = None
    app = create_app(config, tmp_path / "jobs", enable_printer=False)
    with TestClient(app, base_url="http://127.0.0.1:8123") as client:
        # No network status call: obtain the per-process CSRF token directly in this test.
        headers = {"Origin": "http://127.0.0.1:3102", "X-Station-Token": app.state.station.token}
        for chosen in (
            options(print_now=True, readiness_confirmed=True),
            options().model_copy(update={"colour": "blue"}),
        ):
            response = client.post(
                "/api/printer/jobs",
                content=SOURCE,
                headers={**headers, "X-Print-Options": chosen.model_dump_json()},
            )
            assert response.status_code in {409, 422}
        assert not app.state.station.journal.all()


@pytest.mark.parametrize("web_port", [3100, 3102])
def test_station_accepts_only_the_configured_local_web_origin(tmp_path, web_port):
    config = configuration(tmp_path)
    config.printer = None
    config.web_port = web_port
    app = create_app(config, tmp_path / "jobs")
    with TestClient(app, base_url=f"http://127.0.0.1:{web_port}") as client:
        assert client.get("/api/printer/status").status_code == 200
        headers = {
            "Origin": f"http://127.0.0.1:{web_port}",
            "X-Station-Token": app.state.station.token,
        }
        # An invalid body gets past the origin gate only for the configured origin.
        assert client.post("/api/printer/jobs", headers=headers).status_code == 422
        other_port = 3102 if web_port == 3100 else 3100
        for origin in (f"http://127.0.0.1:{other_port}", "https://evil.example", "null"):
            assert (
                client.post("/api/printer/jobs", headers={**headers, "Origin": origin}).status_code
                == 403
            )
        assert (
            client.post(
                "/api/printer/jobs", headers={**headers, "X-Station-Token": "wrong"}
            ).status_code
            == 403
        )
        assert (
            client.get("/api/printer/status", headers={"Host": "evil.example"}).status_code == 403
        )


def test_lan_access_requires_opt_in_and_exact_host_origin_and_token(tmp_path):
    config = configuration(tmp_path)
    config.printer = None
    origin = f"http://192.168.100.5:{config.web_port}"
    default_app = create_app(config, tmp_path / "local-jobs")
    with TestClient(default_app, base_url=origin) as client:
        assert client.get("/api/printer/status").status_code == 403

    app = create_app(config, tmp_path / "lan-jobs", lan_host="192.168.100.5")
    with TestClient(app, base_url=origin) as client:
        assert client.get("/api/printer/status").status_code == 200
        headers = {"Origin": origin, "X-Station-Token": app.state.station.token}
        # Only reach schema validation; no upload, slicing or physical command.
        assert client.post("/api/printer/jobs", headers=headers).status_code == 422
        for rejected in (
            {"Origin": "http://192.168.100.6:3102"},
            {"Origin": "http://192.168.100.5:3100"},
            {"Origin": "https://evil.example"},
            {"Origin": "null"},
            {"X-Station-Token": "wrong"},
            {"Host": "evil.example", "X-Forwarded-Host": "192.168.100.5:3102"},
        ):
            assert (
                client.post("/api/printer/jobs", headers={**headers, **rejected}).status_code == 403
            )
        assert not app.state.station.journal.all()
    with TestClient(app, base_url=origin, client=("192.168.100.6", 50000)) as direct_client:
        assert (
            direct_client.get(
                "/api/printer/status", headers={"X-Forwarded-For": "127.0.0.1"}
            ).status_code
            == 403
        )


@pytest.mark.parametrize("host", ["10.0.0.5", "172.16.2.3", "192.168.100.5"])
def test_lan_host_accepts_only_explicit_private_ipv4(host):
    assert private_lan_ipv4(host) == host


@pytest.mark.parametrize(
    "host",
    ["127.0.0.1", "0.0.0.0", "8.8.8.8", "169.254.1.2", "172.32.0.1", "::1", "printer.local"],
)
def test_lan_host_rejects_public_unspecified_loopback_and_non_ipv4(host):
    with pytest.raises(ValueError):
        private_lan_ipv4(host)


def test_oversized_upload_reports_measured_dimensions_before_slicing(tmp_path, monkeypatch):
    async def must_not_slice(*args, **kwargs):
        pytest.fail("An oversized model must not reach Orca.")

    monkeypatch.setattr("services.bridge.print_station.OrcaSlicer.slice", must_not_slice)
    config = configuration(tmp_path)
    config.printer = None
    source = SOURCE.replace(b"vertex 1 0 1", b"vertex 300 0 1")
    chosen = options().model_copy(
        update={"size": len(source), "source_sha256": sha256(source).hexdigest()}
    )
    app = create_app(config, tmp_path / "jobs")
    with TestClient(app, base_url="http://127.0.0.1:8123") as client:
        response = client.post(
            "/api/printer/jobs",
            content=source,
            headers={
                "Origin": "http://127.0.0.1:3102",
                "X-Station-Token": app.state.station.token,
                "X-Print-Options": chosen.model_dump_json(),
            },
        )
        assert response.status_code == 202

        async def wait_done():
            for _ in range(100):
                job = app.state.station.journal.get(response.json()["id"])
                if job["phase"] == "failed":
                    return job
                await asyncio.sleep(0.02)
            raise AssertionError("Validation timed out")

        job = client.portal.call(wait_done)
        assert job["failure_code"] == "model_outside_build_volume"
        assert job["dimensions_um"] == [300000, 1000, 1000]
        assert "300.00 \u00d7 1.00 \u00d7 1.00 mm" in job["message"]
        assert "220 \u00d7 220 \u00d7 220 mm" in job["message"]
        assert "Export individual parts" in job["message"]
        assert not job.get("start_intent")


@pytest.mark.parametrize(
    ("filament_mg", "seconds", "material", "machine", "total"),
    [(30850, 5253, 9255, 1460, 10715), (1500, 1800, 450, 500, 950), (1, 1, 1, 1, 2)],
)
def test_estimate_uses_measured_metrics_and_prorated_paise(
    filament_mg, seconds, material, machine, total
):
    rates = StationPricing(material_rate_paise_per_gram=300, machine_rate_paise_per_hour=1000)
    estimate = estimate_slice(rates, filament_mg, seconds)
    assert estimate["material_paise"] == material
    assert estimate["machine_paise"] == machine
    assert estimate["total_paise"] == total
    assert estimate["rates"] == rates.model_dump()
    assert estimate["filament_mg"] == filament_mg
    assert estimate["duration_seconds"] == seconds
    assert estimate_slice(None, filament_mg, seconds) is None


def test_rates_price_unpriced_jobs_and_preserve_previous_estimates(tmp_path, monkeypatch):
    import fcntl

    from tools import run_print_station as launcher

    monkeypatch.setattr(launcher, "DIRECTORY", tmp_path)
    monkeypatch.setattr(launcher, "CONFIG", tmp_path / "configuration.json")
    config = configuration(tmp_path)
    config.printer = None
    launcher.write_config(config)
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    journal = Journal(jobs / "jobs.sqlite3")
    job, _ = journal.create(options())
    journal.update(
        job["id"],
        phase="sliced",
        package_sha256="a" * 64,
        filament_mg=30850,
        duration_seconds=5253,
    )

    def set_rates(filament, hourly):
        monkeypatch.setattr(
            "sys.argv",
            [
                "run_print_station.py",
                "--directory",
                str(tmp_path),
                "rates",
                "--filament-per-gram",
                filament,
                "--printing-per-hour",
                hourly,
                "--include-existing",
            ],
        )
        launcher.main()

    set_rates("3", "10")
    estimate = journal.get(job["id"])["estimate"]
    assert estimate["total_paise"] == 10715
    set_rates("5", "20")
    assert journal.get(job["id"])["estimate"] == estimate
    assert launcher.read_config().pricing.material_rate_paise_per_gram == 500
    with (tmp_path / "station.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            set_rates("0", "0")
    assert launcher.read_config().pricing.material_rate_paise_per_gram == 500
    assert journal.get(job["id"])["estimate"] == estimate


@pytest.mark.parametrize("invalid", ["-1", "nan", "inf", "0.001", "10000001"])
def test_rate_cli_rejects_invalid_money(invalid):
    import argparse

    from tools.run_print_station import rupees_to_paise

    with pytest.raises(argparse.ArgumentTypeError):
        rupees_to_paise(invalid)
    assert rupees_to_paise("3") == 300
    assert rupees_to_paise("10.50") == 1050


def test_client_cannot_supply_price_or_rates():
    from pydantic import ValidationError

    for field, value in (("pricing", {"material_rate_paise_per_gram": 0}), ("estimate", 0)):
        with pytest.raises(ValidationError):
            PrintOptions.model_validate({**options().model_dump(), field: value})


def test_zmod_metadata_checksum_and_multitool_rejection(tmp_path):
    source = tmp_path / "raw.gcode"
    original = b"; filament_colour = #FF0000\n; filament_type = PLA\nT0\n"
    source.write_bytes(original)
    output = tmp_path / "zmod.gcode"
    digest = prepare_zmod_gcode(source, output, material="PLA")
    header, body = output.read_bytes().split(b"\r\n", 1)
    assert header == b"; MD5:" + md5(body, usedforsecurity=False).hexdigest().encode()
    assert b"; zmod_color_data = 0|#ff0000|pla\r\n" in body
    assert sha256(output.read_bytes()).hexdigest() == digest
    assert source.read_bytes() == original
    source.write_bytes(original + b"T1\n")
    with pytest.raises(PrinterError, match="one material"):
        prepare_zmod_gcode(source, tmp_path / "not-written.gcode", material="PLA")


def test_private_configuration_preserves_credentials_and_cannot_change_while_running(
    tmp_path, monkeypatch
):
    import fcntl

    from tools import run_print_station as launcher

    monkeypatch.setattr(launcher, "DIRECTORY", tmp_path)
    monkeypatch.setattr(launcher, "CONFIG", tmp_path / "configuration.json")
    config = configuration(tmp_path)
    launcher.write_config(config)
    assert launcher.read_config().printer.check_code.get_secret_value() == "simulation"
    assert launcher.CONFIG.stat().st_mode & 0o077 == 0
    original = launcher.CONFIG.read_bytes()
    with (tmp_path / "station.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            launcher.write_config(config)
    assert launcher.CONFIG.read_bytes() == original


@pytest.mark.skipif(
    not os.environ.get("PRINTFLOW_REAL_ORCA_CONFIG"),
    reason="Opt-in real Orca acceptance; physical printer remains simulated.",
)
def test_real_orca_to_simulated_zmod_end_to_end(tmp_path):
    """Real upload/validator/Orca/G-code → loopback Moonraker. NEVER real hardware."""
    config = StationConfig.model_validate_json(
        Path(os.environ["PRINTFLOW_REAL_ORCA_CONFIG"]).read_bytes()
    )
    config.web_port = 3102
    # These approvals exist only in this disposable simulator instance, not on disk.
    config.profiles["PLA"] = config.profiles["PLA"].model_copy(
        update={"approved_for_printer": True}
    )
    config.printer = Connection(
        host="127.0.0.1",
        transport="moonraker",
        zmod_start_reviewed=True,
        mappings={"PLA:red": Mapping(slot=1, colour_hex="#FF0000")},
    )
    source = Path(os.environ["PRINTFLOW_REAL_ORCA_STL"]).read_bytes()
    chosen = PrintOptions(
        client_token=uuid4(),
        filename="local-verification-cube.stl",
        size=len(source),
        source_sha256=sha256(source).hexdigest(),
        material="PLA",
        colour="red",
        layer_height="0.1",
        quantity=2,
        print_now=False,
    )
    with simulated_printer(moonraker=True) as (port, events, _):
        driver = MoonrakerLan("127.0.0.1", port=port, allow_loopback_test=True)
        app = create_app(config, tmp_path / "jobs", enable_printer=True, driver=driver)
        with TestClient(app, base_url="http://127.0.0.1:8123") as client:
            headers = {
                "Origin": "http://127.0.0.1:3102",
                "X-Station-Token": app.state.station.token,
                "X-Print-Options": chosen.model_dump_json(),
            }
            response = client.post("/api/printer/jobs", content=source, headers=headers)
            assert response.status_code == 202
            job_id = response.json()["id"]

            async def wait_done(phases):
                for _ in range(600):
                    job = app.state.station.journal.get(job_id)
                    if job["phase"] in phases:
                        return job
                    await asyncio.sleep(0.1)
                raise AssertionError("Real Orca acceptance timed out")

            quoted = client.portal.call(wait_done, {"sliced", "failed"})
            assert quoted["phase"] == "sliced", quoted["message"]
            assert quoted["estimate"]["total_paise"] > 0
            assert not any(event[0] == "/server/files/upload" for event in events)
            response = client.post(
                f"/api/printer/jobs/{job_id}/start",
                headers=headers,
                json={
                    "client_token": str(uuid4()),
                    "expected_total_paise": quoted["estimate"]["total_paise"],
                    "readiness_confirmed": True,
                },
            )
            assert response.status_code == 202, response.text
            job = client.portal.call(wait_done, {"awaiting_start", "failed", "needs_attention"})
            assert job["phase"] == "awaiting_start", job["message"]
            assert job["gcode_sha256"] == quoted["gcode_sha256"]
            assert job["package_sha256"] == quoted["package_sha256"]
            assert job["estimate"] == quoted["estimate"]
            uploads = [event for event in events if event[0] == "/server/files/upload"]
            assert len(uploads) == 1
            assert b"; layer_height = 0.1" in uploads[0][2]
            assert b"; filament_colour = #FF0000" in uploads[0][2]
            assert b"; MD5:" in uploads[0][2]
            assert b"; zmod_color_data = 0|#ff0000|pla" in uploads[0][2]
            assert job["filament_mg"] > 0 and job["duration_seconds"] > 0
            assert client.get(f"/api/printer/jobs/{job_id}/gcode").status_code == 200
            print(
                f"Real Orca → simulated ZMOD: {job['filament_mg']} mg, "
                f"{job['duration_seconds']} s, one G-code upload, zero physical commands."
            )
