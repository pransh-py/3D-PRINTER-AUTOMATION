"""Quote ownership, idempotency, upload quarantine, and submission tests."""

from asyncio import run
from datetime import UTC, datetime, timedelta
from json import dumps
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from xxx_api.config import Settings
from xxx_api.domain.auth import UserStatus
from xxx_api.domain.quotes import ModelAssetStatus, QuoteRequestStatus
from xxx_api.domain.roles import Role
from xxx_api.models import AnalysisRun, AuditEvent, Base, OutboxEvent, User
from xxx_api.services.quotes import (
    InvalidModelUploadError,
    QuoteRequestNotFoundError,
    complete_model_upload,
    create_model_upload,
    create_quote_request,
    get_quote_request,
    submit_quote_request,
)
from xxx_api.storage import ObjectMetadata, PresignedPost


class FakeStorage:
    """In-memory private-object evidence without accepting file bodies."""

    def __init__(self) -> None:
        self.objects: dict[str, ObjectMetadata] = {}
        self.deleted: list[str] = []

    async def create_upload(
        self,
        *,
        key: str,
        size_bytes: int,
        content_type: str,
        metadata: dict[str, str],
    ) -> PresignedPost:
        return PresignedPost(
            url="http://storage.test/upload",
            fields={"key": key, "Content-Type": content_type, **metadata},
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )

    async def head(self, key: str) -> ObjectMetadata:
        return self.objects[key]

    async def delete(self, key: str) -> None:
        self.deleted.append(key)
        self.objects.pop(key, None)

    async def check_ready(self) -> None:
        pass


async def _database() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def _users(sessions: async_sessionmaker[AsyncSession]) -> tuple[User, User, User]:
    now = datetime.now(UTC)
    first = User(
        email="first@example.com",
        display_name="First",
        password_hash="unused",
        role=Role.BUYER,
        status=UserStatus.ACTIVE,
        email_verified_at=now,
        password_changed_at=now,
    )
    second = User(
        email="second@example.com",
        display_name="Second",
        password_hash="unused",
        role=Role.BUYER,
        status=UserStatus.ACTIVE,
        email_verified_at=now,
        password_changed_at=now,
    )
    owner = User(
        email="owner@example.com",
        display_name="Owner",
        password_hash="unused",
        role=Role.OWNER,
        owner_slot="primary",
        status=UserStatus.ACTIVE,
        email_verified_at=now,
        password_changed_at=now,
    )
    async with sessions() as session:
        session.add_all((first, second, owner))
        await session.commit()
    return first, second, owner


