"""F-4-3 月次報告書の画面（生成 → 編集 → 承認 → PDF）。

API（/api/v1/monthly-reports）は実装済みで、この層はその画面提供のみを担う。
状態機械（generating→draft→approved）と認可は MonthlyService が強制するため、
テンプレート側は表示の出し分けだけを行い、権限判断を持たない（基本設計 §8）。
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, BackgroundTasks, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.api.deps import ContainerDep, PdfRendererDep
from app.api.labels import template_context
from app.api.routers._ui_shared import TEMPLATES, resolve_user
from app.core.db import unit_of_work
from app.core.di import Container
from app.core.logging import get_logger
from app.domain.entities import User
from app.domain.errors import InvalidStateError
from app.domain.values import MonthlyStatus

router = APIRouter(tags=["monthly-ui"])
logger = get_logger(__name__)

# 生成対象として選べる月数（当月から遡る）
MONTH_CHOICES = 6


async def _common(container: ContainerDep, uid: int) -> dict[str, object]:
    user = await resolve_user(container, uid)
    async with container.session_factory() as session:
        props = await container.admin_service(session).list_properties(user)
        users = await container.user_repository(session).list_all()
    return {
        "user": user,
        "uid": uid,
        "users": users,
        "properties": props,
        "property_names": {p.id: p.name for p in props},
    }


def _month_options(today: date) -> list[date]:
    months: list[date] = []
    y, m = today.year, today.month
    for _ in range(MONTH_CHOICES):
        months.append(date(y, m, 1))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return months


async def _run_generation(container: Container, monthly_id: int) -> None:
    """バックグラウンド生成（独立した UoW）。例外は failed 転落済みなのでログのみ。"""
    try:
        async with unit_of_work(container.session_factory) as session:
            await container.monthly_service(session).run_generation(monthly_id)
    except Exception:
        logger.exception("monthly_ui.background_failed", monthly_id=monthly_id)


@router.get("/monthly", response_class=HTMLResponse)
async def monthly_home(
    request: Request,
    container: ContainerDep,
    uid: int = Query(..., description="dev用の利用者ID（SSO抽象点）"),
) -> HTMLResponse:
    """月次報告書の一覧と生成フォーム。"""
    ctx = await _common(container, uid)
    user: User = ctx["user"]  # type: ignore[assignment]
    async with container.session_factory() as session:
        reports = await container.monthly_service(session).list_for_user(user)
    return TEMPLATES.TemplateResponse(
        request,
        "monthly_list.html",
        {
            **ctx,
            "reports": reports,
            "months": _month_options(date.today()),
            "active_nav": "monthly",
            **template_context(),
        },
    )


@router.post("/monthly")
async def monthly_generate(
    container: ContainerDep,
    background: BackgroundTasks,
    uid: int = Query(...),
    property_id: int = Form(...),
    month: str = Form(...),
) -> RedirectResponse:
    """ドラフト生成を依頼し、編集画面へ送る（生成中はポーリング表示になる）。"""
    user = await resolve_user(container, uid)
    async with unit_of_work(container.session_factory) as session:
        report = await container.monthly_service(session).request_generation(
            user, property_id, date.fromisoformat(month)
        )
    report_id = report.id
    if report_id is None:  # 直後に採番済みのため通常起きない（型の絞り込み用）
        raise InvalidStateError("月次報告書IDの採番に失敗しました")
    background.add_task(_run_generation, container, report_id)
    return RedirectResponse(f"/monthly/{report_id}?uid={uid}", status_code=303)


@router.get("/monthly/{monthly_id}", response_class=HTMLResponse)
async def monthly_detail(
    request: Request,
    container: ContainerDep,
    monthly_id: int,
    uid: int = Query(...),
    saved: bool = False,
) -> HTMLResponse:
    """編集・承認画面。generating の間は自動で再読み込みして完成を待つ。"""
    ctx = await _common(container, uid)
    user: User = ctx["user"]  # type: ignore[assignment]
    async with container.session_factory() as session:
        report = await container.monthly_service(session).get(user, monthly_id)
    return TEMPLATES.TemplateResponse(
        request,
        "monthly_detail.html",
        {
            **ctx,
            "report": report,
            "editable": report.status is MonthlyStatus.DRAFT and not user.is_qa,
            "saved": saved,
            "active_nav": "monthly",
            **template_context(),
        },
    )


@router.post("/monthly/{monthly_id}/save")
async def monthly_save(
    container: ContainerDep,
    monthly_id: int,
    uid: int = Query(...),
    body_markdown: str = Form(...),
) -> RedirectResponse:
    user = await resolve_user(container, uid)
    async with unit_of_work(container.session_factory) as session:
        await container.monthly_service(session).save_draft(user, monthly_id, body_markdown)
    return RedirectResponse(f"/monthly/{monthly_id}?uid={uid}&saved=true", status_code=303)


@router.post("/monthly/{monthly_id}/approve")
async def monthly_approve(
    container: ContainerDep,
    monthly_id: int,
    uid: int = Query(...),
    body_markdown: str = Form(...),
) -> RedirectResponse:
    """編集中の内容を保存してから承認する（画面の見た目と確定内容を一致させる）。"""
    user = await resolve_user(container, uid)
    async with unit_of_work(container.session_factory) as session:
        service = container.monthly_service(session)
        await service.save_draft(user, monthly_id, body_markdown)
        await service.approve(user, monthly_id)
    return RedirectResponse(f"/monthly/{monthly_id}?uid={uid}", status_code=303)


@router.get("/monthly/{monthly_id}/pdf")
async def monthly_pdf(
    container: ContainerDep,
    renderer: PdfRendererDep,
    monthly_id: int,
    uid: int = Query(...),
) -> Response:
    """確定版（および draft）の PDF ダウンロード。描画は API 側と同じレンダラを使う。"""
    user = await resolve_user(container, uid)
    async with container.session_factory() as session:
        report = await container.monthly_service(session).get(user, monthly_id)
    if report.status not in (MonthlyStatus.DRAFT, MonthlyStatus.APPROVED):
        raise InvalidStateError(f"status={report.status} の月次報告書は PDF 出力できません")

    title = f"{report.month.year}年{report.month.month}月 月次報告 v{report.version}"
    pdf = await renderer.render(title=title, body_markdown=report.body_markdown)
    filename = f"monthly-{report.property_id}-{report.month:%Y%m}-v{report.version}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
