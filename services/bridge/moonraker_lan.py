"""ZMOD transport using documented Moonraker APIs, with no arbitrary G-code RPC.

The operator must commission ZMOD single-material colour matching and the silent
start settings separately. Moonraker standard status does NOT prove spool colour.
"""

from dataclasses import dataclass, field
from hashlib import file_digest
from http.client import HTTPConnection, HTTPException
from json import dumps, loads
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
            return PrinterStatus(
                normalized,
                0,
                str(info.get("software_version", ""))[:128],
                filename,
                float(progress),
                state == "error",
                (),
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
