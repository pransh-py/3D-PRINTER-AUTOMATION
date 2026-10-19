"""Compare measured slicer outputs without connecting to or commanding a printer."""

import argparse
import json
from hashlib import file_digest
from pathlib import Path

from xxx_worker.slicing import gcode_metrics
from xxx_worker.validation import ModelValidationError


def evidence(path: Path) -> dict[str, int | str]:
    if not path.is_file() or not 0 < path.stat().st_size <= 200 * 1024 * 1024:
        raise ValueError("Use a non-empty G-code export no larger than 200 MiB.")
    mass, duration = gcode_metrics(path.read_bytes())
    with path.open("rb") as stream:
        digest = file_digest(stream, "sha256").hexdigest()
    return {"sha256": digest, "filamentMg": mass, "durationSeconds": duration}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("worker_export", type=Path)
    parser.add_argument("print_station_export", type=Path)
    args = parser.parse_args()
    try:
        worker = evidence(args.worker_export)
        station = evidence(args.print_station_export)
        print(
            json.dumps(
                {
                    "worker": worker,
                    "printStation": station,
                    "sameArtifact": worker["sha256"] == station["sha256"],
                    "massDifferenceMg": int(station["filamentMg"])
                    - int(worker["filamentMg"]),
                    "durationDifferenceSeconds": int(station["durationSeconds"])
                    - int(worker["durationSeconds"]),
                    "scope": "Metadata comparison only. Equal mass/time does not prove identical toolpaths or printer safety. No printer was contacted.",
                },
                indent=2,
            )
        )
    except (OSError, ValueError, ModelValidationError) as error:
        parser.exit(2, f"Comparison unavailable: {error}\n")


if __name__ == "__main__":
    main()
