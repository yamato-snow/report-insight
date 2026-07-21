"""F-4 管理画面（Jinja2 + HTMX。SPA にしない。基本設計 §1 / 05 §7）。

サーバサイドレンダリングし、部分更新のみ HTMX で差し替える。LLM 由来テキスト
（normalized_summary / raw_text）は Jinja2 の自動エスケープでサニタイズする（XSS 対策 §7）。
認可は AdminService が permitted_property_ids で強制するため、画面には権限内データのみ載る。
SSO は抽象化済みのため、dev では利用者を uid クエリで指定する（本番はセッションに置換）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BeforeValidator

from app.api.deps import ContainerDep
from app.api.labels import template_context
from app.core.db import unit_of_work
from app.domain.entities import Property, Report, ReportListFilters, User
from app.domain.errors import NotFoundError
from app.domain.values import AnalysisStatus, Category, Urgency

router = APIRouter(tags=["admin-ui"])


def _empty_to_none(value: object) -> object | None:
    """HTML の <select> は「すべて」を空文字で送ってくるため、未指定として扱う。

    これを挟まないと `int | None` や Enum のバリデーションに落ちて 422 になる。
    """
    return None if value == "" else value


_Blankable = BeforeValidator(_empty_to_none)

PropertyFilter = Annotated[int | None, _Blankable, Query()]
CategoryFilter = Annotated[Category | None, _Blankable, Query()]
UrgencyFilter = Annotated[Urgency | None, _Blankable, Query()]
StatusFilter = Annotated[AnalysisStatus | None, _Blankable, Query()]

_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))

# 1ページの表示件数。keyset ページングのため「次へ」の有無判定に +1 件を余分に取る。
PAGE_SIZE = 20


async def _resolve_user(container: ContainerDep, uid: int) -> User:
    async with container.session_factory() as session:
        try:
            return await container.user_repository(session).get(uid)
        except NotFoundError as exc:
            raise HTTPException(status_code=401, detail="不明な利用者です") from exc


async def _all_users(container: ContainerDep) -> list[User]:
    """利用者切替セレクタ用の一覧（dev 限定。本番は SSO のセッションに置換）。"""
    async with container.session_factory() as session:
        return await container.user_repository(session).list_all()


def _property_names(properties: list[Property]) -> dict[int, str]:
    return {p.id: p.name for p in properties}


async def _permitted_properties(container: ContainerDep, user: User) -> list[Property]:
    async with container.session_factory() as session:
        return await container.admin_service(session).list_properties(user)


@router.get("/admin", response_class=HTMLResponse)
async def admin_home(
    request: Request,
    container: ContainerDep,
    uid: int = Query(..., description="dev用の利用者ID（SSO抽象点）"),
) -> HTMLResponse:
    """管理画面トップ（フィルタ + 一覧 + 未分類キュータブ）。"""
    user = await _resolve_user(container, uid)
    props = await _permitted_properties(container, user)
    return _TEMPLATES.TemplateResponse(
        request,
        "admin.html",
        {
            "user": user,
            "uid": uid,
            "users": await _all_users(container),
            "properties": props,
            "categories": list(Category),
            "urgencies": list(Urgency),
            "statuses": list(AnalysisStatus),
            "active_nav": "admin",
            **template_context(),
        },
    )


@router.get("/admin/reports", response_class=HTMLResponse)
async def admin_reports_partial(
    request: Request,
    container: ContainerDep,
    uid: int = Query(...),
    property_id: PropertyFilter = None,
    category: CategoryFilter = None,
    urgency: UrgencyFilter = None,
    status: StatusFilter = None,
    queue: bool = False,
    cursor: int | None = None,
) -> HTMLResponse:
    """一覧/未分類キューの HTMX 部分テンプレート（テーブル行 + ページ送り）。"""
    user = await _resolve_user(container, uid)
    props = await _permitted_properties(container, user)

    async with container.session_factory() as session:
        service = container.admin_service(session)
        if queue:
            rows = await service.review_queue(user, cursor, PAGE_SIZE + 1)
        else:
            filters = ReportListFilters(
                property_id=property_id, category=category, urgency=urgency, status=status
            )
            rows = await service.list_reports(user, filters, cursor, PAGE_SIZE + 1)

    has_next = len(rows) > PAGE_SIZE
    reports: list[Report] = rows[:PAGE_SIZE]
    next_cursor = reports[-1].id if has_next and reports else None

    return _TEMPLATES.TemplateResponse(
        request,
        "_reports_table.html",
        {
            "reports": reports,
            "uid": uid,
            "property_names": _property_names(props),
            "queue": queue,
            "next_cursor": next_cursor,
            "is_first_page": cursor is None,
            "query": {
                "property_id": property_id,
                "category": category.value if category else None,
                "urgency": urgency.value if urgency else None,
                "status": status.value if status else None,
            },
            **template_context(),
        },
    )


@router.get("/admin/reports/{report_id}", response_class=HTMLResponse)
async def admin_report_detail(
    request: Request,
    container: ContainerDep,
    report_id: int,
    uid: int = Query(...),
) -> HTMLResponse:
    """報告書1件の詳細（原文 + 分類の上書きフォーム）。権限外は AdminService が 403 を投げる。"""
    user = await _resolve_user(container, uid)
    props = await _permitted_properties(container, user)
    async with container.session_factory() as session:
        report = await container.admin_service(session).get_report(user, report_id)
    return _TEMPLATES.TemplateResponse(
        request,
        "_report_detail.html",
        {
            "report": report,
            "uid": uid,
            "property_names": _property_names(props),
            "categories": list(Category),
            "urgencies": list(Urgency),
            "saved": False,
            **template_context(),
        },
    )


@router.post("/admin/reports/{report_id}/analysis", response_class=HTMLResponse)
async def admin_override_analysis(
    request: Request,
    container: ContainerDep,
    report_id: int,
    category: Annotated[Category, Form()],
    urgency: Annotated[Urgency, Form()],
    action_required: Annotated[bool, Form()] = False,
    uid: int = Query(...),
) -> HTMLResponse:
    """分類の人手確定（F-4-4）。確定後は human_verified になり監査ログに残る。

    レスポンスヘッダ HX-Trigger で一覧側に再読み込みを促し、キューから消えることを画面に反映する。
    """
    user = await _resolve_user(container, uid)
    props = await _permitted_properties(container, user)
    async with unit_of_work(container.session_factory) as session:
        service = container.admin_service(session)
        await service.override_analysis(user, report_id, category, urgency, action_required)
        report = await service.get_report(user, report_id)

    response = _TEMPLATES.TemplateResponse(
        request,
        "_report_detail.html",
        {
            "report": report,
            "uid": uid,
            "property_names": _property_names(props),
            "categories": list(Category),
            "urgencies": list(Urgency),
            "saved": True,
            **template_context(),
        },
    )
    response.headers["HX-Trigger"] = "reportsChanged"
    return response
