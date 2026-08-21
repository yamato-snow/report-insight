"""トップページ（入口）。

依頼主の3課題（確認負荷・事例の属人化・月次作成の負荷）と、対応する画面への導線をまとめる。
uid が無い直アクセスでもデモを始められるよう既定の利用者（東京支店管理者）で表示する。
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from app.api.deps import ContainerDep
from app.api.labels import template_context
from app.api.routers._ui_shared import TEMPLATES, all_users, resolve_user

router = APIRouter(tags=["ui"])

# uid 未指定時の既定利用者（seed_demo の東京支店管理者）。SSO 導入時はセッションに置換する。
DEFAULT_UID = 1


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def index(
    request: Request,
    container: ContainerDep,
    uid: int = Query(default=DEFAULT_UID, description="dev用の利用者ID（SSO抽象点）"),
) -> HTMLResponse:
    """トップページ（3課題と画面への導線）。"""
    user = await resolve_user(container, uid)
    return TEMPLATES.TemplateResponse(
        request,
        "index.html",
        {
            "user": user,
            "uid": uid,
            "users": await all_users(container),
            "active_nav": "home",
            **template_context(),
        },
    )
