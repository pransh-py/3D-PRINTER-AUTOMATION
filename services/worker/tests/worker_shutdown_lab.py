"""Disposable real-schema failure; reports worker cleanup hooks, not printer operations."""

import asyncio
import html
import json
from pathlib import Path

from pytest import MonkeyPatch
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import create_async_engine
from xxx_api.config import Settings
from xxx_api.models import Base

import xxx_worker.main as worker


async def reproduce_notice_failure():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync: Base.metadata.create_all(
                sync,
                tables=[
                    table for table in Base.metadata.sorted_tables if table.name != "notifications"
                ],
            )
        )
    cleanup = {"storage": False, "redis": False, "database": False}
    original_dispose = type(engine).dispose

    async def dispose(observed_engine, *args, **kwargs):
        assert observed_engine is engine
        cleanup["database"] = True
        await original_dispose(observed_engine, *args, **kwargs)

    class LabRedis:
        async def aclose(self):
            cleanup["redis"] = True

    class LabStorage:
        def __init__(self, _settings):
            pass

        def close(self):
            cleanup["storage"] = True

    class EmptyQueue:
        def __init__(self, *args, **kwargs):
            pass

        async def ensure_group(self):
            pass

        async def reclaim_stale(self, **kwargs):
            return None

        async def read_new(self, **kwargs):
            await asyncio.sleep(0.01)
            return None

    failure = None
    try:
        with MonkeyPatch.context() as patch:
            patch.setattr(
                worker,
                "get_settings",
                lambda: Settings(
                    _env_file=None, environment="test", workflow_notifications_enabled=True
                ),
            )
            patch.setattr(worker, "create_database_engine", lambda settings: engine)
            patch.setattr(type(engine), "dispose", dispose)
            patch.setattr(worker.Redis, "from_url", lambda *args, **kwargs: LabRedis())
            patch.setattr(worker, "create_object_storage", LabStorage)
            patch.setattr(worker, "AnalysisQueue", EmptyQueue)
            try:
                await asyncio.wait_for(worker._run_worker(once=False), timeout=5)
            except OperationalError as error:
                assert "no such table: notifications" in str(error)
                failure = "OperationalError: no such table: notifications"
    finally:
        # Always release the disposable harness, even when the unfixed worker did not.
        # This does not change the captured worker-hook flags above.
        await original_dispose(engine)
    assert failure, "the background schema failure must remain visible to the process"
    return {
        "labOnly": True,
        "trigger": "Start notice-enabled worker with a real SQLite schema missing notifications",
        "observedFailure": failure,
        "workerCleanupHooksReached": cleanup,
        "testTransports": "No network, SMTP, payment or printer action; empty queue/resource spies",
        "harnessCleanup": "Always disposes its own temporary database after observation",
    }


if __name__ == "__main__":
    from argparse import ArgumentParser

    parser = ArgumentParser()
    parser.add_argument("--capture", required=True, choices=["before", "after"])
    args = parser.parse_args()
    result = asyncio.run(reproduce_notice_failure())
    directory = Path(__file__).resolve().parents[3] / ".local/workflow/worker-shutdown-evidence"
    directory.mkdir(parents=True, exist_ok=True)
    rendered = html.escape(json.dumps(result, indent=2))
    (directory / f"{args.capture}.html").write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>Worker shutdown lab</title>'
        "<style>body{font:18px system-ui;margin:48px;max-width:1000px}pre{white-space:pre-wrap;"
        "padding:24px;background:#f2f4f6;font:16px monospace;line-height:1.6}</style>"
        f"<h1>Worker shutdown — {args.capture}</h1><p>Genuine disposable schema-failure replay; "
        f"no customer data or physical operation.</p><pre>{rendered}</pre></html>"
    )
    print(json.dumps(result, indent=2))
