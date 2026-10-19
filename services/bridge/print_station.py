"""One local operator, one AD5X, no accounts/commerce/database server.

Run using tools/run_print_station.py. This application deliberately accepts only
loopback UI requests. Physical starts require local configuration and a fresh
per-job readiness confirmation. A persisted start intent is NEVER resent.
"""

import asyncio
import hmac
import json
import secrets
import sqlite3
import time
from contextlib import asynccontextmanager
from dataclasses import asdict
from hashlib import file_digest, sha256
from pathlib import Path
from typing import Literal, cast
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictBool, StrictInt
from xxx_api.config import Settings
from xxx_api.print_presets import PROFILE_FILES, profile_settings, read_profile_bundle
from xxx_api.schemas.model_options import ModelOptions
from xxx_worker.model_transform import prepare_transformed_model
from xxx_worker.sandbox import SandboxValidator
from xxx_worker.slicing import OrcaSlicer
from xxx_worker.validation import ModelFormat, ModelValidationError

from services.bridge.ad5x_lan import AD5XLan, PrinterError, PrinterStatus
from services.bridge.moonraker_lan import MoonrakerLan
from services.bridge.zmod_gcode import prepare_zmod_gcode

STOCK: dict[Literal["PLA", "PETG"], list[str]] = {
    "PLA": ["red", "white", "black"],
    "PETG": ["black", "orange"],
}
PREVIEW_COLOURS = {"red": "#FF0000", "white": "#FFFFFF", "black": "#000000", "orange": "#FF8000"}
ACTIVE = (
    "uploading",
    "validating",
    "slicing",
    "starting",
    "awaiting_start",
    "printing",
    "needs_attention",
)
MAX_BYTES = 100 * 1024 * 1024


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Profile(StrictModel):
    directory: Path
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved_for_printer: StrictBool = False


class Mapping(StrictModel):
    slot: StrictInt = Field(ge=1, le=4)
    colour_hex: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")


class Connection(StrictModel):
    transport: Literal["flashforge", "moonraker"] = "moonraker"
    host: str
    serial: SecretStr = SecretStr("")
    check_code: SecretStr = SecretStr("")
    api_key: SecretStr = SecretStr("")
    zmod_start_reviewed: StrictBool = False
    mappings: dict[str, Mapping] = Field(default_factory=dict)


class StationConfig(StrictModel):
    slicer: Path
    slicer_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    slicer_version: str = Field(min_length=1, max_length=64)
    profiles: dict[Literal["PLA", "PETG"], Profile]
    bed_type: Literal["Textured PEI Plate", "High Temp Plate", "Cool Plate"] | None = None
    printer: Connection | None = None


class PrintOptions(StrictModel):
    client_token: UUID
    filename: str = Field(
        min_length=1, max_length=160, pattern=r"^[^/\\\x00-\x1f\x7f]+\.(?i:stl|obj)$"
    )
    size: StrictInt = Field(gt=0, le=MAX_BYTES)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    material: Literal["PLA", "PETG"]
    colour: str
    layer_height: Literal["0.1", "0.15", "0.2"] = "0.2"
    infill: Literal[10, 15, 20, 30, 40, 50, 60, 70, 80, 90] = 20
    quantity: StrictInt = Field(default=1, ge=1, le=10)
    supports: StrictBool = False
    model: ModelOptions = Field(default_factory=ModelOptions)
    print_now: StrictBool = False
    readiness_confirmed: StrictBool = False


