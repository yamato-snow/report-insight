"""F-4 管理画面ユースケース: 一覧・フィルタ・未分類キュー・分類上書き（基本設計 §3 / 05 §7）。

認可は permitted_property_ids で強制し、他支店の参照は 403。分類上書きは human_verified に
確定させ、監査ログに記録する（09 §6）。SSR/HTMX の描画は API 層が担い、ここは判断のみ持つ。
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.domain.entities import Property, Report, ReportAnalysis, ReportListFilters, User
from app.domain.values import AuditAction, Category, Urgency
from app.services.ports import (
    AuditPort,
    PermissionResolver,
    PropertyLister,
    ReportRepository,
)

logger = get_logger(__name__)

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


class AdminService:
    """報告書の閲覧・確定を束ねる管理ユースケース。"""

    def __init__(
        self,
        *,
        reports: ReportRepository,
        properties: PropertyLister,
        audit: AuditPort,
        permissions: PermissionResolver,
    ) -> None:
        self._reports = reports
        self._properties = properties
        self._audit = audit
        self._permissions = permissions

    async def list_reports(
        self, user: User, filters: ReportListFilters, cursor: int | None, limit: int
    ) -> list[Report]:
        permitted = await self._permissions.permitted_property_ids(user)
        return await self._reports.list_reports(filters, permitted, cursor, _clamp(limit))

    async def review_queue(self, user: User, cursor: int | None, limit: int) -> list[Report]:
        permitted = await self._permissions.permitted_property_ids(user)
        return await self._reports.review_queue(permitted, cursor, _clamp(limit))

    async def get_report(self, user: User, report_id: int) -> Report:
        permitted = await self._permissions.permitted_property_ids(user)
        # 範囲外は repo が PermissionDenied を投げる（→403）
        return await self._reports.get(report_id, permitted)

    async def override_analysis(
        self,
        user: User,
        report_id: int,
        category: Category,
        urgency: Urgency,
        action_required: bool,
    ) -> ReportAnalysis:
        permitted = await self._permissions.permitted_property_ids(user)
        analysis = await self._reports.update_analysis(
            report_id, category, urgency, action_required, permitted
        )
        await self._audit.record(
            user_id=user.id,
            action=AuditAction.OVERRIDE_ANALYSIS.value,
            payload={
                "report_id": report_id,
                "category": category.value,
                "urgency": urgency.value,
                "action_required": action_required,
            },
        )
        logger.info("admin.analysis_overridden", report_id=report_id, user_id=user.id)
        return analysis

    async def list_properties(self, user: User) -> list[Property]:
        return await self._properties.list_properties(user)


def _clamp(limit: int) -> int:
    if limit < 1:
        return DEFAULT_PAGE_SIZE
    return min(limit, MAX_PAGE_SIZE)
