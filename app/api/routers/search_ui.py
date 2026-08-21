"""F-3 過去事例検索の画面。

/api/v1/search（SSE）を fetch で呼び、sources → token → done を逐次表示する。
検索本体・認可・引用実在検証は SearchService 側が担い、この層は表示のみ
（バックエンド仕様には一切触れない読み取り専用のクライアント）。
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from app.api.deps import ContainerDep
from app.api.labels import template_context
from app.api.routers._ui_shared import TEMPLATES, all_users, resolve_user

router = APIRouter(tags=["search-ui"])


@router.get("/search", response_class=HTMLResponse)
async def search_home(
    request: Request,
    container: ContainerDep,
    uid: int = Query(..., description="dev用の利用者ID（SSO抽象点）"),
) -> HTMLResponse:
    """検索画面。uid は topbar のセレクタと連動し、X-User-Id ヘッダとして検索APIへ渡る。"""
    user = await resolve_user(container, uid)
    return TEMPLATES.TemplateResponse(
        request,
        "search.html",
        {
            "user": user,
            "uid": uid,
            "users": await all_users(container),
            "active_nav": "search",
            **template_context(),
        },
    )
