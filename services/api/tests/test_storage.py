"""S3-compatible signed POST policy tests."""

from asyncio import run
from base64 import b64decode
from json import loads

from xxx_api.config import Settings
from xxx_api.storage import S3ObjectStorage


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
