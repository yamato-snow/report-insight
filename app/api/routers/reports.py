"""F-4 管理API: 報告書の一覧・詳細・分類確定・未分類キュー・物件一覧（API設計書 F-4）。

認可は AdminService/リポジトリで permitted_property_ids により強制する。他支店の
GET /reports/{id} は 403（SqlReportRepository.get が PermissionDenied を送出）。
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import ContainerDep, CurrentUser
from app.api.schemas import (
    AnalysisOverrideIn,
    PropertyOut,
    ReportAnalysisOut,
    ReportListOut,
    ReportOut,
)
from app.core.db import unit_of_work
from app.core.logging import get_logger
from app.domain.entities import ReportListFilters
from app.domain.values import AnalysisStatus, Category, Urgency

logger = get_logger(__name__)

router = APIRouter(tags=["admin"])


def _to_list_out(reports: list[ReportOut], limit: int) -> ReportListOut:
    next_cursor = reports[-1].id if len(reports) == limit else None
    return ReportListOut(items=reports, next_cursor=next_cursor)


@router.get("/reports/review-queue")
async def review_queue(
    user: CurrentUser,
    container: ContainerDep,
    cursor: int | None = None,
    limit: int = 20,
) -> ReportListOut:
    """未分類（needs_review）キュー。"""
    async with container.session_factory() as session:
        reports = await container.admin_service(session).review_queue(user, cursor, limit)
    items = [ReportOut.from_domain(r) for r in reports]
    return _to_list_out(items, limit)


@router.get("/reports")
async def list_reports(
    user: CurrentUser,
    container: ContainerDep,
    property_id: int | None = None,
    category: Category | None = None,
    urgency: Urgency | None = None,
    status: AnalysisStatus | None = None,
    cursor: int | None = None,
    limit: int = 20,
) -> ReportListOut:
    """権限内の報告書一覧（フィルタ・カーソルページング）。"""
    filters = ReportListFilters(
        property_id=property_id, category=category, urgency=urgency, status=status
    )
    async with container.session_factory() as session:
        reports = await container.admin_service(session).list_reports(user, filters, cursor, limit)
    items = [ReportOut.from_domain(r) for r in reports]
    return _to_list_out(items, limit)


@router.get("/reports/{report_id}")
async def get_report(
    report_id: int,
    user: CurrentUser,
    container: ContainerDep,
) -> ReportOut:
    """1件詳細。他支店は 403。"""
    async with container.session_factory() as session:
        report = await container.admin_service(session).get_report(user, report_id)
    return ReportOut.from_domain(report)


@router.patch("/reports/{report_id}/analysis")
async def override_analysis(
    report_id: int,
    body: AnalysisOverrideIn,
    user: CurrentUser,
    container: ContainerDep,
) -> ReportAnalysisOut:
    """人手による分類確定（→human_verified）。監査ログに記録。"""
    async with unit_of_work(container.session_factory) as session:
        analysis = await container.admin_service(session).override_analysis(
            user, report_id, body.category, body.urgency, body.action_required
        )
    return ReportAnalysisOut(
        category=analysis.category.value,
        urgency=analysis.urgency.value,
        action_required=analysis.action_required,
        normalized_summary=analysis.normalized_summary,
        confidence=analysis.confidence,
        status=analysis.status.value,
    )


@router.get("/properties")
async def list_properties(
    user: CurrentUser,
    container: ContainerDep,
) -> list[PropertyOut]:
    """権限内の物件一覧（フィルタ選択肢用）。"""
    async with container.session_factory() as session:
        props = await container.admin_service(session).list_properties(user)
    return [PropertyOut.from_domain(p) for p in props]
