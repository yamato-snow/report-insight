"""ドメイン例外（アーキテクチャ規約 §3）。services はこれ以外を投げない（規約 §4）。"""

from __future__ import annotations


class DomainError(Exception):
    """ドメイン例外の基底。"""


class NotFoundError(DomainError):
    """リソースが存在しない（→ HTTP 404）。"""


class PermissionDeniedError(DomainError):
    """権限外アクセス（他支店の物件など。→ HTTP 403）。"""


class InvalidStateError(DomainError):
    """状態起因の拒否（未処理報告書への操作・approved後の編集など。→ HTTP 422）。"""


class RetryableError(DomainError):
    """リトライ可能な一時障害（レートリミット・一時的なAPI障害）。

    worker はこれを SQS 再配信に委ね、非リトライ例外は即 DLQ に倒す（規約 §4）。
    """
