"""RAG検索（API設計書 §3: POST /search、SSEストリーミング）。"""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.api.deps import ContainerDep, CurrentUser
from app.api.schemas import SearchRequest
from app.api.sse import render_event
from app.core.db import unit_of_work
from app.domain.values import AuditAction

router = APIRouter(prefix="/search", tags=["search"])


@router.post("")
async def search(
    request: SearchRequest,
    user: CurrentUser,
    container: ContainerDep,
) -> StreamingResponse:
    """検索を SSE（sources → token* → done、または no_results）で返す。

    セッションはストリーミング全体で開いたままにするためジェネレータ内で開く
    （yield依存だとストリーム消費前に閉じられるため）。監査は別トランザクションで先に確定する。
    """
    # 検索の実行は監査ログに記録する（09 §6）。SSE ストリームとは別 UoW で確定させる。
    async with unit_of_work(container.session_factory) as session:
        await container.audit_repository(session).record(
            user_id=user.id,
            action=AuditAction.SEARCH.value,
            payload={"query": request.query},
        )

    async def event_stream() -> AsyncIterator[str]:
        async with container.session_factory() as session:
            service = container.search_service(session)
            async for event in service.search(user, request.query, request.filters.to_domain()):
                yield render_event(event)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
