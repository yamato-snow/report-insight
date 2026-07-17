"""死活監視（API設計書: /healthz / /readyz）。ALB ヘルスチェック用。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text

from app.api.deps import get_container
from app.core.di import Container

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(container: Annotated[Container, Depends(get_container)]) -> dict[str, str]:
    async with container.session_factory() as session:
        await session.execute(text("SELECT 1"))
    return {"status": "ready"}
