"""ZMOD transport using documented Moonraker APIs, with no arbitrary G-code RPC.

The operator must commission ZMOD single-material colour matching and the silent
start settings separately. Moonraker standard status does NOT prove spool colour.
"""

from dataclasses import dataclass, field
from hashlib import file_digest
from http.client import HTTPConnection, HTTPException
from json import dumps, loads
from math import isfinite
from pathlib import Path
from re import fullmatch
from uuid import uuid4

from services.bridge.ad5x_lan import AD5XLan, PrinterError, PrinterStatus, Slot


@dataclass(frozen=True)
class MoonrakerLan:
    host: str
    api_key: str = field(default="", repr=False)
    port: int = 7125
    timeout: float = 20
    allow_loopback_test: bool = False
    native: AD5XLan | None = field(default=None, repr=False)

    def __post_init__(self):
        # Reuse the numeric private-LAN boundary; neither DNS nor redirects are used.
        AD5XLan(
            self.host,
            "validation-only",
            "validation-only",
            port=self.port,
            timeout=self.timeout,
            allow_loopback_test=self.allow_loopback_test,
        )
        if len(self.api_key) > 256 or any(ord(c) < 33 or ord(c) > 126 for c in self.api_key):
            raise ValueError("Enter a valid Moonraker API key locally, if required.")

    @property
    def headers(self):
        return {"X-Api-Key": self.api_key} if self.api_key else {}

    @staticmethod
    def result(connection, expected=200):
        response = connection.getresponse()
        data = response.read(1024 * 1024 + 1)
        if response.status != expected or len(data) > 1024 * 1024:
            raise PrinterError(
                "Moonraker rejected the request. Check its local access configuration."
            )
        try:
            result = loads(data)
        except (ValueError, UnicodeError) as error:
            raise PrinterError("Invalid Moonraker response.") from error
        if not isinstance(result, dict) or "error" in result:
            raise PrinterError("Moonraker reported an error.")
        return result.get("result", result)

    def status(self):
        connection = HTTPConnection(self.host, self.port, timeout=self.timeout)
        try:
            connection.request("GET", "/printer/info", headers=self.headers)
            info = self.result(connection)
            if info.get("state") != "ready":
                raise PrinterError("Klipper is not ready. Inspect the printer before starting.")
            connection.request("GET", "/server/job_queue/status", headers=self.headers)
            queue = self.result(connection)
            if queue.get("queued_jobs") != [] or queue.get("queue_state") not in {
                "ready",
                "paused",
            }:
                raise PrinterError("Clear pending Moonraker jobs in its UI. No new start sent.")
            connection.request(
                "POST",
                "/printer/objects/query",
                body=dumps(
                    {
                        "objects": {
                            "print_stats": ["state", "filename"],
                            "virtual_sdcard": ["progress", "is_active"],
                            "idle_timeout": ["state"],
                            "extruder": ["target"],
                            "heater_bed": ["target"],
                        }
                    }
                ),
                headers={**self.headers, "Content-Type": "application/json"},
            )
            objects = self.result(connection)["status"]
            stats, sd, idle = (
                objects[name] for name in ("print_stats", "virtual_sdcard", "idle_timeout")
            )
            state, filename = stats["state"], stats["filename"]
            progress = sd["progress"]
            targets = [objects.get(name, {}).get("target") for name in ("extruder", "heater_bed")]
            heaters_active = (
                any(value > 0 for value in targets)
                if all(
                    type(value) in {int, float} and isfinite(value) and value >= 0
                    for value in targets
                )
                else None
            )
            if (
                not isinstance(state, str)
                or not isinstance(filename, str)
                or len(filename) > 256
                or type(progress) not in {int, float}
                or not 0 <= progress <= 1
                or type(sd["is_active"]) is not bool
            ):
                raise ValueError
            normalized = {
                "printing": "printing",
                "paused": "paused",
                "complete": "completed",
                "error": "error",
                "cancelled": "cancelled",
                "standby": "ready",
            }.get(state, "unknown")
            # A completed/cancelled file can remain selected. Only an inactive idle
            # machine is eligible for the next fresh, bed-clear-confirmed job.
            if (
                state in {"complete", "cancelled", "standby"}
                and sd["is_active"] is False
                and idle["state"] in {"Ready", "Idle"}
            ):
                normalized = "completed" if state == "complete" else "ready"
            elif state in {"complete", "cancelled", "standby"}:
                normalized = "busy"
            native = self.native.status() if self.native else None
            if native:
                if native.error or native.state == "error":
                    raise PrinterError(
                        "Native printer reports an error. No new print will be sent."
                    )
                if native.state not in {"ready", "completed", "cancelled"}:
                    normalized = {
                        "printing": "printing",
                        "pause": "paused",
                        "paused": "paused",
                        "heating": "heating",
                    }.get(native.state, "busy")
                    # The native engine may run a different file while Moonraker
                    # retains the old selection. Never attribute that activity to it.
                    if normalized in {"printing", "paused", "heating"}:
                        if native.filename:
                            filename, progress = native.filename, native.progress
                        elif state not in {"printing", "paused"}:
                            normalized = "busy"
                if heaters_active is None:
                    raise PrinterError("Heater status unavailable. No new print will be sent.")
            if normalized in {"ready", "completed"} and heaters_active:
                normalized = "heating"
            if (
                native
                and native.state == "ready"
                and not native.filename
                and sd["is_active"] is False
                and heaters_active is False
                and state == "standby"
                and filename
            ):
                connection.request(
                    "GET", "/server/history/list?limit=10&order=desc", headers=self.headers
                )
                history = self.result(connection).get("jobs", [])
                matching = next((job for job in history if job.get("filename") == filename), None)
                if matching and matching.get("status") in {"completed", "cancelled"}:
                    state = "complete" if matching["status"] == "completed" else "cancelled"
                    normalized = "completed" if state == "complete" else "ready"
            return PrinterStatus(
                normalized,
                native.model_pid if native else 0,
                native.firmware if native else str(info.get("software_version", ""))[:128],
                filename,
                float(progress),
                state == "error",
                native.slots if native else (),
                job_state=state,
                is_active=sd["is_active"],
                heaters_active=heaters_active,
                native_state=native.state if native else None,
                native_filename=native.filename if native else None,
            )
        except (
            OSError,
            HTTPException,
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
        ) as error:
            raise PrinterError(
                "ZMOD/Moonraker status unavailable or unsupported. No new print will be sent."
            ) from error
        finally:
            connection.close()

    @staticmethod
    def require_ready(status, *, slot, material, colour_hex):
        if status.state not in {"ready", "completed"} or status.error:
            raise PrinterError("ZMOD printer is not idle and error-free. No print was sent.")
        if status.native_state is not None:
            match = next((item for item in status.slots if item.number == slot), None)
            if (
                not match
                or not match.loaded
                or match.material != material.upper()
                or match.colour_hex != colour_hex.upper()
            ):
                raise PrinterError(
                    "The selected IFS slot is not loaded with the configured material/colour."
                )
        # These are commissioned values AND a fresh operator attestation, not
        # purported live IFS sensor readings. Standard Moonraker has no colour sensor.
        return Slot(slot, material, colour_hex, True)

    def upload_and_print(self, source: Path, *, filename: str, slot: Slot):
        del slot  # Colour matching is in reviewed ZMOD settings and sliced metadata.
        if not fullmatch(r"pf_[0-9a-f]{32}_[0-9a-f]{12}\.gcode", filename):
            raise ValueError("Use a unique station-generated G-code filename.")
        size = source.stat().st_size
        if not 0 < size <= 200 * 1024 * 1024:
            raise PrinterError("G-code exceeds the upload limit.")
        with source.open("rb") as stream:
            digest = file_digest(stream, "sha256").hexdigest()
        boundary = "PrintFlow" + uuid4().hex
        fields = {"root": "gcodes", "print": "true", "checksum": digest}
        prefix = b"".join(
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'
            ).encode()
            for key, value in fields.items()
        )
        prefix += (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
            f'filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n'
        ).encode()
        suffix = f"\r\n--{boundary}--\r\n".encode()
        connection = HTTPConnection(self.host, self.port, timeout=self.timeout)
        try:
            connection.putrequest("POST", "/server/files/upload")
            for name, value in {
                **self.headers,
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(len(prefix) + size + len(suffix)),
            }.items():
                connection.putheader(name, value)
            connection.endheaders()
            connection.send(prefix)
            with source.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    connection.send(chunk)
            connection.send(suffix)
            result = self.result(connection, expected=201)
            if (
                result.get("item", {}).get("path") != filename
                or result.get("print_started") is not True
                or result.get("print_queued") is not False
            ):
                raise PrinterError(
                    "No immediate start confirmation. Inspect the printer; do not resend."
                )
        except (OSError, HTTPException, ValueError, AttributeError) as error:
            raise PrinterError(
                "ZMOD start is uncertain. Inspect the printer; do not resend."
            ) from error
        finally:
            connection.close()
