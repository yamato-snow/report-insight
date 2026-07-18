"""F-4 管理画面（Jinja2 + HTMX。SPA にしない。基本設計 §1 / 05 §7）。

サーバサイドレンダリングし、部分更新のみ HTMX で差し替える。LLM 由来テキスト
（normalized_summary / raw_text）は Jinja2 の自動エスケープでサニタイズする（XSS 対策 §7）。
認可は AdminService が permitted_property_ids で強制するため、画面には権限内データのみ載る。
SSO は抽象化済みのため、dev では利用者を uid クエリで指定する（本番はセッションに置換）。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.api.deps import ContainerDep
from app.domain.entities import ReportListFilters, User
from app.domain.errors import NotFoundError
from app.domain.values import AnalysisStatus, Category, Urgency

router = APIRouter(tags=["admin-ui"])

_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


async def _resolve_user(container: ContainerDep, uid: int) -> User:
    async with container.session_factory() as session:
        try:
            return await container.user_repository(session).get(uid)
        except NotFoundError as exc:
            raise HTTPException(status_code=401, detail="不明な利用者です") from exc


@router.get("/admin", response_class=HTMLResponse)
async def admin_home(
    request: Request,
    container: ContainerDep,
    uid: int = Query(..., description="dev用の利用者ID（SSO抽象点）"),
) -> HTMLResponse:
    """管理画面トップ（フィルタ + 一覧 + 未分類キュータブ）。"""
    user = await _resolve_user(container, uid)
    async with container.session_factory() as session:
        props = await container.admin_service(session).list_properties(user)
    return _TEMPLATES.TemplateResponse(
        request,
        "admin.html",
        {
            "user": user,
            "uid": uid,
            "properties": props,
            "categories": list(Category),
            "urgencies": list(Urgency),
            "statuses": list(AnalysisStatus),
        },
    )


@router.get("/admin/reports", response_class=HTMLResponse)
async def admin_reports_partial(
    request: Request,
    container: ContainerDep,
    uid: int = Query(...),
    property_id: int | None = None,
    category: Category | None = None,
    urgency: Urgency | None = None,
    status: AnalysisStatus | None = None,
    queue: bool = False,
) -> HTMLResponse:
    """一覧/未分類キューの HTMX 部分テンプレート（テーブル行）。"""
    user = await _resolve_user(container, uid)
    async with container.session_factory() as session:
        service = container.admin_service(session)
        if queue:
            reports = await service.review_queue(user, None, 50)
        else:
            filters = ReportListFilters(
                property_id=property_id, category=category, urgency=urgency, status=status
            )
            reports = await service.list_reports(user, filters, None, 50)
    return _TEMPLATES.TemplateResponse(
        request,
        "_reports_table.html",
        {"reports": reports, "uid": uid},
    )
