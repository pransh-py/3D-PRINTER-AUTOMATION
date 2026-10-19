"""Windows-compatible outbound approved-artifact handoff; no physical printer control.

Credentials are read from the terminal, never arguments or plaintext credential files.
Use --pair once, then --receive with the returned credential to download a reviewed job.
"""

from argparse import ArgumentParser
from getpass import getpass
from hashlib import sha256
from json import dumps, loads
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID

MAX_ARTIFACT_BYTES = 200 * 1024 * 1024


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError(
            "Redirects are disabled so bridge credentials cannot leave the configured API"
        )


class ManualBridge:
    def __init__(self, origin: str, credential: str = ""):
        parsed = urlparse(origin)
        if (
            (
                parsed.scheme != "https"
                and not (
                    parsed.scheme == "http"
                    and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
                )
            )
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError(
                "Use an HTTPS API origin, or a loopback HTTP origin for a local lab"
            )
        self.origin = origin.rstrip("/")
        self.credential = credential
        self.opener = build_opener(NoRedirect())

    def request(self, path: str, body: dict | None = None, *, binary: bool = False):
        if not path.startswith("/api/v1/bridge/") or "?" in path or "#" in path:
            raise ValueError("Only credential-scoped bridge API paths are permitted")
        headers = {"Accept": "application/json"}
        if self.credential:
            headers["Authorization"] = f"Bearer {self.credential}"
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = Request(
            self.origin + path,
            data=dumps(body).encode() if body is not None else None,
            headers=headers,
            method="POST" if body is not None else "GET",
        )
        with self.opener.open(request, timeout=30) as response:
            limit = MAX_ARTIFACT_BYTES if binary else 1024 * 1024
            data = response.read(limit + 1)
            if len(data) > limit:
                raise ValueError("Bridge response exceeded its size limit")
            return data if binary else loads(data) if data else None

    def receive(self, authorization_id: str, destination: Path) -> list[Path]:
        identifier = str(UUID(authorization_id))
        prefix = f"/api/v1/bridge/handoffs/{identifier}"
        package = self.request(prefix + "/claim", {})
        if not isinstance(package, dict) or package.get("dispatchEnabled") is not False:
            raise ValueError("Only the disabled-dispatch manual adapter is supported")
        items = package.get("items")
        if not isinstance(items, list) or not 1 <= len(items) <= 10:
            raise ValueError("Invalid artifact manifest")
        manifest = []
        for item in items:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("quantity"), int)
                or isinstance(item["quantity"], bool)
                or not 1 <= item["quantity"] <= 100
                or not isinstance(item.get("position"), int)
                or not 1 <= item["position"] <= 10
                or not isinstance(item.get("sha256"), str)
                or len(item["sha256"]) != 64
                or item.get("downloadUrl") != f"{prefix}/artifacts/{UUID(item['id'])}"
            ):
                raise ValueError("Invalid artifact manifest item")
            manifest.append(item)
        canonical = [
            {
                "position": item["position"],
                "sha256": item["sha256"],
                "quantity": item["quantity"],
                "resultId": str(UUID(item["resultId"])),
            }
            for item in manifest
        ]
        calculated = sha256(
            dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if calculated != package.get("manifestSha256"):
            raise ValueError("The handoff manifest does not match its authorization")
        # Never overwrite an existing handoff directory or any user file.
        target = destination / identifier
        target.mkdir(parents=True, exist_ok=False)
        paths = []
        for item in manifest:
            data = self.request(item["downloadUrl"], binary=True)
            if sha256(data).hexdigest() != item["sha256"]:
                raise ValueError(
                    "Artifact hash verification failed; do not print this job"
                )
            path = target / f"part-{item['position']}-quantity-{item['quantity']}.gcode"
            with path.open("xb") as stream:
                stream.write(data)
            paths.append(path)
        with (target / "manifest.json").open("x", encoding="utf-8") as stream:
            stream.write(dumps(package, indent=2))
        self.request(prefix + "/received", {})
        return paths


def main() -> None:
    parser = ArgumentParser(
        description="Approved G-code handoff. Never dispatches to a printer."
    )
    parser.add_argument(
        "--api", required=True, help="API origin, e.g. https://api.example.com"
    )
    parser.add_argument("--destination", type=Path, default=Path(".state/handoffs"))
    parser.add_argument("--pair", action="store_true")
    parser.add_argument("--receive", metavar="AUTHORIZATION_UUID")
    args = parser.parse_args()
    bridge = ManualBridge(args.api)
    try:
        if args.pair:
            result = bridge.request(
                "/api/v1/bridge/pair", {"token": getpass("One-use pairing token: ")}
            )
            print(
                "Pairing complete. Store this credential in Windows Credential Manager; it is shown once:"
            )
            print(result["credential"])
            return
        bridge.credential = getpass("Bridge credential: ")
        bridge.request("/api/v1/bridge/heartbeat", {})
        if args.receive:
            for path in bridge.receive(args.receive, args.destination):
                print(f"Verified artifact: {path}")
            print(
                "No print command was sent. Review every artifact and quantity in Orca before manual printing."
            )
        else:
            result = bridge.request("/api/v1/bridge/handoffs")
            for item in result["items"]:
                print(
                    f"Handoff {item['id']} · job {item['jobId']} · expires {item['expiresAt']}"
                )
    except (HTTPError, OSError, ValueError, KeyError, TypeError) as error:
        # No request headers, token material, payloads or private source filenames in diagnostics.
        print(
            f"Handoff stopped: {type(error).__name__}. Check pairing, expiry, manifest and API availability."
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
