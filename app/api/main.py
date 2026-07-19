"""FastAPI アプリ組み立て（composition root は core/di）。"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response

from app.api.error_handlers import register_error_handlers
from app.api.routers import admin_ui, health, monthly, reports, search, ui
from app.core.config import get_settings
from app.core.di import build_container
from app.core.logging import configure_logging

API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    app.state.container = build_container(settings, service="api")
    try:
        yield
    finally:
        await app.state.container.aclose()


def create_app() -> FastAPI:
    app = FastAPI(title="Report Insight", version="0.1.0", lifespan=lifespan)

    @app.middleware("http")
    async def _count_server_errors(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """5xx（未処理例外含む）を api_error として送出する（runbook §0 / LLMエラー率の外側）。"""
        try:
            response = await call_next(request)
        except Exception:
            request.app.state.container.metrics.incr("api_error")
            raise
        if response.status_code >= 500:
            request.app.state.container.metrics.incr("api_error")
        return response

    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(ui.router)
    app.include_router(admin_ui.router)
    app.include_router(search.router, prefix=API_PREFIX)
    app.include_router(monthly.router, prefix=API_PREFIX)
    app.include_router(reports.router, prefix=API_PREFIX)
    return app


app = create_app()
