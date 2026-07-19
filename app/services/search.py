"""F-2 RAG検索: ハイブリッド検索→回答生成→引用実在検証（基本設計 §2.2 / LLM設計書 §2）。

サービスは SSE 用のドメインイベントを yield し、SSE 整形は API 層が担う。
"""

from __future__ import annotations

import re
import time
from collections.abc import AsyncIterator

from pydantic import BaseModel

from app.core.logging import get_logger
from app.domain.entities import SearchFilters, User
from app.domain.values import SEARCH_TOP_K
from app.services.ports import EmbeddingClient, LLMClient, MetricsPort, SearchRepository

logger = get_logger(__name__)

_CITATION_RE = re.compile(r"\[report:(\d+)\]")


class SourceItem(BaseModel):
    id: int
    reported_at: str
    summary: str


class SourcesEvent(BaseModel):
    reports: list[SourceItem]


class TokenEvent(BaseModel):
    text: str


class DoneEvent(BaseModel):
    citations: list[int]
    latency_ms: int
    input_tokens: int
    output_tokens: int


class NoResultsEvent(BaseModel):
    message: str = "該当事例なし"


SearchEvent = SourcesEvent | TokenEvent | DoneEvent | NoResultsEvent


class SearchService:
    """RAG検索ユースケース。認可・0件ショートサーキット・引用検証を内包する。"""

    def __init__(
        self,
        *,
        llm: LLMClient,
        embedder: EmbeddingClient,
        repository: SearchRepository,
        metrics: MetricsPort,
    ) -> None:
        self._llm = llm
        self._embedder = embedder
        self._repo = repository
        self._metrics = metrics

    async def search(
        self, user: User, query: str, filters: SearchFilters
    ) -> AsyncIterator[SearchEvent]:
        """検索を実行しイベント列を返す。

        Yields:
            SourcesEvent → TokenEvent* → DoneEvent、または（0件時）NoResultsEvent。
        """
        started = time.perf_counter()
        log = logger.bind(user_id=user.id, role=user.role)

        permitted = await self._repo.permitted_property_ids(user)
        query_vec = await self._embedder.embed_query(query)
        hits = await self._repo.hybrid_search(query_vec, filters, permitted, SEARCH_TOP_K)

        self._metrics.incr("search_total")
        if not hits:
            # 0件は LLM を呼ばない（ハルシネーション防止・コスト節約。LLM設計書 §2）
            self._metrics.incr("search_no_results")
            log.info("search.no_results")
            yield NoResultsEvent()
            return

        yield SourcesEvent(
            reports=[
                SourceItem(
                    id=h.report_id,
                    reported_at=h.reported_at.date().isoformat(),
                    summary=h.summary,
                )
                for h in hits
            ]
        )

        parts: list[str] = []
        stream = self._llm.stream_answer(query, hits)
        async for token in stream:
            parts.append(token)
            yield TokenEvent(text=token)

        # 引用の実在検証: 権限内に実在するIDのみリンク化（LLM設計書 §2 / §7）
        cited = _parse_citations("".join(parts))
        valid = await self._repo.existing_report_ids(list(cited), permitted)
        hallucinated = cited - valid
        if hallucinated:
            log.warning("search.hallucinated_citations", ids=sorted(hallucinated))

        usage = stream.usage
        self._metrics.emit_tokens(
            input_tokens=usage.input_tokens, output_tokens=usage.output_tokens
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        log.info(
            "search.completed",
            hits=len(hits),
            citations=len(valid),
            latency_ms=latency_ms,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
        )
        yield DoneEvent(
            citations=sorted(valid),
            latency_ms=latency_ms,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
        )


def _parse_citations(text: str) -> set[int]:
    return {int(m) for m in _CITATION_RE.findall(text)}
