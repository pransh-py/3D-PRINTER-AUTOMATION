"""Physical commands target only a loopback HTTP simulator, never a printer.

Station slicing here is a deterministic fixture; genuine Orca is exercised by the
local browser acceptance run, not claimed by these unit/transport tests.
"""

import asyncio
import json
import os
import threading
from contextlib import contextmanager
from hashlib import md5, sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from services.bridge.ad5x_lan import AD5XLan, PrinterError, PrinterStatus
from services.bridge.moonraker_lan import MoonrakerLan
from services.bridge.print_station import (
    Connection,
    Journal,
    Mapping,
    PrintOptions,
    Profile,
    StationConfig,
    create_app,
)
from services.bridge.zmod_gcode import prepare_zmod_gcode
from xxx_worker.slicing import SliceResult


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
                self.reply({"result": {"queue_state": "paused", "queued_jobs": []}})
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
                            "status": {
                                "print_stats": {"state": "standby", "filename": ""},
                                "virtual_sdcard": {"progress": 0, "is_active": False},
                                "idle_timeout": {"state": "Ready"},
                            }
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
        print_now=True,
        readiness_confirmed=True,
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

            async def wait_done():
                for _ in range(600):
                    job = app.state.station.journal.get(job_id)
                    if job["phase"] in {"awaiting_start", "failed", "needs_attention"}:
                        return job
                    await asyncio.sleep(0.1)
                raise AssertionError("Real Orca acceptance timed out")

            job = client.portal.call(wait_done)
            assert job["phase"] == "awaiting_start", job["message"]
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
