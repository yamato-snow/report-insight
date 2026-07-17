"""API 依存（認証・コンテナ取得）。認証は AuthBackend 抽象の簡易代替（基本設計 §3）。"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request

from app.core.di import Container
from app.domain.entities import User
from app.domain.errors import NotFoundError


def get_container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


async def get_current_user(
    container: Annotated[Container, Depends(get_container)],
    x_user_id: Annotated[str | None, Header(alias="X-User-Id")] = None,
) -> User:
    """開発用の簡易認証。本番は SSO(SAML)→セッションに置換（AuthBackend 抽象点）。"""
    if x_user_id is None:
        raise HTTPException(status_code=401, detail="未認証（X-User-Id が必要）")
    try:
        user_id = int(x_user_id)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="X-User-Id が不正です") from exc

    async with container.session_factory() as session:
        try:
            return await container.user_repository(session).get(user_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=401, detail="不明な利用者です") from exc


CurrentUser = Annotated[User, Depends(get_current_user)]
ContainerDep = Annotated[Container, Depends(get_container)]
