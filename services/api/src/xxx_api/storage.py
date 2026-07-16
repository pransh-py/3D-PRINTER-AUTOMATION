"""Private S3-compatible object-storage adapter."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Protocol, cast

import boto3
from anyio import to_thread
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError

from xxx_api.config import Settings


class ObjectStorageError(Exception):
    """Private storage could not complete a required operation."""


class ObjectNotFoundError(ObjectStorageError):
    """The expected private object does not exist."""


@dataclass(frozen=True, slots=True)
class PresignedPost:
    """Short-lived browser upload material returned once."""

    url: str
    fields: dict[str, str]
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class ObjectMetadata:
    """Server-observed object metadata used before quarantine admission."""

    size_bytes: int
    content_type: str
    metadata: dict[str, str]
    etag: str | None


class ObjectStorage(Protocol):
    """Bounded private-object operations used by quote intake."""

    async def create_upload(
        self,
        *,
        key: str,
        size_bytes: int,
        content_type: str,
        metadata: dict[str, str],
    ) -> PresignedPost: ...

    async def head(self, key: str) -> ObjectMetadata: ...

    async def delete(self, key: str) -> None: ...

    async def check_ready(self) -> None: ...


class S3ObjectStorage:
    """S3 SigV4 implementation with exact POST-policy constraints."""

    def __init__(self, settings: Settings) -> None:
        self._bucket = settings.storage_bucket
        self._ttl_seconds = settings.upload_url_ttl_seconds
        self._client = boto3.client(
            "s3",
            endpoint_url=str(settings.storage_endpoint_url).rstrip("/"),
            region_name=settings.storage_region,
            aws_access_key_id=settings.storage_access_key.get_secret_value(),
            aws_secret_access_key=settings.storage_secret_key.get_secret_value(),
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    async def create_upload(
        self,
        *,
        key: str,
        size_bytes: int,
        content_type: str,
        metadata: dict[str, str],
    ) -> PresignedPost:
        fields = {
            "Content-Type": content_type,
            "success_action_status": "204",
            **{f"x-amz-meta-{name}": value for name, value in metadata.items()},
        }
        conditions: list[dict[str, str] | list[object]] = [
            {"Content-Type": content_type},
            {"success_action_status": "204"},
            ["content-length-range", size_bytes, size_bytes],
            *({f"x-amz-meta-{name}": value} for name, value in metadata.items()),
        ]
        try:
            result = await to_thread.run_sync(
                partial(
                    self._client.generate_presigned_post,
                    Bucket=self._bucket,
                    Key=key,
                    Fields=fields,
                    Conditions=conditions,
                    ExpiresIn=self._ttl_seconds,
                )
            )
        except (BotoCoreError, ClientError) as error:
            raise ObjectStorageError("could not issue private upload") from error
        result_fields = cast(dict[str, str], result["fields"])
        return PresignedPost(
            url=cast(str, result["url"]),
            fields=result_fields,
            expires_at=datetime.now(UTC) + timedelta(seconds=self._ttl_seconds),
        )

    async def head(self, key: str) -> ObjectMetadata:
        try:
            result = await to_thread.run_sync(
                partial(self._client.head_object, Bucket=self._bucket, Key=key)
            )
        except ClientError as error:
            code = str(error.response.get("Error", {}).get("Code", ""))
            if code in {"404", "NoSuchKey", "NotFound"}:
                raise ObjectNotFoundError("private object not found") from error
            raise ObjectStorageError("could not inspect private object") from error
        except BotoCoreError as error:
            raise ObjectStorageError("could not inspect private object") from error
        return ObjectMetadata(
            size_bytes=cast(int, result["ContentLength"]),
            content_type=cast(str, result.get("ContentType", "application/octet-stream")),
            metadata=cast(dict[str, str], result.get("Metadata", {})),
            etag=cast(str | None, result.get("ETag")),
        )

    async def delete(self, key: str) -> None:
        try:
            await to_thread.run_sync(
                partial(self._client.delete_object, Bucket=self._bucket, Key=key)
            )
        except (BotoCoreError, ClientError) as error:
            raise ObjectStorageError("could not delete private object") from error

    async def check_ready(self) -> None:
        """Confirm the configured private bucket is reachable."""
        try:
            await to_thread.run_sync(partial(self._client.head_bucket, Bucket=self._bucket))
        except (BotoCoreError, ClientError) as error:
            raise ObjectStorageError("private object storage is not ready") from error

    def close(self) -> None:
        """Release the SDK HTTP connection pool."""
        self._client.close()
