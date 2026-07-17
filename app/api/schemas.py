"""API リクエスト/レスポンススキーマ（pydantic）。API設計書 §3。"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.domain.entities import MonthlyReport, SearchFilters
from app.domain.values import Category


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
