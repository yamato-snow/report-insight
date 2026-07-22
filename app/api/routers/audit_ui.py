"""監査ログの閲覧画面。

受入条件（F-4-3 の承認、F-4-4 の分類上書き）が「監査ログに残る」ことを画面で確認できるように
するための参照系。audit_logs は追記専用なので読み取りのみを提供する。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.api.deps import ContainerDep
from app.api.labels import template_context
from app.domain.entities import User
from app.domain.errors import NotFoundError

router = APIRouter(tags=["audit-ui"])

_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))

AUDIT_LIMIT = 100

ACTION_LABELS = {
    "override_analysis": "分類の上書き",
    "approve_monthly": "月次報告書の承認",
    "search": "検索",
}


async def _resolve_user(container: ContainerDep, uid: int) -> User:
    async with container.session_factory() as session:
        try:
            return await container.user_repository(session).get(uid)
        except NotFoundError as exc:
            raise HTTPException(status_code=401, detail="不明な利用者です") from exc


@router.get("/audit", response_class=HTMLResponse)
async def audit_home(
    request: Request,
    container: ContainerDep,
    uid: int = Query(..., description="dev用の利用者ID（SSO抽象点）"),
) -> HTMLResponse:
    user = await _resolve_user(container, uid)
    async with container.session_factory() as session:
        entries = await container.audit_repository(session).list_recent(AUDIT_LIMIT)
        users = await container.user_repository(session).list_all()
    return _TEMPLATES.TemplateResponse(
        request,
        "audit.html",
        {
            "user": user,
            "uid": uid,
            "users": users,
            "entries": entries,
            "action_labels": ACTION_LABELS,
            "active_nav": "audit",
            **template_context(),
        },
    )
