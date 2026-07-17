"""ドメイン例外 → HTTP(Problem Details, RFC 9457) 変換（API設計書 §1・規約 §4）。

ドメイン例外→HTTPステータスの対応表はこの1箇所に集約する。
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.domain.errors import (
    DomainError,
    InvalidStateError,
    NotFoundError,
    PermissionDeniedError,
    RetryableError,
)

_STATUS_MAP: list[tuple[type[DomainError], int, str]] = [
    (NotFoundError, 404, "not-found"),
    (PermissionDeniedError, 403, "forbidden"),
    (InvalidStateError, 422, "invalid-state"),
    (RetryableError, 503, "service-unavailable"),
]


def _problem(status: int, type_slug: str, detail: str, request: Request) -> JSONResponse:
    request_id = request.headers.get("x-request-id", "")
    return JSONResponse(
        status_code=status,
        content={
            "type": f"https://example.com/errors/{type_slug}",
            "title": type_slug.replace("-", " ").title(),
            "status": status,
            "detail": detail,
            "request_id": request_id,
        },
        media_type="application/problem+json",
    )


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def _handle_domain(request: Request, exc: DomainError) -> JSONResponse:
        for exc_type, status, slug in _STATUS_MAP:
            if isinstance(exc, exc_type):
                response = _problem(status, slug, str(exc), request)
                if status == 503:
                    response.headers["Retry-After"] = "30"
                return response
        return _problem(500, "internal", "内部エラー", request)
