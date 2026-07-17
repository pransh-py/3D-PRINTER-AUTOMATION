"""S3-compatible signed POST policy tests."""

from asyncio import run
from base64 import b64decode
from json import loads
from pathlib import Path
from typing import Any, cast

import pytest

from xxx_api.config import Settings
from xxx_api.storage import ObjectStorageError, S3ObjectStorage


class FakeBody:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.offset = 0
        self.closed = False

    def read(self, size: int) -> bytes:
        chunk = self.data[self.offset : self.offset + size]
        self.offset += len(chunk)
        return chunk

    def close(self) -> None:
        self.closed = True


class DownloadClient:
    def __init__(self, data: bytes, *, declared_length: int | None = None) -> None:
        self.body = FakeBody(data)
        self.declared_length = len(data) if declared_length is None else declared_length

    def get_object(self, **_kwargs: object) -> dict[str, object]:
        return {"ContentLength": self.declared_length, "Body": self.body}

    def close(self) -> None:
        pass


def test_presigned_post_binds_key_size_type_and_metadata() -> None:
    async def scenario() -> None:
        storage = S3ObjectStorage(Settings(environment="test"))
        upload = await storage.create_upload(
            key="models/original/user/quote/asset/source",
            size_bytes=4096,
            content_type="application/octet-stream",
            metadata={"asset-id": "asset", "sha256": "a" * 64},
        )
        policy = loads(b64decode(upload.fields["policy"]).decode("utf-8"))
        conditions = policy["conditions"]

        assert upload.fields["key"] == "models/original/user/quote/asset/source"
        assert ["content-length-range", 4096, 4096] in conditions
        assert {"Content-Type": "application/octet-stream"} in conditions
        assert {"x-amz-meta-asset-id": "asset"} in conditions
        assert {"x-amz-meta-sha256": "a" * 64} in conditions
        assert upload.url.startswith("http://127.0.0.1:9000/")
        storage.close()

    run(scenario())


def test_private_download_is_bounded_and_removes_partial_files(tmp_path: Path) -> None:
    async def successful() -> None:
        storage = S3ObjectStorage(Settings(environment="test"))
        client = DownloadClient(b"model-bytes")
        storage._client = cast(Any, client)
        destination = tmp_path / "complete"

        observed = await storage.download_to_path("private-key", destination, max_bytes=32)

        assert observed == 11
        assert destination.read_bytes() == b"model-bytes"
        assert client.body.closed is True

    async def rejected() -> None:
        storage = S3ObjectStorage(Settings(environment="test"))
        client = DownloadClient(b"too-large")
        storage._client = cast(Any, client)
        destination = tmp_path / "partial"

        with pytest.raises(ObjectStorageError, match="outside the allowed range"):
            await storage.download_to_path("private-key", destination, max_bytes=3)

        assert not destination.exists()
        assert client.body.closed is True

    run(successful())
    run(rejected())
