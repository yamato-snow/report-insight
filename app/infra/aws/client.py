"""aioboto3 セッションのファクトリ。エンドポイント差分のみで本番/LocalStackを切替。"""

from __future__ import annotations

from dataclasses import dataclass

import aioboto3


@dataclass(frozen=True)
class AwsConfig:
    region: str
    endpoint_url: str | None
    access_key_id: str
    secret_access_key: str


def make_session() -> aioboto3.Session:
    return aioboto3.Session()
