"""Outbound commerce adapter around the commissioned, unchanged local station.

It imports one already-approved plate, never slices or retries a physical start.
The native journal and monitor remain the authority for local physical attempts.
"""

import asyncio
import json
import logging
import os
import re
import sqlite3
import time
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Literal
from urllib.error import HTTPError
from uuid import UUID, uuid4

from pydantic import Field, SecretStr

from services.bridge.bridge import ManualBridge
from services.bridge.moonraker_lan import MoonrakerLan
from services.bridge.print_station import ACTIVE, PrintOptions, Station, StrictModel
from services.bridge.zmod_gcode import prepare_zmod_gcode

LOG = logging.getLogger(__name__)


class ApprovedProfile(StrictModel):
    profile_sha256: str = Field(alias="profileSha256", pattern=r"^[0-9a-f]{64}$")
    material: Literal["PLA", "PETG"]
    station_bed_type: str = Field(alias="stationBedType")


class ConnectorConfig(StrictModel):
    api_origin: str
    credential: SecretStr
    approved_profiles: list[ApprovedProfile] = Field(default_factory=list)


def read_config(path: Path) -> ConnectorConfig:
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
        raise ValueError("Use a private regular connector file (mode 600).")
    config = ConnectorConfig.model_validate_json(path.read_bytes())
    ManualBridge(
        config.api_origin
    )  # Validate HTTPS / loopback and credential destination.
    return config


def save_config(path: Path, config: ConnectorConfig) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".new")
    data = config.model_dump(mode="json", by_alias=True)
    data["credential"] = config.credential.get_secret_value()
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write(json.dumps(data, indent=2))
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


