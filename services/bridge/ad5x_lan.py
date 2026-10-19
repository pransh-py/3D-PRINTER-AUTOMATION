"""Narrow AD5X LAN adapter: authenticated status and one reviewed upload-and-print.

Protocol reference: OrcaSlicer v2.4.2 src/slic3r/Utils/Flashforge.cpp and the
Parallel-7 flashforge-api-docs AD5X reference. No discovery, arbitrary G-code console,
heating, movement or automatic retry is exposed here. Hardware verification is separate.
"""

from base64 import b64encode
from dataclasses import dataclass, field
from http.client import HTTPConnection, HTTPException
from ipaddress import IPv4Address, IPv4Network
from json import dumps, loads
from pathlib import Path
from re import fullmatch
from uuid import uuid4


class PrinterError(Exception):
    """Non-secret failure suitable for a local operator."""


@dataclass(frozen=True)
class Slot:
    number: int
    material: str
    colour_hex: str
    loaded: bool


@dataclass(frozen=True)
class PrinterStatus:
    state: str
    model_pid: int
    firmware: str
    filename: str
    progress: float
    error: bool
    slots: tuple[Slot, ...]
    job_state: str | None = None
    is_active: bool | None = None
    heaters_active: bool | None = None
    native_state: str | None = None
    native_filename: str | None = None


