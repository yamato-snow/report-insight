"""F-2 検索サービスの unit テスト（Fakeポートのみ）。"""

from __future__ import annotations

from app.domain.entities import SearchFilters, User
from app.domain.values import Role
from app.infra.embedding.fake_client import FakeEmbeddingClient
from app.infra.llm.fake_client import FakeLLMClient
from app.services.search import (
    DoneEvent,
    NoResultsEvent,
    SearchService,
    SourcesEvent,
    TokenEvent,
)
from tests.unit.fakes import CitingFakeLLM, FakeMetrics, FakeSearchRepository, make_hit

_USER = User(id=1, email="m@example.com", role=Role.BRANCH_MANAGER, branch_id=1)


def _service(
    repo: FakeSearchRepository, llm=None, metrics: FakeMetrics | None = None
) -> SearchService:
    return SearchService(
        llm=llm or FakeLLMClient(),
        embedder=FakeEmbeddingClient(dim=64),
        repository=repo,
        metrics=metrics or FakeMetrics(),
    )


async def _collect(service: SearchService):
    return [e async for e in service.search(_USER, "雨漏りの事例", SearchFilters())]


async def test_search_no_results_shortcircuits_llm() -> None:
    repo = FakeSearchRepository(hits=[])

    events = await _collect(_service(repo))

    assert len(events) == 1
    assert isinstance(events[0], NoResultsEvent)


async def test_search_emits_sources_then_tokens_then_done() -> None:
    repo = FakeSearchRepository(hits=[make_hit(987)])

    events = await _collect(_service(repo))

    assert isinstance(events[0], SourcesEvent)
    assert any(isinstance(e, TokenEvent) for e in events)
    assert isinstance(events[-1], DoneEvent)
    assert events[0].reports[0].id == 987


async def test_search_verifies_citations_drops_hallucinated() -> None:
    # 実在する 987 と、存在しない 999 を引用させる
    repo = FakeSearchRepository(hits=[make_hit(987)], existing={987})
    llm = CitingFakeLLM(cite_ids=[987, 999])

    events = await _collect(_service(repo, llm))

    done = events[-1]
    assert isinstance(done, DoneEvent)
    assert done.citations == [987]  # 999 は幻覚として除去


async def test_search_done_reports_token_usage() -> None:
    repo = FakeSearchRepository(hits=[make_hit(1)])

    events = await _collect(_service(repo))

    done = events[-1]
    assert isinstance(done, DoneEvent)
    assert done.input_tokens > 0
    assert done.output_tokens > 0


async def test_search_no_results_emits_shortcircuit_metric() -> None:
    metrics = FakeMetrics()

    await _collect(_service(FakeSearchRepository(hits=[]), metrics=metrics))

    assert metrics.counts.get("search_total") == 1
    assert metrics.counts.get("search_no_results") == 1
    assert metrics.tokens == []


async def test_search_hit_emits_tokens_and_no_shortcircuit() -> None:
    metrics = FakeMetrics()

    await _collect(_service(FakeSearchRepository(hits=[make_hit(1)]), metrics=metrics))

    assert metrics.counts.get("search_total") == 1
    assert "search_no_results" not in metrics.counts
    assert len(metrics.tokens) == 1
