"""UI ルータ共通のヘルパ（Jinja2 テンプレートと利用者解決）。

admin_ui / monthly_ui / audit_ui / search_ui / ui が同じ実装を各自コピーしていたため集約した。
利用者の uid クエリ指定は SSO の抽象点（dev のみ）で、本番はセッションに置換する。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException
from fastapi.templating import Jinja2Templates

from app.api.deps import ContainerDep
from app.domain.entities import User
from app.domain.errors import NotFoundError

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


async def resolve_user(container: ContainerDep, uid: int) -> User:
    async with container.session_factory() as session:
        try:
            return await container.user_repository(session).get(uid)
        except NotFoundError as exc:
            raise HTTPException(status_code=401, detail="不明な利用者です") from exc


async def all_users(container: ContainerDep) -> list[User]:
    """利用者切替セレクタ用の一覧（dev 限定。本番は SSO のセッションに置換）。"""
    async with container.session_factory() as session:
        return await container.user_repository(session).list_all()
