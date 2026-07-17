"""API リクエスト/レスポンススキーマ（pydantic）。API設計書 §3。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.entities import SearchFilters
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
