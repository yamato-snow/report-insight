"""F-1 取込パイプラインの integration テスト（実 PostgreSQL + respx で Webhook 検証）。"""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.db import unit_of_work
from app.domain.values import AnalysisStatus, Urgency
from app.infra.db import models
from app.infra.db.repositories import SqlReportRepository
from app.infra.embedding.fake_client import FakeEmbeddingClient
from app.infra.llm.fake_client import FakeLLMClient
from app.infra.notify.slack import SlackNotifier
from app.services.ingest import IngestService
from tests.unit.fakes import FakeMasker, FakeMetrics, FakeStorage

pytestmark = pytest.mark.integration

_WEBHOOK = "http://webhook-mock.test/webhook"


def _payload(raw_text: str, source_key: str, property_id: int = 101) -> bytes:
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


def _service(storage: FakeStorage, session: AsyncSession, notifier: SlackNotifier) -> IngestService:
    return IngestService(
        storage=storage,
        masker=FakeMasker(),
        llm=FakeLLMClient(),
        embedder=FakeEmbeddingClient(dim=1024),
        repository=SqlReportRepository(session),
        notifier=notifier,
        metrics=FakeMetrics(),
        confidence_threshold=0.85,
    )


async def test_ingest_persists_report_analysis_and_chunks(
    seeded: async_sessionmaker[AsyncSession],
) -> None:
    storage = FakeStorage({"k1.json": _payload("共用部を清掃しました。", "k1.json")})
    notifier = SlackNotifier(_WEBHOOK)

    with respx.mock:
        respx.post(_WEBHOOK).mock(return_value=httpx.Response(200))
        async with unit_of_work(seeded) as session:
            outcome = await _service(storage, session, notifier).ingest_from_key("k1.json")

    assert outcome.report_id is not None
    async with seeded() as session:
        reports = (
            await session.execute(select(func.count()).select_from(models.Report))
        ).scalar_one()
        chunks = (
            await session.execute(select(func.count()).select_from(models.ReportChunk))
        ).scalar_one()
    assert reports == 1
    assert chunks == 1


async def test_ingest_idempotent_on_duplicate_source_key(
    seeded: async_sessionmaker[AsyncSession],
) -> None:
    storage = FakeStorage({"dup.json": _payload("3階廊下で漏水。至急対応。", "dup.json")})
    notifier = SlackNotifier(_WEBHOOK)

    with respx.mock:
        route = respx.post(_WEBHOOK).mock(return_value=httpx.Response(200))
        async with unit_of_work(seeded) as session:
            first = await _service(storage, session, notifier).ingest_from_key("dup.json")
        async with unit_of_work(seeded) as session:
            second = await _service(storage, session, notifier).ingest_from_key("dup.json")

    assert first.duplicate is False
    assert second.duplicate is True  # 2回目は冪等で二重登録しない
    async with seeded() as session:
        count = (
            await session.execute(select(func.count()).select_from(models.Report))
        ).scalar_one()
    assert count == 1
    assert route.call_count == 1  # 通知も1回のみ


async def test_high_urgency_sends_webhook_payload(
    seeded: async_sessionmaker[AsyncSession],
) -> None:
    storage = FakeStorage({"u.json": _payload("屋上でガス臭。火災の危険。至急確認を。", "u.json")})
    notifier = SlackNotifier(_WEBHOOK)

    with respx.mock:
        route = respx.post(_WEBHOOK).mock(return_value=httpx.Response(200))
        async with unit_of_work(seeded) as session:
            outcome = await _service(storage, session, notifier).ingest_from_key("u.json")

    assert outcome.notified is True
    assert route.called
    sent = json.loads(route.calls.last.request.content)
    assert sent["urgency"] == Urgency.HIGH.value
    assert sent["report_id"] == outcome.report_id


async def test_low_confidence_goes_to_needs_review(
    seeded: async_sessionmaker[AsyncSession],
) -> None:
    storage = FakeStorage({"lc.json": _payload("状況不明。詳細は曖昧。", "lc.json")})
    notifier = SlackNotifier(_WEBHOOK)

    with respx.mock:
        respx.post(_WEBHOOK).mock(return_value=httpx.Response(200))
        async with unit_of_work(seeded) as session:
            outcome = await _service(storage, session, notifier).ingest_from_key("lc.json")

    assert outcome.status is AnalysisStatus.NEEDS_REVIEW
    async with seeded() as session:
        status = (await session.execute(select(models.ReportAnalysis.status))).scalar_one()
    assert status == AnalysisStatus.NEEDS_REVIEW.value