class CommerceConnector:
    def __init__(self, station: Station, config: ConnectorConfig, *, api=None):
        self.station = station
        self.config = config
        self.api = api or ManualBridge(
            config.api_origin, config.credential.get_secret_value()
        )

    async def request(self, path, body=None, *, binary=False):
        return await asyncio.to_thread(self.api.request, path, body, binary=binary)

    def imported(self):
        return [
            row for row in self.station.journal.all() if row.get("kind") == "commerce"
        ]

    def queue_event(self, job_id, state, *, refusal=None):
        row = self.station.journal.get(job_id)
        bucket = min(10, max(0, int(row.get("progress", 0) * 10)))
        key = f"commerce:{row['authorization_id']}:{state}"
        if state == "printing":
            previous = [
                int(value.rsplit(":", 1)[1])
                for value in row.get("event_keys", [])
                if ":printing:" in value
            ]
            if previous and bucket <= max(previous):
                return
            key += f":{bucket}"
        if key in row.get("event_keys", []):
            return
        event = {
            "sourceEventId": key,
            "state": state,
            "observedAt": datetime.now(UTC).isoformat(),
            "printerFilename": row.get("printer_filename"),
            "dispatchSha256": row.get("dispatch_sha256"),
            "progressBps": bucket * 1000 if state == "printing" else None,
            "refusalCode": refusal,
        }
        self.station.journal.update(
            job_id,
            outbox=[*row.get("outbox", []), event],
            event_keys=[*row.get("event_keys", []), key],
        )

    async def flush(self, job_id):
        while True:
            row = self.station.journal.get(job_id)
            if not row.get("outbox") or row.get("telemetry_error"):
                return not row.get("telemetry_error")
            try:
                await self.request(
                    f"/api/v1/bridge/dispatches/{row['authorization_id']}/events",
                    row["outbox"][0],
                )
            except HTTPError as error:
                if error.code in {409, 422, 401, 404}:
                    self.station.journal.update(
                        job_id,
                        telemetry_error=f"Station event rejected ({error.code}); owner review required.",
                        message=f"Order update rejected ({error.code}). Inspect the order and printer; no resend.",
                    )
                return False
            except (OSError, ValueError):
                return False
            # The original exact event remains durable until the API acknowledgement.
            fresh = self.station.journal.get(job_id)
            self.station.journal.update(job_id, outbox=fresh["outbox"][1:])

    def reserve(self, authorization_id, commerce_job_id):
        identifier = str(UUID(authorization_id))
        with self.station.journal.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT data FROM jobs WHERE token=?", (identifier,)
            ).fetchone()
            if existing:
                return json.loads(existing[0]), False
            row = {
                "id": uuid4().hex,
                "kind": "commerce",
                "authorization_id": identifier,
                "commerce_job_id": str(UUID(commerce_job_id)),
                "phase": "validating",
                "options": {
                    "filename": "Owner-approved order.gcode",
                    "material": "PLA",
                    "colour": "red",
                    "quantity": 1,
                    "kind": "commerce",
                },
                "created": time.time(),
                "updated": time.time(),
                "message": "Importing approved order.",
                "progress": 0,
                "outbox": [],
                "event_keys": [],
            }
            db.execute(
                "INSERT INTO jobs VALUES(?,?,?,?,?)",
                (row["id"], identifier, identifier, row["phase"], json.dumps(row)),
            )
            return row, True

    def verify(self, claim, raw):
        specification = claim["specification"]
        material = specification["materialCode"].upper()
        colour = specification["colour"]
        config = self.station.config
        if material not in {"PLA", "PETG"} or not self.station.enabled:
            raise ValueError("unsupported_material_or_disabled")
        if not config.printer or not config.printer.zmod_start_reviewed:
            raise ValueError("zmod_not_reviewed")
        if not isinstance(self.station.driver, MoonrakerLan):
            raise ValueError("moonraker_required")
        approved = next(
            (
                entry
                for entry in self.config.approved_profiles
                if entry.profile_sha256 == specification["profileSha256"]
                and entry.material == material
            ),
            None,
        )
        if not approved or config.bed_type != approved.station_bed_type:
            raise ValueError("profile_or_plate_not_approved")
        options = PrintOptions(
            client_token=uuid4(),
            filename="approved.stl",
            size=1,
            source_sha256="0" * 64,
            material=material,
            colour=colour,
            print_now=True,
            readiness_confirmed=True,
        )
        self.station.validate_options(options)
        mapping = self.station.mapping(options)
        if sha256(raw).hexdigest() != claim["artifactSha256"]:
            raise ValueError("artifact_hash_mismatch")
        text = raw.decode("utf-8")
        for field, expected in (
            ("curr_bed_type", config.bed_type),
            ("filament_type", material),
            ("filament_colour", mapping.colour_hex),
        ):
            values = re.findall(rf"^; {field} = ([^\r\n]+)\r?$", text, re.MULTILINE)
            if (
                len(values) != 1
                or values[0].strip().casefold() != str(expected).casefold()
            ):
                raise ValueError("gcode_metadata_mismatch")
        return options, mapping

    async def dispatch(self, row):
        job_id = row["id"]
        current = self.station.journal.get(job_id)
        if current.get("start_intent") or current["phase"] != "validating":
            return  # Only a newly reserved row may ever reach the physical boundary.
        prefix = f"/api/v1/bridge/dispatches/{row['authorization_id']}"
        try:
            claim = await self.request(prefix + "/claim", {})
            if (
                claim["jobId"] != row["commerce_job_id"]
                or claim["downloadUrl"] != prefix + "/artifact"
            ):
                raise ValueError("claim_binding_mismatch")
            self.station.journal.update(job_id, claim=claim)
            raw = await self.request(prefix + "/artifact", binary=True)
            options, mapping = self.verify(claim, raw)
            settings = claim["specification"].get("settings", {})
            self.station.journal.update(
                job_id,
                options={
                    **row["options"],
                    "material": options.material,
                    "colour": options.colour,
                    "client_token": row["authorization_id"],
                    "layer_height": settings.get("layerHeightMm", "—"),
                    "infill": settings.get("infillPercent", "—"),
                },
            )
            scratch = self.station.directory / job_id
            scratch.mkdir(mode=0o700, exist_ok=False)
            source = scratch / "approved.gcode"
            with source.open("xb") as stream:
                stream.write(raw)
            destination = scratch / "zmod.gcode"
            wire_hash = await asyncio.to_thread(
                prepare_zmod_gcode, source, destination, material=options.material
            )
            driver = self.station.driver
            assert driver is not None
            status = await asyncio.to_thread(driver.status)
            slot = driver.require_ready(
                status,
                slot=mapping.slot,
                material=options.material,
                colour_hex=mapping.colour_hex,
            )
            filename = f"pf_{job_id}_{claim['artifactSha256'][:12]}.gcode"
            # Physical boundary. A durable intent is never retried, including on restart.
            self.station.journal.update(
                job_id,
                phase="starting",
                start_intent=time.time(),
                printer_filename=filename,
                dispatch_sha256=wire_hash,
                message="Sending the approved order once. Do not resubmit.",
            )
            self.queue_event(job_id, "sent")
            if not await self.flush(job_id):
                raise ValueError("sent_acknowledgement_uncertain")
            await asyncio.to_thread(
                driver.upload_and_print, destination, filename=filename, slot=slot
            )
            self.station.journal.update(
                job_id,
                phase="awaiting_start",
                message="Upload accepted. Waiting for this exact filename.",
            )
            self.queue_event(job_id, "awaiting_start")
        except Exception as error:
            # No exception text: requests/configuration can contain private credentials.
            current = self.station.journal.get(job_id)
            physical = bool(current.get("start_intent"))
            refusal = str(error) if isinstance(error, ValueError) else "station_refused"
            if not re.fullmatch(r"[a-z_]{1,48}", refusal):
                refusal = "station_refused"
            self.station.journal.update(
                job_id,
                phase="needs_attention" if physical else "failed",
                message="Inspect this attempt. No resend will be made."
                if physical
                else "No printer command sent. Owner must review readiness and configuration.",
            )
            self.queue_event(
                job_id, "needs_attention" if physical else "refused", refusal=refusal
            )
        await self.flush(job_id)

    async def tick(self):
        await self.request("/api/v1/bridge/heartbeat", {})
        for row in self.imported():
            phase = row["phase"]
            if row.get("start_intent") and phase in {
                "awaiting_start",
                "printing",
                "needs_attention",
                "completed",
                "cancelled",
                "stopped",
                "resolved",
            }:
                self.queue_event(row["id"], phase)
            elif phase == "failed" and not row.get("event_keys"):
                # Recovery before intent: consume/recover the claim only to refuse it, never send.
                try:
                    await self.request(
                        f"/api/v1/bridge/dispatches/{row['authorization_id']}/claim", {}
                    )
                    self.queue_event(
                        row["id"], "refused", refusal="station_restarted_before_send"
                    )
                except (OSError, ValueError):
                    pass
            await self.flush(row["id"])
        if any(row["phase"] in ACTIVE for row in self.station.journal.all()):
            return
        grants = await self.request("/api/v1/bridge/dispatches")
        for grant in grants["items"]:
            try:
                row, created = self.reserve(grant["id"], grant["jobId"])
            except sqlite3.IntegrityError:
                return
            if created:
                await self.dispatch(row)
                return

    async def run(self):
        while True:
            try:
                await self.tick()
            except (OSError, ValueError, KeyError, TypeError):
                LOG.warning("Commerce connection unavailable; no automatic resend.")
            await asyncio.sleep(5)
