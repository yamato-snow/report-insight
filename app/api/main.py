"""FastAPI アプリ組み立て（composition root は core/di）。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.error_handlers import register_error_handlers
from app.api.routers import health, monthly, search, ui
from app.core.config import get_settings
from app.core.di import build_container
from app.core.logging import configure_logging

API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    app.state.container = build_container(settings)
    try:
        yield
    finally:
        await app.state.container.aclose()


def create_app() -> FastAPI:
    app = FastAPI(title="Report Insight", version="0.1.0", lifespan=lifespan)
    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(ui.router)
    app.include_router(search.router, prefix=API_PREFIX)
    app.include_router(monthly.router, prefix=API_PREFIX)
    return app


app = create_app()
