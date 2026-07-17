"""SQS コンシューマ（worker が使用）。ロングポーリング・可視性タイムアウトはキュー側設定。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import aioboto3

from app.infra.aws.client import AwsConfig


@dataclass(frozen=True)
class SqsMessage:
    receipt_handle: str
    body: str


class SqsConsumer:
    """SQS の受信・削除。3回失敗時の DLQ 隔離はキューの RedrivePolicy に委ねる（基本設計 §2.1）。"""

    def __init__(self, session: aioboto3.Session, config: AwsConfig, queue_url: str) -> None:
        self._session = session
        self._config = config
        self._queue_url = queue_url

    def _client(self) -> Any:  # aioboto3境界。ContextはAnyで受ける（規約 §2）
        c = self._config
        return self._session.client(
            "sqs",
            region_name=c.region,
            endpoint_url=c.endpoint_url,
            aws_access_key_id=c.access_key_id,
            aws_secret_access_key=c.secret_access_key,
        )

    async def receive(self, *, max_messages: int = 10, wait_seconds: int = 20) -> list[SqsMessage]:
        async with self._client() as sqs:
            response = await sqs.receive_message(
                QueueUrl=self._queue_url,
                MaxNumberOfMessages=max_messages,
                WaitTimeSeconds=wait_seconds,
            )
        return [
            SqsMessage(receipt_handle=m["ReceiptHandle"], body=m["Body"])
            for m in response.get("Messages", [])
        ]

    async def delete(self, receipt_handle: str) -> None:
        async with self._client() as sqs:
            await sqs.delete_message(QueueUrl=self._queue_url, ReceiptHandle=receipt_handle)
