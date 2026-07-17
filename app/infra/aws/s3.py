"""S3 ObjectStoragePort 実装（aioboto3）。"""

from __future__ import annotations

from typing import Any

import aioboto3

from app.infra.aws.client import AwsConfig


class S3ObjectStorage:
    """ObjectStoragePort の S3 実装。"""

    def __init__(self, session: aioboto3.Session, config: AwsConfig, bucket: str) -> None:
        self._session = session
        self._config = config
        self._bucket = bucket

    def _client(self) -> Any:  # aioboto3境界。ContextはAnyで受ける（規約 §2）
        c = self._config
        return self._session.client(
            "s3",
            region_name=c.region,
            endpoint_url=c.endpoint_url,
            aws_access_key_id=c.access_key_id,
            aws_secret_access_key=c.secret_access_key,
        )

    async def get_object(self, key: str) -> bytes:
        async with self._client() as s3:
            response = await s3.get_object(Bucket=self._bucket, Key=key)
            async with response["Body"] as body:
                data: bytes = await body.read()
                return data

    async def put_object(self, key: str, body: bytes) -> None:
        async with self._client() as s3:
            await s3.put_object(Bucket=self._bucket, Key=key, Body=body)
