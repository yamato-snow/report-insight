"""F-4 管理API/画面の integration テスト（実 PostgreSQL・認可・一覧/キュー/上書き）。

最重要: 支店管理者が他支店の報告書へアクセスすると 403（検索・一覧に混入しない）。
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.main import create_app
from app.core.db import unit_of_work
from app.infra.db import models
from app.infra.db.repositories import SqlReportRepository
from app.infra.embedding.fake_client import FakeEmbeddingClient
from app.infra.llm.fake_client import FakeLLMClient
from app.services.ingest import IngestService
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


async def _report_id_for(session_factory: async_sessionmaker[AsyncSession], source_key: str) -> int:
    async with session_factory() as session:
        return (
            await session.execute(
                select(models.Report.id).where(models.Report.source_key == source_key)
            )
        ).scalar_one()


async def _seed_two_branches(seeded: async_sessionmaker[AsyncSession]) -> None:
    await _ingest(
        seeded,
        {
            "t1.json": _payload("設備の故障が発生。", "t1.json", 101),  # 東京・equipment
            "t2.json": _payload("曖昧", "t2.json", 101),  # 東京・低信頼→needs_review
            "o1.json": _payload("大阪で漏水。", "o1.json", 201),  # 大阪
        },
    )


async def test_qa_lists_all_branches(seeded: async_sessionmaker[AsyncSession]) -> None:
    await _seed_two_branches(seeded)
    with TestClient(create_app()) as client:
        resp = client.get("/api/v1/reports", headers={"X-User-Id": "2"})
    assert resp.status_code == 200
    property_ids = {item["property_id"] for item in resp.json()["items"]}
    assert property_ids == {101, 201}


async def test_branch_manager_list_excludes_other_branch(
    seeded: async_sessionmaker[AsyncSession],
) -> None:
    await _seed_two_branches(seeded)
    with TestClient(create_app()) as client:
        resp = client.get("/api/v1/reports", headers={"X-User-Id": "1"})  # 東京
    assert resp.status_code == 200
    property_ids = {item["property_id"] for item in resp.json()["items"]}
    assert property_ids == {101}  # 大阪(201)は混入しない


async def test_branch_manager_get_other_branch_is_403(
    seeded: async_sessionmaker[AsyncSession],
) -> None:
    await _seed_two_branches(seeded)
    osaka_id = await _report_id_for(seeded, "o1.json")
    with TestClient(create_app()) as client:
        resp = client.get(f"/api/v1/reports/{osaka_id}", headers={"X-User-Id": "1"})
    assert resp.status_code == 403


async def test_review_queue_only_needs_review(
    seeded: async_sessionmaker[AsyncSession],
) -> None:
    await _seed_two_branches(seeded)
    with TestClient(create_app()) as client:
        resp = client.get("/api/v1/reports/review-queue", headers={"X-User-Id": "2"})
    assert resp.status_code == 200
    statuses = {item["analysis"]["status"] for item in resp.json()["items"]}
    assert statuses == {"needs_review"}


async def test_override_analysis_sets_human_verified(
    seeded: async_sessionmaker[AsyncSession],
) -> None:
    await _seed_two_branches(seeded)
    tokyo_id = await _report_id_for(seeded, "t2.json")
    with TestClient(create_app()) as client:
        resp = client.patch(
            f"/api/v1/reports/{tokyo_id}/analysis",
            headers={"X-User-Id": "1"},
            json={"category": "equipment_failure", "urgency": "high", "action_required": True},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "human_verified"
    assert resp.json()["category"] == "equipment_failure"


async def test_properties_scoped_to_branch(seeded: async_sessionmaker[AsyncSession]) -> None:
    with TestClient(create_app()) as client:
        qa = client.get("/api/v1/properties", headers={"X-User-Id": "2"})
        tokyo = client.get("/api/v1/properties", headers={"X-User-Id": "1"})
    assert {p["id"] for p in qa.json()} == {101, 201}
    assert {p["id"] for p in tokyo.json()} == {101}


async def test_admin_ui_page_renders(seeded: async_sessionmaker[AsyncSession]) -> None:
    with TestClient(create_app()) as client:
        resp = client.get("/admin?uid=2")
    assert resp.status_code == 200
    assert "管理画面" in resp.text
