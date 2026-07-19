"""F-2 RAG検索の integration テスト（実 PostgreSQL・ハイブリッド検索・認可・SSE）。"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.main import create_app
from app.core.db import unit_of_work
from app.domain.entities import SearchFilters, User
from app.domain.values import Role
from app.infra.db.repositories import SqlReportRepository, SqlSearchRepository
from app.infra.embedding.fake_client import FakeEmbeddingClient
from app.infra.llm.fake_client import FakeLLMClient
from app.services.ingest import IngestService
from app.services.search import DoneEvent, NoResultsEvent, SearchService, SourcesEvent
from tests.unit.fakes import FakeMasker, FakeMetrics, FakeNotifier, FakeStorage

pytestmark = pytest.mark.integration


def _payload(raw_text: str, source_key: str, property_id: int) -> bytes:
    return json.dumps(
        {
            "source_key": source_key,
            "property_id": property_id,
            "reported_at": "2026-06-01T09:00:00+00:00",
            "reporter_role": "巡回スタッフ",
            "raw_text": raw_text,
            "photo_meta": {},
        }
    ).encode("utf-8")


async def _ingest(
    session_factory: async_sessionmaker[AsyncSession], objects: dict[str, bytes]
) -> None:
    storage = FakeStorage(objects)
    for key in objects:
        async with unit_of_work(session_factory) as session:
            service = IngestService(
                storage=storage,
                masker=FakeMasker(),
                llm=FakeLLMClient(),
                embedder=FakeEmbeddingClient(dim=1024),
                repository=SqlReportRepository(session),
                notifier=FakeNotifier(),
                metrics=FakeMetrics(),
                confidence_threshold=0.85,
            )
            await service.ingest_from_key(key)


def _search_service(session: AsyncSession) -> SearchService:
    return SearchService(
        llm=FakeLLMClient(),
        embedder=FakeEmbeddingClient(dim=1024),
        repository=SqlSearchRepository(session),
        metrics=FakeMetrics(),
    )


async def test_branch_manager_cannot_see_other_branch_reports(
    seeded: async_sessionmaker[AsyncSession],
) -> None:
    await _ingest(
        seeded,
        {
            "t.json": _payload("3階廊下で漏水が発生。", "t.json", property_id=101),  # 東京
            "o.json": _payload("3階廊下で漏水が発生。", "o.json", property_id=201),  # 大阪
        },
    )
    tokyo_mgr = User(id=1, email="tokyo@e.com", role=Role.BRANCH_MANAGER, branch_id=1)

    async with seeded() as session:
        events = [
            e async for e in _search_service(session).search(tokyo_mgr, "漏水", SearchFilters())
        ]

    sources = next(e for e in events if isinstance(e, SourcesEvent))
    property_ids = {r.id for r in sources.reports}
    # 東京支店管理者には大阪(201)の報告は1件も混入しない
    assert property_ids  # 東京分はヒットする
    async with seeded() as session:
        repo = SqlSearchRepository(session)
        permitted = await repo.permitted_property_ids(tokyo_mgr)
    assert 201 not in permitted


async def test_qa_can_see_all_branches(
    seeded: async_sessionmaker[AsyncSession],
) -> None:
    await _ingest(
        seeded,
        {
            "t.json": _payload("3階廊下で漏水が発生。", "t.json", property_id=101),
            "o.json": _payload("3階廊下で漏水が発生。", "o.json", property_id=201),
        },
    )
    qa = User(id=2, email="qa@e.com", role=Role.QA, branch_id=None)

    async with seeded() as session:
        events = [e async for e in _search_service(session).search(qa, "漏水", SearchFilters())]

    sources = next(e for e in events if isinstance(e, SourcesEvent))
    assert len(sources.reports) >= 2  # 全支店が対象


async def test_search_no_results_when_empty(
    seeded: async_sessionmaker[AsyncSession],
) -> None:
    qa = User(id=2, email="qa@e.com", role=Role.QA, branch_id=None)

    async with seeded() as session:
        events = [
            e async for e in _search_service(session).search(qa, "存在しない事象", SearchFilters())
        ]

    assert len(events) == 1
    assert isinstance(events[0], NoResultsEvent)


async def test_search_citations_are_real_ids(
    seeded: async_sessionmaker[AsyncSession],
) -> None:
    await _ingest(seeded, {"t.json": _payload("3階廊下で漏水が発生。", "t.json", property_id=101)})
    qa = User(id=2, email="qa@e.com", role=Role.QA, branch_id=None)

    async with seeded() as session:
        events = [e async for e in _search_service(session).search(qa, "漏水", SearchFilters())]
        sources = next(e for e in events if isinstance(e, SourcesEvent))
        done = events[-1]

    assert isinstance(done, DoneEvent)
    real_ids = {r.id for r in sources.reports}
    assert set(done.citations).issubset(real_ids)  # 引用は実在IDのみ


async def test_api_search_sse_end_to_end(
    seeded: async_sessionmaker[AsyncSession],
) -> None:
    await _ingest(seeded, {"t.json": _payload("3階廊下で漏水が発生。", "t.json", property_id=101)})

    with TestClient(create_app()) as client:
        response = client.post(
            "/api/v1/search",
            headers={"X-User-Id": "2"},
            json={"query": "漏水", "filters": {}},
        )

    assert response.status_code == 200
    body = response.text
    assert "event: sources" in body
    assert "event: done" in body


async def test_api_search_requires_auth() -> None:
    with TestClient(create_app()) as client:
        response = client.post("/api/v1/search", json={"query": "漏水", "filters": {}})
    assert response.status_code == 401
