"""Explicit loopback lab wrapper; the frozen production drivers are not mocked."""

import json
import threading
import time
from contextlib import contextmanager

from test_print_station import paired_moonraker, simulated_printer


@contextmanager
def demo_printer(control, evidence):
    with simulated_printer(moonraker=True) as (port, events, detail):
        stop = threading.Event()

        def observe():
            while not stop.wait(0.25):
                starts = [
                    json.loads(body) for path, _headers, body in events if path == "/printGcode"
                ]
                if not starts:
                    continue
                state = (
                    json.loads(control.read_text())
                    if control.exists()
                    else {"phase": "printing", "progress": 0.4}
                )
                phase = state["phase"]
                filename = starts[-1]["fileName"]
                detail["status"] = "printing" if phase == "printing" else "ready"
                detail["printFileName"] = filename if phase == "printing" else ""
                detail["printProgress"] = state.get("progress", 1)
                detail["_moonraker"] = {
                    "print_stats": {
                        "state": "printing" if phase == "printing" else "complete",
                        "filename": filename,
                    },
                    "virtual_sdcard": {
                        "progress": state.get("progress", 1),
                        "is_active": phase == "printing",
                    },
                    "idle_timeout": {"state": "Printing" if phase == "printing" else "Ready"},
                    "extruder": {"target": 210 if phase == "printing" else 0},
                    "heater_bed": {"target": 60 if phase == "printing" else 0},
                }
                evidence.write_text(
                    json.dumps(
                        {
                            "label": "LOOPBACK SIMULATOR — NOT A PHYSICAL PRINTER",
                            "uploads": len(
                                [path for path, _, _ in events if path == "/server/files/upload"]
                            ),
                            "starts": len(starts),
                            "filename": filename,
                            "phase": phase,
                            "progress": state.get("progress", 1),
                            "observedAt": time.time(),
                        },
                        indent=2,
                    )
                )

        thread = threading.Thread(target=observe, daemon=True)
        thread.start()
        try:
            yield paired_moonraker(port)
        finally:
            stop.set()
            thread.join(timeout=2)
