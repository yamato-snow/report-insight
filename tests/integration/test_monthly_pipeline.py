"""F-3 月次報告書の integration テスト（実 PostgreSQL・生成→承認→PDF・認可）。

生成は BackgroundTasks で実行される。TestClient はレスポンス返却後にバックグラウンドを
同期実行するため、POST 直後の GET は draft に遷移済みになる（202 分岐は別途 repo 経由で検証）。
PDF は WeasyPrint のネイティブ依存を避けるため FakePdfRenderer に差し替える。
"""

from __future__ import annotations

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import get_pdf_renderer
from app.api.main import create_app
from app.core.db import unit_of_work
from app.infra.db.repositories import SqlMonthlyReportRepository, SqlReportRepository
from app.infra.embedding.fake_client import FakeEmbeddingClient
from app.infra.llm.fake_client import FakeLLMClient
from app.services.ingest import IngestService
from tests.unit.fakes import FakeMasker, FakeMetrics, FakeNotifier, FakePdfRenderer, FakeStorage

pytestmark = pytest.mark.integration


def _payload(raw_text: str, source_key: str, property_id: int, reported_at: str) -> bytes:
    return json.dumps(
        {
            "source_key": source_key,
            "property_id": property_id,
            "reported_at": reported_at,
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


def _client() -> TestClient:
    app = create_app()
    app.dependency_overrides[get_pdf_renderer] = FakePdfRenderer
    return TestClient(app)


async def _seed_june_reports(seeded: async_sessionmaker[AsyncSession]) -> None:
    jun = "2026-06-{:02d}T09:00:00+00:00"
    await _ingest(
        seeded,
        {
            "j1.json": _payload("設備の故障が発生。", "j1.json", 101, jun.format(3)),
            "j2.json": _payload("3階廊下で漏水が発生。", "j2.json", 101, jun.format(10)),
            "j3.json": _payload("清掃を実施。", "j3.json", 101, jun.format(20)),
            # 対象外月（5月）は集計に含まれないこと
            "m1.json": _payload("5月の清掃。", "m1.json", 101, "2026-05-20T09:00:00+00:00"),
        },
    )


async def test_monthly_lifecycle_generate_edit_approve_pdf(
    seeded: async_sessionmaker[AsyncSession],
) -> None:
    await _seed_june_reports(seeded)

    with _client() as client:
        # 生成要求（202・generating で受理）
        created = client.post(
            "/api/v1/monthly-reports",
            headers={"X-User-Id": "2"},
            json={"property_id": 101, "month": "2026-06-01"},
        )
        assert created.status_code == 202
        monthly_id = created.json()["id"]
        assert created.json()["status"] == "generating"

        # BackgroundTasks 実行後は draft（GET 200）。6月分3件のみ集計。
        got = client.get(f"/api/v1/monthly-reports/{monthly_id}", headers={"X-User-Id": "2"})
        assert got.status_code == 200
        assert got.json()["status"] == "draft"
        assert "総報告件数: 3 件" in got.json()["body_markdown"]

        # 保存（人手修正）
        saved = client.patch(
            f"/api/v1/monthly-reports/{monthly_id}",
            headers={"X-User-Id": "2"},
            json={"action": "save", "body_markdown": got.json()["body_markdown"] + "\n\n追記。"},
        )
        assert saved.status_code == 200
        assert saved.json()["body_markdown"].endswith("追記。")

        # 承認 → approved
        approved = client.patch(
            f"/api/v1/monthly-reports/{monthly_id}",
            headers={"X-User-Id": "2"},
            json={"action": "approve"},
        )
        assert approved.status_code == 200
        assert approved.json()["status"] == "approved"

        # approved 後の編集は 422
        rejected = client.patch(
            f"/api/v1/monthly-reports/{monthly_id}",
            headers={"X-User-Id": "2"},
            json={"action": "save", "body_markdown": "承認後の改ざん"},
        )
        assert rejected.status_code == 422

        # PDF（Fake レンダラ）
        pdf = client.get(f"/api/v1/monthly-reports/{monthly_id}/pdf", headers={"X-User-Id": "2"})
        assert pdf.status_code == 200
        assert pdf.headers["content-type"] == "application/pdf"
        assert pdf.content.startswith(b"%PDF")


async def test_monthly_get_returns_202_while_generating(
    seeded: async_sessionmaker[AsyncSession],
) -> None:
    # 生成中（generating）の行を直接作り、GET が 202 を返すことを確認する。
    async with unit_of_work(seeded) as session:
        report = await SqlMonthlyReportRepository(session).create_generating(
            101, date(2026, 6, 1), [101]
        )
    monthly_id = report.id

    with _client() as client:
        got = client.get(f"/api/v1/monthly-reports/{monthly_id}", headers={"X-User-Id": "2"})
    assert got.status_code == 202
    assert got.json()["status"] == "generating"


async def test_branch_manager_cannot_generate_other_branch(
    seeded: async_sessionmaker[AsyncSession],
) -> None:
    # 東京支店管理者(1)が大阪物件(201)の月次を生成しようとすると 403。
    with _client() as client:
        resp = client.post(
            "/api/v1/monthly-reports",
            headers={"X-User-Id": "1"},
            json={"property_id": 201, "month": "2026-06-01"},
        )
    assert resp.status_code == 403


async def test_branch_manager_cannot_read_other_branch_monthly(
    seeded: async_sessionmaker[AsyncSession],
) -> None:
    # 大阪物件(201)の月次を作成 → 東京支店管理者(1)の GET は 403。
    async with unit_of_work(seeded) as session:
        report = await SqlMonthlyReportRepository(session).create_generating(
            201, date(2026, 6, 1), [201]
        )
    monthly_id = report.id

    with _client() as client:
        resp = client.get(f"/api/v1/monthly-reports/{monthly_id}", headers={"X-User-Id": "1"})
    assert resp.status_code == 403
