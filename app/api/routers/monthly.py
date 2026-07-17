"""F-3 月次報告書 API（生成=202→ポーリング、保存/承認、PDF）。API設計書 F-3。

生成は「API 内バックグラウンドタスク」で実行する（P0 の worker とは別系統。引き継ぎ計画 §4.1）。
POST は generating 行を作って即 202 を返し、実処理は BackgroundTasks が別 UoW で行う。
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import JSONResponse, Response

from app.api.deps import ContainerDep, CurrentUser, PdfRendererDep
from app.api.schemas import MonthlyReportCreate, MonthlyReportOut, MonthlyReportPatch
from app.core.db import unit_of_work
from app.core.di import Container
from app.core.logging import get_logger
from app.domain.errors import InvalidStateError
from app.domain.values import MonthlyStatus

logger = get_logger(__name__)

router = APIRouter(prefix="/monthly-reports", tags=["monthly-reports"])


async def _run_generation(container: Container, monthly_id: int) -> None:
    """バックグラウンド生成（独立した UoW）。例外は握って failed 転落済みなのでログのみ。"""
    try:
        async with unit_of_work(container.session_factory) as session:
            await container.monthly_service(session).run_generation(monthly_id)
    except Exception:
        logger.exception("monthly.background_failed", monthly_id=monthly_id)


@router.post("")
async def create_monthly_report(
    body: MonthlyReportCreate,
    user: CurrentUser,
    container: ContainerDep,
    background: BackgroundTasks,
) -> JSONResponse:
    """生成ジョブを登録し 202 を返す（本文は status=generating）。"""
    async with unit_of_work(container.session_factory) as session:
        report = await container.monthly_service(session).request_generation(
            user, body.property_id, body.month
        )
    report_id = report.id
    if report_id is None:  # 直後に採番済みのため通常起きない（型の絞り込み用）
        raise InvalidStateError("月次報告書IDの採番に失敗しました")
    background.add_task(_run_generation, container, report_id)
    return JSONResponse(
        status_code=202,
        content=MonthlyReportOut.from_domain(report).model_dump(mode="json"),
    )


@router.get("/{monthly_id}")
async def get_monthly_report(
    monthly_id: int,
    user: CurrentUser,
    container: ContainerDep,
) -> JSONResponse:
    """1件取得。生成中は 202、それ以外は 200（API設計書 F-3: ポーリング）。"""
    async with container.session_factory() as session:
        report = await container.monthly_service(session).get(user, monthly_id)
    status_code = 202 if report.status is MonthlyStatus.GENERATING else 200
    return JSONResponse(
        status_code=status_code,
        content=MonthlyReportOut.from_domain(report).model_dump(mode="json"),
    )


@router.patch("/{monthly_id}")
async def patch_monthly_report(
    monthly_id: int,
    body: MonthlyReportPatch,
    user: CurrentUser,
    container: ContainerDep,
) -> MonthlyReportOut:
    """draft の保存（save）または承認（approve）。approved 後の編集は 422。"""
    async with unit_of_work(container.session_factory) as session:
        service = container.monthly_service(session)
        if body.action == "save":
            # body_markdown の必須性は schema で検証済み
            report = await service.save_draft(user, monthly_id, body.body_markdown or "")
        else:
            report = await service.approve(user, monthly_id)
    return MonthlyReportOut.from_domain(report)


@router.get("/{monthly_id}/pdf")
async def get_monthly_report_pdf(
    monthly_id: int,
    user: CurrentUser,
    container: ContainerDep,
    renderer: PdfRendererDep,
) -> Response:
    """draft/approved の PDF を返す。生成中/失敗は 422。"""
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
