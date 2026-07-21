"""ドメインエンティティ・値（pydantic）。ポートの戻り値はここで定義した型のみ（規約 §4）。"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.values import (
    AnalysisStatus,
    AuditAction,
    Category,
    MonthlyStatus,
    Role,
    Urgency,
)


class Branch(BaseModel):
    id: int
    name: str


class User(BaseModel):
    """利用者。branch_id が None なら品質管理部（全支店アクセス可）。"""

    id: int
    email: str
    role: Role
    branch_id: int | None = None

    @property
    def is_qa(self) -> bool:
        return self.role is Role.QA


class Property(BaseModel):
    id: int
    branch_id: int
    name: str
    address: str | None = None


class ClassificationResult(BaseModel):
    """LLM 分類・構造化の結果（LLMClient.classify_report の戻り値）。"""

    model_config = ConfigDict(frozen=True)

    category: Category
    urgency: Urgency
    action_required: bool
    normalized_summary: str
    confidence: float = Field(ge=0.0, le=1.0)


class ReportAnalysis(BaseModel):
    """構造化結果（DB設計書 04: report_analyses）。"""

    report_id: int
    category: Category
    urgency: Urgency
    action_required: bool
    normalized_summary: str
    confidence: float
    status: AnalysisStatus
    model_id: str
    prompt_version: str
    input_tokens: int = 0
    output_tokens: int = 0
    analyzed_at: datetime | None = None


class Report(BaseModel):
    """報告書本体（DB設計書 04: reports）。"""

    id: int | None = None
    property_id: int
    source_key: str
    reported_at: datetime
    reporter_role: str
    raw_text: str
    photo_meta: dict[str, object] = Field(default_factory=dict)
    created_at: datetime | None = None
    analysis: ReportAnalysis | None = None


class IngestMessage(BaseModel):
    """S3 に投入された報告書 JSON（取込パイプラインの入力。基本設計 §2.1）。"""

    source_key: str
    property_id: int
    reported_at: datetime
    reporter_role: str
    raw_text: str
    photo_meta: dict[str, object] = Field(default_factory=dict)


class SearchHit(BaseModel):
    """ハイブリッド検索の1件（DB設計書 §2 のクエリ結果）。"""

    report_id: int
    property_id: int
    content: str
    summary: str
    reported_at: datetime
    similarity: float


class LLMCallMeta(BaseModel):
    """LLM呼び出しの監査・コスト用メタ（LLM設計書 §5）。"""

    model_id: str
    prompt_version: str
    input_tokens: int = 0
    output_tokens: int = 0


class ClassificationEnvelope(BaseModel):
    """分類結果＋呼び出しメタ（LLMClient.classify_report の戻り値）。"""

    result: ClassificationResult
    meta: LLMCallMeta


class SearchFilters(BaseModel):
    """検索の絞り込み条件（API設計書 POST /search の filters）。"""

    property_id: int | None = None
    category: Category | None = None
    from_: datetime | None = None
    to: datetime | None = None


class ReportListFilters(BaseModel):
    """管理画面の一覧フィルタ（API設計書 F-4: GET /reports）。"""

    property_id: int | None = None
    category: Category | None = None
    urgency: Urgency | None = None
    status: AnalysisStatus | None = None


class MaskingResult(BaseModel):
    """PIIマスキング結果。mapping は復元用でDB内のみ保持（LLM設計書 §3）。"""

    masked_text: str
    mapping: dict[str, str] = Field(default_factory=dict)


class MonthlyReport(BaseModel):
    """月次報告書（DB設計書 04: monthly_reports）。"""

    id: int | None = None
    property_id: int
    month: date
    version: int
    body_markdown: str
    status: MonthlyStatus
    approved_by: int | None = None
    approved_at: datetime | None = None


class MonthlyStats(BaseModel):
    """月次の件数サマリ（SQLで確定計算。数値ハルシネーション防止のため LLM には渡さず、
    本文の数表はこの値から決定的に生成する。基本設計 §2.3 / LLM設計書 §2）。"""

    model_config = ConfigDict(frozen=True)

    property_id: int
    month: date
    total: int
    by_category: dict[Category, int] = Field(default_factory=dict)
    by_urgency: dict[Urgency, int] = Field(default_factory=dict)
    action_required: int = 0


class AuditEntry(BaseModel):
    """監査ログ1件（DB設計書 04: audit_logs）。追記専用のため読み取り専用の型として扱う。"""

    id: int
    actor_email: str
    action: AuditAction
    payload: dict[str, object] = Field(default_factory=dict)
    created_at: datetime


class MonthlyNarration(BaseModel):
    """月次報告書の所見（LLM が数値サマリを文章化した散文＋呼び出しメタ）。"""

    body: str
    meta: LLMCallMeta
