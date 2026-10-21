"""Disposable software E2E: real Orca, private upload, fictional payment, loopback AD5X.

Never import this factory in production. No physical printer configuration is read.
"""

import asyncio
import json
from contextlib import asynccontextmanager
from hashlib import file_digest, sha256
from pathlib import Path
from uuid import uuid4

from ad5x_simulator import demo_printer
from services.bridge.commerce_connector import ApprovedProfile, CommerceConnector, ConnectorConfig
from services.bridge.print_station import Connection, Mapping, Profile, Station, StationConfig
from sqlalchemy import select
from workflow_lab import create_lab
from xxx_worker.main import create_worker_redis
from xxx_worker.orchestrator import (
    AnalysisOrchestrator,
    DeliveryDisposition,
    dispatch_analysis_outbox,
)
from xxx_worker.queue import AnalysisQueue
from xxx_worker.sandbox import SandboxValidator

from xxx_api.local_storage import LocalObjectStorage
from xxx_api.models.identity import User
from xxx_api.razorpay import ProviderOrder, ProviderPayment
from xxx_api.services.bridge import begin_pairing, finish_pairing
from xxx_api.services.commerce import enqueue_paid_orders
from xxx_api.services.pricing import (
    activate_pricing_policy,
    create_pending_estimates,
    create_pricing_policy,
)

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / ".local/evidence/order-station"


class DemoGateway:
    """Multi-order fictional provider. Never selected by the production app factory."""

    def __init__(self):
        self.orders = {}
        self.payments = {}

    async def create_order(self, *, amount, receipt):
        order = ProviderOrder(
            id="order_Demo" + uuid4().hex,
            entity="order",
            amount=amount,
            receipt=receipt,
            currency="INR",
            status="created",
            amount_paid=0,
            amount_due=amount,
        )
        self.orders[order.id] = order
        return order

    async def find_orders(self, *, receipt):
        return [order for order in self.orders.values() if order.receipt == receipt]

    async def fetch_order(self, order_id):
        order = self.orders[order_id]
        if order.status == "created":
            order = order.model_copy(
                update={"status": "paid", "amount_paid": order.amount, "amount_due": 0}
            )
            self.orders[order_id] = order
            payment = ProviderPayment(
                id="pay_Demo" + uuid4().hex,
                entity="payment",
                order_id=order_id,
                amount=order.amount,
                currency="INR",
                status="captured",
                captured=True,
                amount_refunded=0,
            )
            self.payments[payment.id] = payment
        return order

    async def fetch_payment(self, payment_id):
        return self.payments[payment_id]

    async def order_payments(self, order_id):
        return [payment for payment in self.payments.values() if payment.order_id == order_id]