def test_quote_upload_is_private_idempotent_and_quarantined_before_submit() -> None:
    async def scenario() -> None:
        sessions = await _database()
        first, second, owner = await _users(sessions)
        settings = Settings(environment="test")
        storage = FakeStorage()
        quote_token = uuid4()
        async with sessions() as session:
            quote = await create_quote_request(
                session,
                buyer=first,
                client_token=quote_token,
            )
        async with sessions() as session:
            repeated = await create_quote_request(
                session,
                buyer=first,
                client_token=quote_token,
            )
            assert repeated.id == quote.id
        async with sessions() as session:
            with pytest.raises(QuoteRequestNotFoundError):
                await get_quote_request(session, user=second, request_id=quote.id)
        async with sessions() as session:
            owner_view = await get_quote_request(session, user=owner, request_id=quote.id)
            assert owner_view.buyer_id == first.id

        upload_token = uuid4()
        digest = "a" * 64
        async with sessions() as session:
            issued = await create_model_upload(
                session,
                settings,
                storage,
                buyer=first,
                request_id=quote.id,
                client_token=upload_token,
                filename="../../private/model.STL",
                size_bytes=1024,
                sha256=digest,
            )
            assert issued.asset.original_filename == "model.STL"
            assert issued.asset.status is ModelAssetStatus.PENDING_UPLOAD
            assert "model.STL" not in issued.upload.fields["key"]
        storage.objects[issued.upload.fields["key"]] = ObjectMetadata(
            size_bytes=1024,
            content_type="application/octet-stream",
            metadata={"asset-id": str(issued.asset.id), "sha256": digest},
            etag='"untrusted-etag"',
        )
        async with sessions() as session:
            completed = await complete_model_upload(
                session,
                storage,
                buyer=first,
                request_id=quote.id,
                asset_id=issued.asset.id,
            )
            assert completed.status is ModelAssetStatus.QUARANTINED
            assert completed.verified_sha256 is None
        async with sessions() as session:
            submitted = await submit_quote_request(
                session,
                buyer=first,
                request_id=quote.id,
            )
            assert submitted.status is QuoteRequestStatus.ANALYZING
            assert submitted.version == 2
            assert len(submitted.analysis_runs) == 1
            assert submitted.analysis_runs[0].request_version == 2
        async with sessions() as session:
            runs = list(await session.scalars(select(AnalysisRun)))
            outbox = list(await session.scalars(select(OutboxEvent)))
            assert len(runs) == 1
            assert len(outbox) == 1
            assert outbox[0].topic == "analysis.requested"
            assert outbox[0].aggregate_id == runs[0].id
            assert outbox[0].payload == {
                "analysis_run_id": str(runs[0].id),
                "quote_request_id": str(quote.id),
                "request_version": 2,
            }
        async with sessions() as session:
            events = list(await session.scalars(select(AuditEvent)))
            serialized_details = dumps([event.details for event in events])
            assert "models/original" not in serialized_details
            assert digest not in serialized_details
            assert "model.STL" not in serialized_details

    run(scenario())


def test_mismatched_upload_is_deleted_and_rejected() -> None:
    async def scenario() -> None:
        sessions = await _database()
        buyer, _, _ = await _users(sessions)
        settings = Settings(environment="test")
        storage = FakeStorage()
        async with sessions() as session:
            quote = await create_quote_request(session, buyer=buyer, client_token=uuid4())
        async with sessions() as session:
            issued = await create_model_upload(
                session,
                settings,
                storage,
                buyer=buyer,
                request_id=quote.id,
                client_token=uuid4(),
                filename="part.3mf",
                size_bytes=4096,
                sha256="b" * 64,
            )
        key = issued.upload.fields["key"]
        storage.objects[key] = ObjectMetadata(
            size_bytes=4095,
            content_type="application/octet-stream",
            metadata={"asset-id": str(issued.asset.id), "sha256": "b" * 64},
            etag=None,
        )
        async with sessions() as session:
            with pytest.raises(InvalidModelUploadError):
                await complete_model_upload(
                    session,
                    storage,
                    buyer=buyer,
                    request_id=quote.id,
                    asset_id=issued.asset.id,
                )
        assert storage.deleted == [key]
        async with sessions() as session:
            persisted = await get_quote_request(session, user=buyer, request_id=quote.id)
            assert persisted.assets[0].status is ModelAssetStatus.REJECTED
            assert persisted.assets[0].rejection_code == "upload_metadata_mismatch"

    run(scenario())


def test_model_declarations_fail_closed() -> None:
    async def scenario() -> None:
        sessions = await _database()
        buyer, _, _ = await _users(sessions)
        settings = Settings(environment="test", max_model_file_bytes=1024)
        storage = FakeStorage()
        async with sessions() as session:
            quote = await create_quote_request(session, buyer=buyer, client_token=uuid4())
        for filename, size, digest in (
            ("toolpath.gcode", 100, "a" * 64),
            ("part.stl", 1025, "a" * 64),
            ("part.stl", 100, "not-a-digest"),
        ):
            async with sessions() as session:
                with pytest.raises(InvalidModelUploadError):
                    await create_model_upload(
                        session,
                        settings,
                        storage,
                        buyer=buyer,
                        request_id=quote.id,
                        client_token=uuid4(),
                        filename=filename,
                        size_bytes=size,
                        sha256=digest,
                    )

    run(scenario())
