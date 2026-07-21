"""ポート定義（Protocol）。外部依存の隔離点（アーキテクチャ規約 §4）。

戻り値は domain の型のみ。プロバイダ固有の型をポートから漏らさない。
infra/ の実装と tests の Fake が同じ Protocol を満たす。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from datetime import date, datetime
from typing import Protocol, runtime_checkable

from app.domain.entities import (
    AuditEntry,
    ClassificationEnvelope,
    LLMCallMeta,
    MaskingResult,
    MonthlyNarration,
    MonthlyReport,
    MonthlyStats,
    Property,
    Report,
    ReportAnalysis,
    ReportListFilters,
    SearchFilters,
    SearchHit,
    User,
)
from app.domain.values import Category, MonthlyStatus, Urgency


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

    async def narrate_monthly(self, *, property_name: str, stats: MonthlyStats) -> MonthlyNarration:
        """確定済みの件数サマリを散文化する（数値は stats のみが正。捏造禁止。基本設計 §2.3）。"""
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


class MetricsPort(Protocol):
    """カスタムメトリクス送出（観測層。運用ハンドブック S8 の4指標）。

    実装は CloudWatch EMF（stdout JSON）で送る（infra/observability）。domain/services は
    この Protocol だけを知り、EMF/CloudWatch を直接知らない（アーキテクチャ規約 §4）。
    送出は fire-and-forget（監視の失敗が業務処理を止めてはならない）ので同期・戻り値なし。
    """

    def incr(self, name: str, value: int = 1, **dimensions: str) -> None:
        """カウンタ系メトリクスを value だけ加算する（既定 1）。"""
        ...

    def emit_tokens(self, *, input_tokens: int, output_tokens: int, **dimensions: str) -> None:
        """LLM トークン消費（input/output）を送出する（コスト先行指標。runbook §5）。"""
        ...


class NullMetrics:
    """何もしない MetricsPort（Null Object）。

    本番は DI が EMF 実装を、テストは Fake を明示注入する。これは観測が不要な
    手動構築（評価ハーネス等）向けの既定値で、送出しても外部I/Oを起こさない。
    """

    def incr(self, name: str, value: int = 1, **dimensions: str) -> None:
        return None

    def emit_tokens(self, *, input_tokens: int, output_tokens: int, **dimensions: str) -> None:
        return None


NULL_METRICS: MetricsPort = NullMetrics()


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

    async def list_reports(
        self,
        filters: ReportListFilters,
        permitted_property_ids: Sequence[int],
        cursor: int | None,
        limit: int,
    ) -> list[Report]:
        """権限内の報告書一覧（id 降順・カーソルページング）。認可はSQLで強制。"""
        ...

    async def review_queue(
        self,
        permitted_property_ids: Sequence[int],
        cursor: int | None,
        limit: int,
    ) -> list[Report]:
        """未分類（needs_review）キュー（id 降順・カーソルページング）。"""
        ...


class PropertyLister(Protocol):
    """権限内の物件一覧（管理画面のフィルタ選択肢。基本設計 §3）。"""

    async def list_properties(self, user: User) -> list[Property]:
        """qa は全件、支店管理者は自支店のみ。"""
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


class PermissionResolver(Protocol):
    """利用者の物件アクセス範囲を解決する（認可の単一ソース。基本設計 §3）。"""

    async def permitted_property_ids(self, user: User) -> list[int]:
        """利用者がアクセス可能な物件ID一覧（qa は全件）。"""
        ...


class MonthlyReportRepository(Protocol):
    """月次報告書の永続化・状態遷移・件数集計（F-3。DB設計書 04）。

    認可は permitted_property_ids で強制する。状態遷移（generating→draft→approved）の
    ビジネス判断は services 側に置き、ここは行の読み書きに徹する。
    """

    async def compute_stats(self, property_id: int, month: date) -> MonthlyStats:
        """対象物件・対象月の報告書を SQL で集計する（分類別・緊急度別の確定値）。"""
        ...

    async def property_name(self, property_id: int) -> str:
        """物件名（本文タイトル・所見プロンプト用）。不在は NotFound。"""
        ...

    async def create_generating(
        self, property_id: int, month: date, permitted_property_ids: Sequence[int]
    ) -> MonthlyReport:
        """新規世代を generating で作成（同一物件×月は version+1）。範囲外は PermissionDenied。"""
        ...

    async def get(self, monthly_id: int, permitted_property_ids: Sequence[int]) -> MonthlyReport:
        """権限内の月次報告書を1件取得。不在/範囲外は NotFound/PermissionDenied。"""
        ...

    async def list_reports(
        self, permitted_property_ids: Sequence[int], limit: int
    ) -> list[MonthlyReport]:
        """権限内の月次報告書を新しい順に返す（画面の一覧用）。"""
        ...

    async def get_internal(self, monthly_id: int) -> MonthlyReport:
        """生成ジョブ（システム実行・認可なし）用の取得。API から直接は使わない。"""
        ...

    async def set_body(
        self, monthly_id: int, body_markdown: str, status: MonthlyStatus
    ) -> MonthlyReport:
        """本文と状態を更新（generating→draft、または draft の保存・failed 転落）。"""
        ...

    async def approve(
        self, monthly_id: int, approver_id: int, approved_at: datetime
    ) -> MonthlyReport:
        """承認（→approved・承認者/時刻を記録）。呼び出し側で状態を検証済みの前提。"""
        ...


class AuditPort(Protocol):
    """監査ログの記録（検索・承認・分類上書き。DB設計書 04 / 09 §6）。"""

    async def record(self, *, user_id: int, action: str, payload: dict[str, object]) -> None: ...

    async def list_recent(self, limit: int) -> list[AuditEntry]:
        """新しい順の監査ログ（受入条件の確認用の参照系）。"""
        ...


class PdfRendererPort(Protocol):
    """Markdown 本文を PDF 化する（F-3。ネイティブ依存はコンテナ内に閉じる）。"""

    async def render(self, *, title: str, body_markdown: str) -> bytes: ...
