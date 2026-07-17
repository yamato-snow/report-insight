"""ポート定義（Protocol）。外部依存の隔離点（アーキテクチャ規約 §4）。

戻り値は domain の型のみ。プロバイダ固有の型をポートから漏らさない。
infra/ の実装と tests の Fake が同じ Protocol を満たす。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Protocol, runtime_checkable

from app.domain.entities import (
    ClassificationEnvelope,
    LLMCallMeta,
    MaskingResult,
    Report,
    ReportAnalysis,
    SearchFilters,
    SearchHit,
    User,
)
from app.domain.values import Category, Urgency


@runtime_checkable
class AnswerStream(Protocol):
    """RAG回答のトークンストリーム。消費後に usage で使用量を取得できる。"""

    def __aiter__(self) -> AsyncIterator[str]: ...

    @property
    def usage(self) -> LLMCallMeta: ...


class LLMClient(Protocol):
    """LLM抽象（ADR-003 のモデル切替・Fake差し替えの境界）。"""

    async def classify_report(self, masked_text: str) -> ClassificationEnvelope:
        """報告書を分類・構造化する（Structured Output 強制。LLM設計書 §2）。"""
        ...

    def stream_answer(self, query: str, sources: Sequence[SearchHit]) -> AnswerStream:
        """検索結果を根拠に回答を生成しストリーミングする（引用は [report:ID] 形式）。"""
        ...


class EmbeddingClient(Protocol):
    """埋め込み抽象（fastembed 実装。将来 Voyage 等へ切替可能。ADR-001）。"""

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


class PIIMaskerPort(Protocol):
    """PIIマスキング（LLM設計書 §3）。正規表現＋形態素解析で個人名・電話番号等を伏せる。"""

    async def mask(self, text: str) -> MaskingResult: ...


class ObjectStoragePort(Protocol):
    """S3 抽象。エンドポイントは env で LocalStack に切替（アーキテクチャ規約 §3）。"""

    async def get_object(self, key: str) -> bytes: ...

    async def put_object(self, key: str, body: bytes) -> None: ...


class NotificationPort(Protocol):
    """緊急通知（Slack Webhook）。LLM出力の自動アクションは通知のみ（LLM設計書 §7）。"""

    async def notify_urgent(self, report: Report, analysis: ReportAnalysis) -> None: ...


class ReportRepository(Protocol):
    """報告書・構造化結果の永続化。認可は permitted_property_ids で強制（DB設計書 §2）。"""

    async def upsert_ingested(
        self,
        report: Report,
        analysis: ReportAnalysis,
        chunks: Sequence[tuple[str, list[float]]],
    ) -> int | None:
        """source_key 冪等UPSERT。新規なら report_id、重複(既存)なら None を返す。"""
        ...

    async def get(self, report_id: int, permitted_property_ids: Sequence[int]) -> Report:
        """権限内の報告書を1件取得。範囲外/不在は NotFound/PermissionDenied。"""
        ...

    async def update_analysis(
        self,
        report_id: int,
        category: Category,
        urgency: Urgency,
        action_required: bool,
        permitted_property_ids: Sequence[int],
    ) -> ReportAnalysis:
        """人間による分類修正・確定（status=human_verified）。"""
        ...


class SearchRepository(Protocol):
    """RAG検索・認可・引用検証（DB設計書 §2 のハイブリッド検索SQL）。"""

    async def permitted_property_ids(self, user: User) -> list[int]:
        """利用者がアクセス可能な物件ID一覧（qa は全件）。"""
        ...

    async def hybrid_search(
        self,
        query_vec: Sequence[float],
        filters: SearchFilters,
        permitted_property_ids: Sequence[int],
        limit: int,
    ) -> list[SearchHit]:
        """ベクトル類似＋メタデータフィルタ。認可は必ずSQLに含める。"""
        ...

    async def existing_report_ids(
        self, report_ids: Sequence[int], permitted_property_ids: Sequence[int]
    ) -> set[int]:
        """引用の実在検証（権限内に実在するIDのみ返す。LLM設計書 §2）。"""
        ...
