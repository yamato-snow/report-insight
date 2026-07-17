"""SSE 整形（API設計書 POST /search）。サービスのドメインイベント→SSEフレーム。"""

from __future__ import annotations

from app.services.search import (
    DoneEvent,
    NoResultsEvent,
    SearchEvent,
    SourcesEvent,
    TokenEvent,
)


def format_sse(event: str, data: str) -> str:
    return f"event: {event}\ndata: {data}\n\n"


def render_event(event: SearchEvent) -> str:
    """検索イベントを SSE フレーム文字列に変換する。"""
    if isinstance(event, SourcesEvent):
        return format_sse("sources", event.model_dump_json())
    if isinstance(event, TokenEvent):
        return format_sse("token", event.model_dump_json())
    if isinstance(event, DoneEvent):
        return format_sse("done", event.model_dump_json())
    if isinstance(event, NoResultsEvent):
        return format_sse("no_results", event.model_dump_json())
    raise ValueError(f"未知の検索イベント: {type(event)!r}")
