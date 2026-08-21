"""監査ログの閲覧画面。

受入条件（F-4-3 の承認、F-4-4 の分類上書き）が「監査ログに残る」ことを画面で確認できるように
するための参照系。audit_logs は追記専用なので読み取りのみを提供する。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from app.api.deps import ContainerDep
from app.api.labels import template_context
from app.api.routers._ui_shared import TEMPLATES, all_users, resolve_user
from app.domain.labels import CATEGORY_JP, URGENCY_JP
from app.domain.values import Category, Urgency

router = APIRouter(tags=["audit-ui"])

AUDIT_LIMIT = 100

ACTION_LABELS = {
    "override_analysis": "分類の上書き",
    "approve_monthly": "月次報告書の承認",
    "search": "検索",
}


def _format_payload(action: str, payload: dict[str, Any]) -> str:
    """payload(JSON) を読める日本語へ。未知の形は素通しし、表記は labels.py に委ねる。"""
    try:
        if action == "override_analysis":
            category = CATEGORY_JP[Category(payload["category"])]
            urgency = URGENCY_JP[Urgency(payload["urgency"])]
            action_req = "要対応" if payload.get("action_required") else "対応不要"
            return (
                f"報告書 #{payload['report_id']} を"
                f"「{category}・緊急度 {urgency}・{action_req}」に確定"
            )
        if action == "approve_monthly":
            year, month = str(payload["month"])[:7].split("-")
            return (
                f"物件 #{payload['property_id']} の {int(year)}年{int(month)}月分"
                f"（v{payload['version']}）を確定"
            )
        if action == "search":
            return f"「{payload['query']}」で過去事例を検索"
    except (KeyError, ValueError):
        pass  # 想定外の形は生表示にフォールバック
    return " / ".join(f"{k}={v}" for k, v in payload.items())


@router.get("/audit", response_class=HTMLResponse)
async def audit_home(
    request: Request,
    container: ContainerDep,
    uid: int = Query(..., description="dev用の利用者ID（SSO抽象点）"),
) -> HTMLResponse:
    user = await resolve_user(container, uid)
    async with container.session_factory() as session:
        entries = await container.audit_repository(session).list_recent(AUDIT_LIMIT)
    rows = [
        {
            "created_at": e.created_at,
            "actor_email": e.actor_email,
            "action_label": ACTION_LABELS.get(e.action.value, e.action.value),
            "detail": _format_payload(e.action.value, e.payload),
        }
        for e in entries
    ]
    return TEMPLATES.TemplateResponse(
        request,
        "audit.html",
        {
            "user": user,
            "uid": uid,
            "users": await all_users(container),
            "rows": rows,
            "active_nav": "audit",
            **template_context(),
        },
    )