@dataclass(frozen=True)
class AD5XLan:
    host: str
    serial: str = field(repr=False)
    check_code: str = field(repr=False)
    port: int = 8898
    timeout: float = 20
    allow_loopback_test: bool = False

    def __post_init__(self):
        address = IPv4Address(self.host)
        private_lan = any(
            address in IPv4Network(network)
            for network in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
        )
        if not (private_lan or (address.is_loopback and self.allow_loopback_test)):
            raise ValueError("Configure a private LAN IPv4 address, not a public or loopback host.")
        if not 1 <= self.port <= 65535 or not 1 <= self.timeout <= 60:
            raise ValueError("Invalid printer connection settings.")
        if any(
            not value or len(value) > 128 or any(ord(c) < 32 or ord(c) > 126 for c in value)
            for value in (self.serial, self.check_code)
        ):
            raise ValueError("Configure valid LAN credentials locally.")

    @staticmethod
    def _result(connection: HTTPConnection) -> dict:
        response = connection.getresponse()
        data = response.read(1024 * 1024 + 1)
        if response.status != 200 or len(data) > 1024 * 1024:
            raise PrinterError("The printer returned an invalid response.")
        try:
            value = loads(data)
        except (ValueError, UnicodeError) as error:
            raise PrinterError("The printer did not return valid JSON.") from error
        if not isinstance(value, dict) or type(value.get("code")) is not int or value["code"] != 0:
            raise PrinterError(
                "The printer rejected the request. Check its screen and LAN credentials."
            )
        return value

    def status(self) -> PrinterStatus:
        connection = HTTPConnection(self.host, self.port, timeout=self.timeout)
        try:
            connection.request(
                "POST",
                "/detail",
                body=dumps({"serialNumber": self.serial, "checkCode": self.check_code}),
                headers={"Content-Type": "application/json"},
            )
            detail = self._result(connection).get("detail")
            if not isinstance(detail, dict):
                raise PrinterError("The printer status is missing.")
            raw_pid = detail.get("pid")
            pid = int(raw_pid, 16) if isinstance(raw_pid, str) else raw_pid
            # Native AD5X firmware 3.1.6 reports numeric 38 and name AD5X.
            native_ad5x = type(raw_pid) is int and raw_pid == 38 and detail.get("name") == "AD5X"
            if not native_ad5x and (type(pid) is not int or pid != 0x38):
                raise PrinterError("This device has not identified itself as an AD5X.")
            slots = []
            station = detail.get("matlStationInfo", {})
            if detail.get("hasMatlStation") is True and isinstance(station, dict):
                raw_slots = station.get("slotInfos", [])
                if not isinstance(raw_slots, list) or len(raw_slots) > 4:
                    raise PrinterError("Unsupported IFS slot information.")
                for item in raw_slots:
                    if not isinstance(item, dict):
                        continue
                    number, material, colour = (
                        item.get("slotId"),
                        item.get("materialName"),
                        item.get("materialColor"),
                    )
                    if (
                        type(number) is int
                        and 1 <= number <= 4
                        and isinstance(material, str)
                        and isinstance(colour, str)
                        and fullmatch(r"#[0-9a-fA-F]{6}", colour)
                    ):
                        slots.append(
                            Slot(
                                number,
                                material.upper(),
                                colour.upper(),
                                item.get("hasFilament") is True,
                            )
                        )
            state, filename, firmware = (
                detail.get("status"),
                detail.get("printFileName", ""),
                detail.get("firmwareVersion", ""),
            )
            progress = detail.get("printProgress", 0)
            if (
                not isinstance(state, str)
                or len(state) > 64
                or not isinstance(filename, str)
                or len(filename) > 256
                or not isinstance(firmware, str)
                or len(firmware) > 128
                or type(progress) not in {int, float}
                or not 0 <= progress <= 1
            ):
                raise PrinterError("The printer returned unsupported status fields.")
            return PrinterStatus(
                state,
                pid,
                firmware,
                filename,
                float(progress),
                detail.get("errorCode") not in ("", None, 0, "0"),
                tuple(slots),
            )
        except (OSError, ValueError, HTTPException) as error:
            raise PrinterError(
                "Printer connection unavailable. Check LAN mode, IP address and credentials."
            ) from error
        finally:
            connection.close()

    @staticmethod
    def require_ready(status: PrinterStatus, *, slot: int, material: str, colour_hex: str) -> Slot:
        if status.state != "ready" or status.error:
            raise PrinterError("The AD5X is not idle and error-free. No print was sent.")
        match = next((item for item in status.slots if item.number == slot), None)
        if (
            match is None
            or not match.loaded
            or match.material != material.upper()
            or match.colour_hex != colour_hex.upper()
        ):
            raise PrinterError(
                "The IFS slot, loaded material or colour changed. Check the spool and mapping."
            )
        return match

    def upload_and_print(self, source: Path, *, filename: str, slot: Slot) -> None:
        """Send once, after a persisted intent. Every uncertain result is ambiguous."""
        if not fullmatch(r"pf_[0-9a-f]{32}_[0-9a-f]{12}\.3mf", filename):
            raise ValueError("Use a job-specific generated printer filename.")
        size = source.stat().st_size
        if not 0 < size <= 200 * 1024 * 1024:
            raise PrinterError("The sliced package exceeds the upload limit.")
        boundary = "PrintFlow" + uuid4().hex
        prefix = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="gcodeFile"; '
            f'filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n'
        ).encode()
        suffix = f"\r\n--{boundary}--\r\n".encode()
        mapping = [
            {
                "toolId": 0,
                "slotId": slot.number,
                "materialName": slot.material,
                "toolMaterialColor": slot.colour_hex,
                "slotMaterialColor": slot.colour_hex,
            }
        ]
        headers = {
            "serialNumber": self.serial,
            "checkCode": self.check_code,
            "fileSize": str(size),
            "printNow": "true",
            "levelingBeforePrint": "true",
            "flowCalibration": "false",
            "firstLayerInspection": "false",
            "timeLapseVideo": "false",
            "useMatlStation": "true",
            "gcodeToolCnt": "1",
            "materialMappings": b64encode(dumps(mapping, separators=(",", ":")).encode()).decode(),
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(prefix) + size + len(suffix)),
        }
        connection = HTTPConnection(self.host, self.port, timeout=self.timeout)
        try:
            connection.putrequest("POST", "/uploadGcode")
            for name, value in headers.items():
                connection.putheader(name, value)
            connection.endheaders()
            connection.send(prefix)
            with source.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    connection.send(chunk)
            connection.send(suffix)
            self._result(connection)
        except (OSError, ValueError, HTTPException) as error:
            raise PrinterError(
                "Print start is uncertain. Inspect the printer; do not send the job again."
            ) from error
        finally:
            connection.close()
