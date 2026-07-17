"""F-1 取込サービスの unit テスト（Fakeポートのみ・外部I/Oゼロ）。"""

from __future__ import annotations

import json

import pytest

from app.domain.values import AnalysisStatus, Category, Urgency
from app.infra.embedding.fake_client import FakeEmbeddingClient
from app.infra.llm.fake_client import FakeLLMClient
from app.services.ingest import IngestService, parse_s3_event
from tests.unit.fakes import (
    FakeMasker,
    FakeNotifier,
    FakeReportRepository,
    FakeStorage,
)


def _message(raw_text: str, *, source_key: str = "reports/a.json") -> bytes:
    return json.dumps(
        {
            "source_key": source_key,
            "property_id": 101,
            "reported_at": "2026-06-01T09:00:00+00:00",
            "reporter_role": "巡回スタッフ",
            "raw_text": raw_text,
            "photo_meta": {},
        }
    ).encode("utf-8")


def _service(storage: FakeStorage, repo: FakeReportRepository, notifier: FakeNotifier):
    return IngestService(
        storage=storage,
        masker=FakeMasker(),
        llm=FakeLLMClient(),
        embedder=FakeEmbeddingClient(dim=64),
        repository=repo,
        notifier=notifier,
        confidence_threshold=0.85,
    )


async def test_ingest_low_confidence_marks_needs_review() -> None:
    storage = FakeStorage({"reports/a.json": _message("状況不明。詳細は曖昧。")})
    repo = FakeReportRepository()
    notifier = FakeNotifier()

    outcome = await _service(storage, repo, notifier).ingest_from_key("reports/a.json")

    assert outcome.status is AnalysisStatus.NEEDS_REVIEW
    assert outcome.duplicate is False


async def test_ingest_high_urgency_notifies() -> None:
    storage = FakeStorage({"reports/a.json": _message("3階廊下で漏水。至急対応願います。")})
    repo = FakeReportRepository()
    notifier = FakeNotifier()

    outcome = await _service(storage, repo, notifier).ingest_from_key("reports/a.json")

    assert outcome.notified is True
    assert len(notifier.calls) == 1
    _, analysis = notifier.calls[0]
    assert analysis.urgency is Urgency.HIGH


async def test_ingest_normal_is_auto_classified_no_notify() -> None:
    storage = FakeStorage({"reports/a.json": _message("共用部の廊下を清掃しました。")})
    repo = FakeReportRepository()
    notifier = FakeNotifier()

    outcome = await _service(storage, repo, notifier).ingest_from_key("reports/a.json")

    assert outcome.status is AnalysisStatus.AUTO_CLASSIFIED
    assert outcome.notified is False
    assert notifier.calls == []


async def test_ingest_duplicate_skips_notify() -> None:
    storage = FakeStorage({"reports/a.json": _message("3階廊下で漏水。至急対応。")})
    repo = FakeReportRepository(force_duplicate=True)
    notifier = FakeNotifier()

    outcome = await _service(storage, repo, notifier).ingest_from_key("reports/a.json")

    assert outcome.duplicate is True
    assert outcome.report_id is None
    assert notifier.calls == []


async def test_ingest_boundary_cleaning_with_breakage_is_equipment() -> None:
    storage = FakeStorage({"reports/a.json": _message("清掃中に給水管の破損を発見しました。")})
    repo = FakeReportRepository()

    await _service(storage, repo, FakeNotifier()).ingest_from_key("reports/a.json")

    _, analysis, _ = repo.saved[0]
    assert analysis.category is Category.EQUIPMENT_FAILURE


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (
            json.dumps({"Records": [{"s3": {"object": {"key": "reports/x.json"}}}]}),
            ["reports/x.json"],
        ),
        (json.dumps({"source_key": "reports/y.json"}), ["reports/y.json"]),
        ("reports/plain.json", ["reports/plain.json"]),
        (json.dumps({"Records": []}), []),
    ],
)
def test_parse_s3_event(body: str, expected: list[str]) -> None:
    assert parse_s3_event(body) == expected