class Journal:
    def __init__(self, path: Path):
        self.path = path
        with self.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, token TEXT UNIQUE NOT NULL, "
                "fingerprint TEXT NOT NULL, phase TEXT NOT NULL, data TEXT NOT NULL)"
            )
            # An unresolved physical start blocks another print, including after a restart.
            active = ",".join(f"'{phase}'" for phase in ACTIVE)
            db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS one_active ON jobs((1)) "
                f"WHERE phase IN ({active})"
            )
        path.chmod(0o600)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA synchronous=FULL")
        return db

    def all(self):
        with self.connect() as db:
            return [
                json.loads(row[0])
                for row in db.execute("SELECT data FROM jobs ORDER BY rowid DESC LIMIT 100")
            ]

    def get(self, job_id: str):
        with self.connect() as db:
            row = db.execute("SELECT data FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Job not found.")
        return json.loads(row[0])

    def create(self, options: PrintOptions):
        payload = options.model_dump(mode="json")
        fingerprint = sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT fingerprint, data FROM jobs WHERE token=?",
                (str(options.client_token),),
            ).fetchone()
            if row:
                if row[0] != fingerprint:
                    raise HTTPException(
                        409,
                        "This submission token was already used with different settings.",
                    )
                return json.loads(row[1]), False
            job = {
                "id": uuid4().hex,
                "phase": "uploading",
                "options": payload,
                "created": time.time(),
                "updated": time.time(),
                "message": "Receiving model.",
                "progress": 0,
            }
            try:
                db.execute(
                    "INSERT INTO jobs VALUES(?,?,?,?,?)",
                    (
                        job["id"],
                        str(options.client_token),
                        fingerprint,
                        job["phase"],
                        json.dumps(job),
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise HTTPException(
                    409, "Finish or resolve the current job before submitting another."
                ) from error
        return job, True

    def update(self, job_id: str, **changes):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT data FROM jobs WHERE id=?", (job_id,)).fetchone()
            job = json.loads(row[0])
            job.update(changes, updated=time.time())
            db.execute(
                "UPDATE jobs SET phase=?,data=? WHERE id=?",
                (job["phase"], json.dumps(job), job_id),
            )
        return job

    def recover(self):
        for job in self.all():
            if job["phase"] in ACTIVE:
                physical = bool(job.get("start_intent"))
                self.update(
                    job["id"],
                    phase="needs_attention" if physical else "failed",
                    message="Station restarted after sending began. Inspect the printer; no resend."
                    if physical
                    else "Station stopped before sending this job. Submit again when ready.",
                )


class Station:
    def __init__(
        self,
        config: StationConfig,
        directory: Path,
        *,
        enable_printer: bool = False,
        driver: AD5XLan | MoonrakerLan | None = None,
    ):
        self.config, self.directory, self.enabled = config, directory, enable_printer
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory.chmod(0o700)
        self.journal = Journal(directory / "jobs.sqlite3")
        self.journal.recover()
        self.token = secrets.token_urlsafe(32)
        self.submit_lock = asyncio.Lock()
        self.tasks: set[asyncio.Task] = set()
        self.driver = driver
        if config.printer and driver is None:
            printer = config.printer
            self.driver = (
                MoonrakerLan(printer.host, printer.api_key.get_secret_value())
                if printer.transport == "moonraker"
                else AD5XLan(
                    printer.host,
                    printer.serial.get_secret_value(),
                    printer.check_code.get_secret_value(),
                )
            )
        if enable_printer and self.driver is None:
            raise ValueError("Configure the AD5X locally before enabling physical starts.")

    def profile(self, material: Literal["PLA", "PETG"]):
        profile = self.config.profiles.get(material)
        if profile is None or not profile.directory.is_absolute():
            raise HTTPException(422, "No reviewed base profile is configured for this material.")
        files = read_profile_bundle(profile.directory, profile.sha256)
        settings = profile_settings(files)
        machine = json.loads(files["machine.json"])
        if (
            str(settings["filamentType"]).upper() != material
            or settings["nozzleDiameterMm"] != "0.4"
            or "AD5X" not in str(machine.get("name", "")).upper()
        ):
            raise HTTPException(422, "Use matching AD5X / 0.4 mm / material profiles.")
        return profile, files

    def validate_options(self, options: PrintOptions):
        if self.config.bed_type is None:
            raise HTTPException(422, "Configure the print station's build-plate type first.")
        if options.colour not in STOCK[options.material]:
            raise HTTPException(422, "Choose one of the confirmed filament colours.")
        profile, _ = self.profile(options.material)
        if options.print_now:
            if not self.enabled or not profile.approved_for_printer:
                raise HTTPException(
                    409,
                    "Printer starts are disabled or this material profile is not printer-approved.",
                )
            if not options.readiness_confirmed:
                raise HTTPException(
                    422,
                    "Confirm a clear bed, correct nozzle/filament and supervision for this job.",
                )
            if (
                self.config.printer
                and self.config.printer.transport == "moonraker"
                and not self.config.printer.zmod_start_reviewed
            ):
                raise HTTPException(
                    409,
                    "Review ZMOD colour matching, silent start and a known-working profile first.",
                )
            self.mapping(options)

    def mapping(self, options: PrintOptions):
        printer = self.config.printer
        mapping = printer.mappings.get(f"{options.material}:{options.colour}") if printer else None
        if mapping is None:
            raise PrinterError(
                "No commissioned IFS slot mapping exists for this material and colour."
            )
        return mapping

    def spawn(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def process(self, job_id: str):
        job = self.journal.get(job_id)
        options = PrintOptions.model_validate(job["options"])
        scratch = self.directory / job_id
        try:
            self.journal.update(
                job_id,
                phase="validating",
                message="Validating model geometry and dimensions.",
            )
            kind = cast(ModelFormat, options.filename.rsplit(".", 1)[1].lower())
            source = scratch / ("source." + kind)
            validator = SandboxValidator("xxx-analyzer", 60)
            result = await validator.validate(
                source,
                declared_format=kind,
                expected_size=options.size,
                claimed_sha256=options.source_sha256,
                scratch_directory=scratch,
            )
            if not options.model.is_identity:
                prepared = scratch / ("configured." + kind)
                await asyncio.to_thread(
                    prepare_transformed_model,
                    source,
                    prepared,
                    model_format=kind,
                    triangle_count=result.triangle_count,
                    options=options.model,
                )
                source = prepared
                with source.open("rb") as stream:
                    transformed_hash = file_digest(stream, "sha256").hexdigest()
                result = await validator.validate(
                    source,
                    declared_format=kind,
                    expected_size=source.stat().st_size,
                    claimed_sha256=transformed_hash,
                    scratch_directory=scratch,
                )
            if (
                result.fits_build_volume is not True
                or not result.dimensions_um
                or any(v <= 0 for v in result.dimensions_um)
            ):
                raise ModelValidationError("model_outside_build_volume")
            _, files = self.profile(options.material)
            process = json.loads(files["process.json"])
            # Only the explicit UI settings may override the hash-pinned base profiles.
            process.update(
                layer_height=options.layer_height,
                sparse_infill_density=f"{options.infill}%",
                enable_support="1" if options.supports else "0",
                curr_bed_type=self.config.bed_type,
            )
            files["process.json"] = json.dumps(process, sort_keys=True).encode()
            filament = json.loads(files["filament.json"])
            configured_mapping = (
                config_printer.mappings.get(f"{options.material}:{options.colour}")
                if (config_printer := self.config.printer)
                else None
            )
            filament["filament_colour"] = [
                configured_mapping.colour_hex
                if configured_mapping
                else PREVIEW_COLOURS[options.colour]
            ]
            files["filament.json"] = json.dumps(filament, sort_keys=True).encode()
            profiles = scratch / "profiles"
            profiles.mkdir(mode=0o700)
            digest = sha256()
            for name in PROFILE_FILES:
                (profiles / name).write_bytes(files[name])
                digest.update(name.encode() + b"\0" + files[name])
            profile_hash = digest.hexdigest()
            config = self.config
            settings = Settings(
                _env_file=None,  # type: ignore[call-arg]
                analysis_slicer_command=config.slicer,
                analysis_slicer_version=config.slicer_version,
                analysis_slicer_sha256=config.slicer_sha256,
                analysis_profile_directory=profiles,
                analysis_profile_sha256=profile_hash,
                analysis_material_code=options.material.lower(),
                max_models_per_quote=1,
                analysis_lease_seconds=3600,
            )
            self.journal.update(
                job_id,
                phase="slicing",
                message="Slicing locally with OrcaSlicer.",
                dimensions_mm=[v / 1000 for v in result.dimensions_um],
                profile_sha256=profile_hash,
                configured_source_sha256=result.verified_sha256,
            )
            sliced = await OrcaSlicer(settings).slice(source, scratch, quantity=options.quantity)
            print_artifact = sliced.artifact
            dispatch_hash = sliced.artifact_sha256
            if not config.printer or config.printer.transport == "moonraker":
                print_artifact = scratch / "zmod.gcode"
                dispatch_hash = await asyncio.to_thread(
                    prepare_zmod_gcode, sliced.artifact, print_artifact, material=options.material
                )
            package = scratch / "result.3mf"
            with package.open("rb") as stream:
                package_hash = file_digest(stream, "sha256").hexdigest()
            self.journal.update(
                job_id,
                package_sha256=package_hash,
                gcode_sha256=dispatch_hash,
                gcode_name=print_artifact.name,
                filament_mg=sliced.filament_mg,
                duration_seconds=sliced.duration_seconds,
            )
            if not options.print_now:
                self.journal.update(
                    job_id,
                    phase="sliced",
                    message="Slicing complete. No printer command was sent.",
                )
                return
            self.validate_options(options)
            if time.time() - job["created"] > 600:
                raise PrinterError(
                    "Readiness confirmation expired during processing. No print was sent."
                )
            assert self.driver is not None
            mapping = self.mapping(options)
            status = await asyncio.to_thread(self.driver.status)
            slot = self.driver.require_ready(
                status,
                slot=mapping.slot,
                material=options.material,
                colour_hex=mapping.colour_hex,
            )
            # All prerequisites above precede the durable intent. Never retry below this line.
            moonraker = isinstance(self.driver, MoonrakerLan)
            suffix = "gcode" if moonraker else "3mf"
            printer_filename = f"pf_{job_id}_{package_hash[:12]}.{suffix}"
            self.journal.update(
                job_id,
                phase="starting",
                start_intent=time.time(),
                printer_filename=printer_filename,
                message="Sending this job once to the AD5X. Do not resubmit.",
            )
            await asyncio.to_thread(
                self.driver.upload_and_print,
                print_artifact if moonraker else package,
                filename=printer_filename,
                slot=slot,
            )
            self.journal.update(
                job_id,
                phase="awaiting_start",
                message="Printer accepted the upload; waiting for matching live print status.",
            )
        except asyncio.CancelledError:
            physical = bool(self.journal.get(job_id).get("start_intent"))
            self.journal.update(
                job_id,
                phase="needs_attention" if physical else "failed",
                message="Station stopped. Inspect the printer before sending another job."
                if physical
                else "Processing stopped before sending to the printer.",
            )
            raise
        except Exception as error:
            physical = bool(self.journal.get(job_id).get("start_intent"))
            message = (
                error.code
                if isinstance(error, ModelValidationError)
                else str(error)
                if isinstance(error, (PrinterError, HTTPException))
                else "Local processing failed. Check the configured profiles and station log."
            )
            self.journal.update(
                job_id,
                phase="needs_attention" if physical else "failed",
                message=message,
            )

    def reconcile(self, status: PrinterStatus):
        for job in self.journal.all():
            if job["phase"] not in {
                "awaiting_start",
                "printing",
                "needs_attention",
            } or not job.get("start_intent"):
                continue
            if status.error:
                self.journal.update(
                    job["id"],
                    phase="needs_attention",
                    message="Printer reports an error. Inspect its screen; no retry will be sent.",
                )
            elif status.filename == job.get("printer_filename"):
                if status.state in {"heating", "printing"}:
                    self.journal.update(
                        job["id"],
                        phase="printing",
                        progress=status.progress,
                        message="AD5X reports this exact job is " + status.state + ".",
                    )
                elif status.state == "completed":
                    self.journal.update(
                        job["id"],
                        phase="completed",
                        progress=1,
                        message="Job completed per AD5X. Remove the print before the next job.",
                    )
                elif status.state in {
                    "cancel",
                    "cancelled",
                    "error",
                    "pause",
                    "paused",
                }:
                    self.journal.update(
                        job["id"],
                        phase="needs_attention",
                        message="Job is paused, cancelled or in error. Inspect the printer.",
                    )
            elif time.time() - job["start_intent"] > 90:
                self.journal.update(
                    job["id"],
                    phase="needs_attention",
                    message="Printer has not confirmed this exact job. Inspect it; no retry sent.",
                )

    async def monitor(self):
        while True:
            if self.driver:
                try:
                    self.reconcile(await asyncio.to_thread(self.driver.status))
                except PrinterError:
                    for job in self.journal.all():
                        if job["phase"] in {"awaiting_start", "printing"}:
                            self.journal.update(
                                job["id"],
                                phase="needs_attention",
                                message="Printer disconnected. Inspect it; no resend.",
                            )
            await asyncio.sleep(3)


def create_app(config: StationConfig, directory: Path, *, enable_printer=False, driver=None):
    station = Station(config, directory, enable_printer=enable_printer, driver=driver)

    @asynccontextmanager
    async def lifespan(app):
        monitor = asyncio.create_task(station.monitor())
        yield
        monitor.cancel()
        for task in tuple(station.tasks):
            task.cancel()
        await asyncio.gather(monitor, *tuple(station.tasks), return_exceptions=True)

    app = FastAPI(
        title="Local AD5X Print Station",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.station = station

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        # Check both before reading a body. No CORS, public binding or printer URLs from HTTP.
        if (
            request.client is None
            or request.client.host not in {"127.0.0.1", "::1", "testclient"}
            or request.headers.get("host") not in {"127.0.0.1:8123", "127.0.0.1:3102"}
        ):
            return JSONResponse({"detail": "Local print station only."}, status_code=403)
        if request.method not in {"GET", "HEAD"} and (
            request.headers.get("origin") != "http://127.0.0.1:3102"
            or not hmac.compare_digest(request.headers.get("x-station-token", ""), station.token)
        ):
            return JSONResponse(
                {"detail": "Open the local print page to submit a job."}, status_code=403
            )
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/api/printer/status")
    async def status():
        printer_status, printer_message = None, "No printer configured. Slicing only."
        if station.driver:
            try:
                current = await asyncio.to_thread(station.driver.status)
                station.reconcile(current)
                printer_status = asdict(current)
                printer_message = "Connected to AD5X."
            except PrinterError as error:
                printer_message = str(error)
        profiles = {}
        for material in STOCK:
            try:
                profile, _ = station.profile(material)
                connection = config.printer
                commissioned = bool(
                    connection
                    and (connection.transport == "flashforge" or connection.zmod_start_reviewed)
                )
                profiles[material] = {
                    "available": True,
                    "approved": profile.approved_for_printer,
                    "printableColours": [
                        colour
                        for colour in STOCK[material]
                        if connection
                        and commissioned
                        and station.enabled
                        and profile.approved_for_printer
                        and f"{material}:{colour}" in connection.mappings
                    ],
                }
            except (ValueError, HTTPException):
                profiles[material] = {"available": False, "approved": False, "printableColours": []}
        return {
            "token": station.token,
            "enabled": station.enabled,
            "bedType": config.bed_type,
            "stock": STOCK,
            "profiles": profiles,
            "printer": printer_status,
            "message": printer_message,
            "jobs": station.journal.all(),
        }

    @app.post("/api/printer/jobs", status_code=202)
    async def submit(request: Request):
        raw = request.headers.get("x-print-options", "")
        if len(raw) > 4096:
            raise HTTPException(422, "Print options are too large.")
        try:
            options = PrintOptions.model_validate_json(raw)
            station.validate_options(options)
        except (ValueError, PrinterError) as error:
            raise HTTPException(422, "Invalid print settings, profile or IFS mapping.") from error
        async with station.submit_lock:
            job, created = station.journal.create(options)
            if not created:
                return job
            scratch = station.directory / job["id"]
            scratch.mkdir(mode=0o700)
            source = scratch / ("source." + options.filename.rsplit(".", 1)[1].lower())
            try:
                digest, size = sha256(), 0
                async with asyncio.timeout(120):
                    with source.open("xb") as output:
                        async for chunk in request.stream():
                            size += len(chunk)
                            if size > options.size or size > MAX_BYTES:
                                raise HTTPException(413, "Upload exceeded its declared size.")
                            digest.update(chunk)
                            output.write(chunk)
                if size != options.size or digest.hexdigest() != options.source_sha256:
                    raise HTTPException(422, "Upload size or integrity check failed.")
            except BaseException:
                station.journal.update(
                    job["id"],
                    phase="failed",
                    message="Upload or integrity check failed. Nothing sent to printer.",
                )
                raise
            station.spawn(station.process(job["id"]))
            return job

    @app.get("/api/printer/jobs/{job_id}/package")
    async def package(job_id: UUID):
        job = station.journal.get(job_id.hex)
        if not job.get("package_sha256"):
            raise HTTPException(409, "No sliced package is available.")
        path = station.directory / job_id.hex / "result.3mf"
        return FileResponse(
            path,
            media_type="application/octet-stream",
            filename=f"print-{job_id.hex[:8]}.3mf",
        )

    @app.get("/api/printer/jobs/{job_id}/gcode")
    async def gcode(job_id: UUID):
        job = station.journal.get(job_id.hex)
        if not job.get("gcode_sha256"):
            raise HTTPException(409, "No sliced G-code is available.")
        name = job.get("gcode_name", "approved.gcode")
        if name not in {"approved.gcode", "zmod.gcode"}:
            raise HTTPException(409, "Unsupported artifact name.")
        path = station.directory / job_id.hex / name
        return FileResponse(
            path, media_type="application/octet-stream", filename=f"print-{job_id.hex[:8]}.gcode"
        )

    @app.post("/api/printer/jobs/{job_id}/resolve")
    async def resolve(job_id: UUID, request: Request):
        if request.headers.get("x-bed-clear-confirmed") != "true":
            raise HTTPException(422, "Inspect the printer and clear the bed before resolving.")
        job = station.journal.get(job_id.hex)
        if job["phase"] != "needs_attention" or not station.driver:
            raise HTTPException(409, "Only an uncertain physical job can be resolved here.")
        current = await asyncio.to_thread(station.driver.status)
        ready_states = (
            {"ready", "completed"} if isinstance(station.driver, MoonrakerLan) else {"ready"}
        )
        if current.state not in ready_states or current.error:
            raise HTTPException(
                409,
                "Printer must report ready and error-free. Resolve at its screen first.",
            )
        return station.journal.update(
            job_id.hex,
            phase="resolved",
            message="Operator inspected printer and cleared bed. Original job was not resent.",
        )

    return app