def create_dispatch_lab():
    app = create_lab(payments=True)
    original = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(current):
        async with original(current):
            app.state.payment_gateway = DemoGateway()
            settings = app.state.settings
            directory = app.state.lab_access_file.parent
            profiles = directory / "simulator-only-profiles"
            profiles.mkdir()
            digest = sha256()
            for name in ("machine.json", "process.json", "filament.json"):
                value = json.loads(
                    (ROOT / ".local/service/verification-preset" / name).read_bytes()
                )
                if name == "filament.json":
                    value["filament_colour"] = ["#FF0000"]
                if name == "process.json":
                    value["curr_bed_type"] = "Cool Plate"
                data = json.dumps(value).encode()
                (profiles / name).write_bytes(data)
                digest.update(name.encode() + b"\0" + data)
            profile_hash = digest.hexdigest()
            manifest = profiles / "presets.json"
            manifest.write_text(
                json.dumps(
                    [
                        {
                            "code": "demo-pla",
                            "label": "DEMO ONLY · PLA standard",
                            "materialCode": "pla",
                            "colours": ["red"],
                            "profileDirectory": str(profiles),
                            "profileSha256": profile_hash,
                        }
                    ]
                )
            )
            binary = (
                ROOT / ".local/service/orca-mount.U8SJHn/OrcaSlicer.app/Contents/MacOS/OrcaSlicer"
            )
            with binary.open("rb") as source:
                binary_hash = file_digest(source, "sha256").hexdigest()
            settings.allowed_origins = ["http://localhost:3111", "http://127.0.0.1:3111"]
            settings.public_web_url = "http://localhost:3111"
            settings.printer_dispatch_enabled = True
            settings.analysis_slicer_command = binary
            settings.analysis_slicer_sha256 = binary_hash
            settings.analysis_slicer_version = "2.4.2"
            settings.analysis_preset_manifest = manifest
            settings.analysis_slicer_timeout_seconds = 60
            settings.analysis_validator_command = str(ROOT / ".venv313/bin/xxx-analyzer")
            settings.analysis_stream_name = "demo:analysis:" + uuid4().hex[:12]
            settings.analysis_consumer_group = "demo-workers"
            settings.redis_url = "redis://127.0.0.1:56379/14"
            settings.storage_backend = "local"
            settings.storage_local_directory = directory / "private-models"
            app.state.object_storage = LocalObjectStorage(settings)
            async with app.state.session_factory() as session:
                owner = await session.scalar(select(User).where(User.owner_slot == "primary"))
                policy = await create_pricing_policy(
                    session,
                    owner=owner,
                    machine_rate_paise_per_hour=10000,
                    setup_fee_paise=1000,
                    minimum_order_paise=10000,
                    contingency_bps=0,
                    tax_bps=0,
                    estimate_validity_hours=24,
                    materials=[("pla", "DEMO ONLY PLA — not approved selling prices", 200)],
                )
                await activate_pricing_policy(session, owner=owner, policy_id=policy.id)
                _installation, token = await begin_pairing(
                    session, owner, "Lab simulator — not a printer"
                )
                _bridge, credential = await finish_pairing(
                    session, token, adapter="station-zmod-v1"
                )
            access = json.loads(app.state.lab_access_file.read_bytes())
            access["profileSha256"] = profile_hash
            app.state.lab_access_file.write_text(json.dumps(access))
            (EVIDENCE / "active-lab.txt").write_text(str(app.state.lab_access_file))
            control = EVIDENCE / "simulator-control.json"
            if not control.exists():
                control.write_text('{"phase":"printing","progress":0.4}')
            redis = create_worker_redis(settings)
            queue = AnalysisQueue(
                redis,
                stream=settings.analysis_stream_name,
                group=settings.analysis_consumer_group,
                consumer="demo-local",
            )
            await queue.ensure_group()
            orchestrator = AnalysisOrchestrator(
                settings,
                app.state.session_factory,
                app.state.object_storage,
                SandboxValidator(settings.analysis_validator_command, timeout_seconds=60),
            )

            async def work():
                while True:
                    async with app.state.session_factory() as session:
                        await enqueue_paid_orders(session)
                        await create_pending_estimates(session)
                    await dispatch_analysis_outbox(app.state.session_factory, queue)
                    message = await queue.read_new(block_ms=100)
                    if (
                        message
                        and await orchestrator.process(message) is DeliveryDisposition.ACKNOWLEDGE
                    ):
                        await queue.acknowledge(message)
                    await asyncio.sleep(0.5)

            with demo_printer(control, EVIDENCE / "simulator-observation.json") as driver:
                config = StationConfig(
                    slicer=binary,
                    slicer_sha256=binary_hash,
                    slicer_version="2.4.2",
                    bed_type="Cool Plate",
                    profiles={
                        "PLA": Profile(
                            directory=profiles, sha256=profile_hash, approved_for_printer=True
                        )
                    },
                    printer=Connection(
                        transport="moonraker",
                        host="127.0.0.1",
                        zmod_start_reviewed=True,
                        mappings={"PLA:red": Mapping(slot=1, colour_hex="#FF0000")},
                    ),
                )
                station = Station(
                    config, directory / "simulated-station", enable_printer=True, driver=driver
                )
                connector = CommerceConnector(
                    station,
                    ConnectorConfig(
                        api_origin="http://127.0.0.1:8032",
                        credential=credential,
                        approved_profiles=[
                            ApprovedProfile(
                                profileSha256=profile_hash,
                                material="PLA",
                                stationBedType="Cool Plate",
                            )
                        ],
                    ),
                )
                tasks = [
                    asyncio.create_task(work()),
                    asyncio.create_task(station.monitor()),
                    asyncio.create_task(connector.run()),
                ]
                try:
                    yield
                finally:
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                    await redis.aclose()

    app.router.lifespan_context = lifespan
    return app
