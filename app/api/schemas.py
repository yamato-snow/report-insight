"""API リクエスト/レスポンススキーマ（pydantic）。API設計書 §3。"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.domain.entities import MonthlyReport, Property, Report, SearchFilters
from app.domain.values import Category, Urgency


class SearchFiltersIn(BaseModel):
    property_id: int | None = None
    category: Category | None = None
    from_: datetime | None = Field(default=None, alias="from")
    to: datetime | None = None

    def to_domain(self) -> SearchFilters:
        return SearchFilters(
            property_id=self.property_id,
            category=self.category,
            from_=self.from_,
            to=self.to,
        )


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    filters: SearchFiltersIn = Field(default_factory=SearchFiltersIn)


class PropertyOut(BaseModel):
    id: int
    branch_id: int
    name: str
    address: str | None = None

    @classmethod
    def from_domain(cls, prop: Property) -> PropertyOut:
        return cls(id=prop.id, branch_id=prop.branch_id, name=prop.name, address=prop.address)


class ReportAnalysisOut(BaseModel):
    category: str
    urgency: str
    action_required: bool
    normalized_summary: str
    confidence: float
    status: str


class ReportOut(BaseModel):
    """報告書の一覧/詳細表現（管理画面 API）。"""

    id: int
    property_id: int
    reported_at: datetime
    reporter_role: str
    raw_text: str
    analysis: ReportAnalysisOut | None = None

    @classmethod
    def from_domain(cls, report: Report) -> ReportOut:
        if report.id is None:
            raise ValueError("永続化されていない報告書は表現できません")
        analysis = None
        if report.analysis is not None:
            a = report.analysis
            analysis = ReportAnalysisOut(
                category=a.category.value,
                urgency=a.urgency.value,
                action_required=a.action_required,
                normalized_summary=a.normalized_summary,
                confidence=a.confidence,
                status=a.status.value,
            )
        return cls(
            id=report.id,
            property_id=report.property_id,
            reported_at=report.reported_at,
            reporter_role=report.reporter_role,
            raw_text=report.raw_text,
            analysis=analysis,
        )


class ReportListOut(BaseModel):
    """一覧レスポンス（カーソルページング）。"""

    items: list[ReportOut]
    next_cursor: int | None = None


class AnalysisOverrideIn(BaseModel):
    """人手による分類確定（PATCH /reports/{id}/analysis）。"""

    category: Category
    urgency: Urgency
    action_required: bool


class MonthlyReportCreate(BaseModel):
    """月次報告書の生成要求（API設計書 F-3: POST /monthly-reports）。"""

    property_id: int
    # 対象月。日付で受け取り、サービス側で月初へ正規化する（"2026-06-01" 等）。
    month: date


class MonthlyReportPatch(BaseModel):
    """月次報告書の保存/承認（PATCH /monthly-reports/{id}）。"""

    action: Literal["save", "approve"]
    body_markdown: str | None = None

    @model_validator(mode="after")
    def _require_body_for_save(self) -> MonthlyReportPatch:
        if self.action == "save" and self.body_markdown is None:
            raise ValueError("action=save には body_markdown が必要です")
        return self


class MonthlyReportOut(BaseModel):
    """月次報告書のレスポンス表現。"""

    id: int
    property_id: int
    month: date
    version: int
    status: str
    body_markdown: str
    approved_by: int | None = None
    approved_at: datetime | None = None

    @classmethod
    def from_domain(cls, report: MonthlyReport) -> MonthlyReportOut:
        if report.id is None:  # 永続化済みのみ返す（防御的）
            raise ValueError("永続化されていない月次報告書は表現できません")
        return cls(
            id=report.id,
            property_id=report.property_id,
            month=report.month,
            version=report.version,
            status=report.status.value,
            body_markdown=report.body_markdown,
            approved_by=report.approved_by,
            approved_at=report.approved_at,
        )
