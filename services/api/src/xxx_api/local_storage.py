"""Private single-machine development storage; never a public file server."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from functools import partial
from hashlib import sha256
from json import JSONDecodeError, dumps, loads
from pathlib import Path
from typing import cast
from uuid import UUID

from anyio import open_file, to_thread

from xxx_api.config import Settings
from xxx_api.storage import ObjectMetadata, ObjectNotFoundError, ObjectStorageError, PresignedPost

MAX_OBJECT_BYTES = 200 * 1024 * 1024


class LocalObjectStorage:
    def __init__(self, settings: Settings) -> None:
        if settings.storage_backend != "local" or settings.environment not in {
            "development",
            "test",
        }:
            raise ObjectStorageError("Local storage is not enabled for this environment.")
        directory = settings.storage_local_directory
        if directory is None or directory.is_symlink():
            raise ObjectStorageError("Configure a private local storage directory.")
        self.root = directory.resolve()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.ttl = settings.upload_url_ttl_seconds

    def _directory(self, key: str) -> Path:
        # Object keys never become filesystem path components.
        directory = self.root / sha256(key.encode()).hexdigest()
        if directory.is_symlink():
            raise ObjectStorageError("Invalid private object directory.")
        return directory

    async def create_upload(
        self, *, key: str, size_bytes: int, content_type: str, metadata: dict[str, str]
    ) -> PresignedPost:
        parts = key.split("/")
        try:
            if len(parts) != 6 or parts[:2] != ["models", "original"] or parts[-1] != "source":
                raise ValueError
            request_id, asset_id = UUID(parts[3]), UUID(parts[4])
        except (ValueError, IndexError) as error:
            raise ObjectStorageError("Invalid private upload reference.") from error
        return PresignedPost(
            url=f"/api/v1/quote-requests/{request_id}/uploads/{asset_id}/content",
            fields={},
            expires_at=datetime.now(UTC) + timedelta(seconds=self.ttl),
            method="PUT",
        )

    async def receive(
        self,
        key: str,
        chunks: AsyncIterator[bytes],
        *,
        expected_size: int,
        expected_sha256: str,
        metadata: dict[str, str],
        content_type: str = "application/octet-stream",
    ) -> None:
        if not 0 < expected_size <= MAX_OBJECT_BYTES:
            raise ObjectStorageError("Private upload size is outside the allowed range.")
        directory = self._directory(key)
        try:
            directory.mkdir(mode=0o700, exist_ok=False)
        except OSError as error:
            raise ObjectStorageError(
                "An upload already exists or storage is unavailable."
            ) from error
        complete = False
        try:
            observed = 0
            digest = sha256()
            async with await open_file(directory / "data", "xb") as stream:
                async for chunk in chunks:
                    observed += len(chunk)
                    if observed > expected_size:
                        raise ObjectStorageError("The upload exceeds its declared size.")
                    digest.update(chunk)
                    await stream.write(chunk)
            if observed != expected_size or digest.hexdigest() != expected_sha256:
                raise ObjectStorageError("The upload length or checksum does not match.")
            async with await open_file(
                directory / "metadata.json", "x", encoding="utf-8"
            ) as stream:
                await stream.write(
                    dumps(
                        {
                            "size": observed,
                            "contentType": content_type,
                            "metadata": metadata,
                            "etag": digest.hexdigest(),
                        }
                    )
                )
            complete = True
        except OSError as error:
            raise ObjectStorageError("The private upload could not be stored.") from error
        finally:
            if not complete:
                for name in ("data", "metadata.json"):
                    (directory / name).unlink(missing_ok=True)
                directory.rmdir()

    def _head(self, key: str) -> ObjectMetadata:
        directory = self._directory(key)
        data, metadata = directory / "data", directory / "metadata.json"
        try:
            if data.is_symlink() or metadata.is_symlink():
                raise ObjectStorageError("Invalid private object.")
            if not metadata.is_file() or not data.is_file():
                raise ObjectNotFoundError("The private object is not complete.")
            if metadata.stat().st_size > 65536:
                raise ObjectStorageError("Invalid private object metadata.")
            value = loads(metadata.read_bytes())
            if not isinstance(value, dict) or value.get("size") != data.stat().st_size:
                raise ObjectStorageError("The private object size changed.")
            return ObjectMetadata(
                size_bytes=data.stat().st_size,
                content_type=str(value["contentType"]),
                metadata=cast(dict[str, str], value["metadata"]),
                etag=str(value["etag"]),
            )
        except (OSError, JSONDecodeError, KeyError, UnicodeError) as error:
            raise ObjectStorageError("The private object could not be inspected.") from error

    async def head(self, key: str) -> ObjectMetadata:
        return await to_thread.run_sync(self._head, key)

    async def delete(self, key: str) -> None:
        directory = self._directory(key)
        if directory.exists():
            for name in ("data", "metadata.json"):
                (directory / name).unlink(missing_ok=True)
            directory.rmdir()

    def _download(self, key: str, destination: Path, max_bytes: int) -> int:
        metadata = self._head(key)
        if not 0 < metadata.size_bytes <= max_bytes:
            raise ObjectStorageError("The object exceeds the download limit.")
        created = False
        try:
            observed = 0
            with (
                (self._directory(key) / "data").open("rb") as source,
                destination.open("xb") as target,
            ):
                created = True
                while chunk := source.read(1024 * 1024):
                    observed += len(chunk)
                    if observed > max_bytes:
                        raise ObjectStorageError("The object exceeds the download limit.")
                    target.write(chunk)
            if observed != metadata.size_bytes:
                raise ObjectStorageError("The private object changed during download.")
            return observed
        except (OSError, ObjectStorageError) as error:
            if created:
                destination.unlink(missing_ok=True)
            raise ObjectStorageError("The private object could not be downloaded.") from error

    async def download_to_path(self, key: str, destination: Path, *, max_bytes: int) -> int:
        return await to_thread.run_sync(partial(self._download, key, destination, max_bytes))

    async def check_ready(self) -> None:
        if not self.root.is_dir():
            raise ObjectStorageError("The private local storage directory is unavailable.")

    async def upload_from_path(self, key: str, source: Path, *, content_type: str) -> None:
        if not source.is_file() or not 0 < source.stat().st_size <= MAX_OBJECT_BYTES:
            raise ObjectStorageError("The derived artifact is outside the size limit.")
        digest = sha256()
        async with await open_file(source, "rb") as stream:
            while chunk := await stream.read(1024 * 1024):
                digest.update(chunk)
        try:
            existing = await self.head(key)
        except ObjectNotFoundError:
            existing = None
        if existing:
            if existing.etag != digest.hexdigest() or existing.size_bytes != source.stat().st_size:
                raise ObjectStorageError("An existing derived artifact cannot be replaced.")
            return

        async def chunks() -> AsyncIterator[bytes]:
            async with await open_file(source, "rb") as stream:
                while chunk := await stream.read(1024 * 1024):
                    yield chunk

        await self.receive(
            key,
            chunks(),
            expected_size=source.stat().st_size,
            expected_sha256=digest.hexdigest(),
            metadata={},
            content_type=content_type,
        )

    def close(self) -> None:
        pass
