"""F-3 月次報告書サービスの unit テスト（Fake ポートで状態機械・確定計算を検証）。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime

import pytest

from app.domain.entities import LLMCallMeta, MonthlyNarration, MonthlyReport, MonthlyStats, User
from app.domain.errors import InvalidStateError, PermissionDeniedError
from app.domain.values import Category, MonthlyStatus, Role, Urgency
from app.infra.llm.fake_client import FakeLLMClient
from app.services.monthly import MonthlyService, render_monthly_markdown
from tests.unit.fakes import FakeAudit

_MONTH = date(2026, 6, 1)


class FakePermissions:
    def __init__(self, permitted: list[int]) -> None:
        self._permitted = permitted

    async def permitted_property_ids(self, user: User) -> list[int]:
        return self._permitted


class FakeMonthlyRepo:
    """MonthlyReportRepository の決定的 Fake（in-memory）。"""

    def __init__(self, *, stats: MonthlyStats, property_name: str = "物件A") -> None:
        self._stats = stats
        self._name = property_name
        self._rows: dict[int, MonthlyReport] = {}
        self._next_id = 1

    async def compute_stats(self, property_id: int, month: date) -> MonthlyStats:
        return self._stats

    async def property_name(self, property_id: int) -> str:
        return self._name

    async def create_generating(
        self, property_id: int, month: date, permitted_property_ids: Sequence[int]
    ) -> MonthlyReport:
        if property_id not in set(permitted_property_ids):
            raise PermissionDeniedError("範囲外")
        version = 1 + sum(
            1 for r in self._rows.values() if r.property_id == property_id and r.month == month
        )
        report = MonthlyReport(
            id=self._next_id,
            property_id=property_id,
            month=month,
            version=version,
            body_markdown="",
            status=MonthlyStatus.GENERATING,
        )
        self._rows[self._next_id] = report
        self._next_id += 1
        return report

    async def get(self, monthly_id: int, permitted_property_ids: Sequence[int]) -> MonthlyReport:
        report = await self.get_internal(monthly_id)
        if report.property_id not in set(permitted_property_ids):
            raise PermissionDeniedError("範囲外")
        return report

    async def get_internal(self, monthly_id: int) -> MonthlyReport:
        return self._rows[monthly_id]

    async def set_body(
        self, monthly_id: int, body_markdown: str, status: MonthlyStatus
    ) -> MonthlyReport:
        row = self._rows[monthly_id]
        updated = row.model_copy(update={"body_markdown": body_markdown, "status": status})
        self._rows[monthly_id] = updated
        return updated

    async def approve(
        self, monthly_id: int, approver_id: int, approved_at: datetime
    ) -> MonthlyReport:
        row = self._rows[monthly_id]
        updated = row.model_copy(
            update={
                "status": MonthlyStatus.APPROVED,
                "approved_by": approver_id,
                "approved_at": approved_at,
            }
        )
        self._rows[monthly_id] = updated
        return updated


def _stats(total: int = 3) -> MonthlyStats:
    return MonthlyStats(
        property_id=101,
        month=_MONTH,
        total=total,
        by_category={Category.EQUIPMENT_FAILURE: 2, Category.CLEANING: 1},
        by_urgency={Urgency.HIGH: 1, Urgency.LOW: 2},
        action_required=2,
    )


def _service(repo: FakeMonthlyRepo, *, permitted: list[int]) -> tuple[MonthlyService, FakeAudit]:
    audit = FakeAudit()
    service = MonthlyService(
        llm=FakeLLMClient(),
        repository=repo,
        audit=audit,
        permissions=FakePermissions(permitted),
    )
    return service, audit


_QA = User(id=2, email="qa@e.com", role=Role.QA, branch_id=None)


async def test_lifecycle_generate_draft_approve() -> None:
    repo = FakeMonthlyRepo(stats=_stats())
    service, audit = _service(repo, permitted=[101])

    created = await service.request_generation(_QA, 101, _MONTH)
    assert created.status is MonthlyStatus.GENERATING
    assert created.version == 1

    drafted = await service.run_generation(created.id or 0)
    assert drafted.status is MonthlyStatus.DRAFT
    # 確定計算の数値が本文に含まれる（数表は stats 由来）
    assert "総報告件数: 3 件" in drafted.body_markdown
    assert "## 所見" in drafted.body_markdown

    edited = await service.save_draft(_QA, created.id or 0, drafted.body_markdown + "\n追記")
    assert edited.body_markdown.endswith("追記")

    approved = await service.approve(_QA, created.id or 0)
    assert approved.status is MonthlyStatus.APPROVED
    assert approved.approved_by == _QA.id
    # 承認は監査ログに記録される
    assert audit.records and audit.records[0]["action"] == "approve_monthly"


async def test_edit_after_approved_is_invalid_state() -> None:
    repo = FakeMonthlyRepo(stats=_stats())
    service, _ = _service(repo, permitted=[101])
    created = await service.request_generation(_QA, 101, _MONTH)
    await service.run_generation(created.id or 0)
    await service.approve(_QA, created.id or 0)

    with pytest.raises(InvalidStateError):
        await service.save_draft(_QA, created.id or 0, "承認後の編集")
    with pytest.raises(InvalidStateError):
        await service.approve(_QA, created.id or 0)


async def test_regeneration_bumps_version() -> None:
    repo = FakeMonthlyRepo(stats=_stats())
    service, _ = _service(repo, permitted=[101])
    first = await service.request_generation(_QA, 101, _MONTH)
    second = await service.request_generation(_QA, 101, _MONTH)
    assert (first.version, second.version) == (1, 2)


async def test_generate_out_of_scope_property_forbidden() -> None:
    repo = FakeMonthlyRepo(stats=_stats())
    service, _ = _service(repo, permitted=[999])  # 101 は範囲外
    with pytest.raises(PermissionDeniedError):
        await service.request_generation(_QA, 101, _MONTH)


def test_render_markdown_uses_confirmed_counts() -> None:
    stats = _stats(total=5)
    narration = MonthlyNarration(
        body="所見テキスト",
        meta=LLMCallMeta(model_id="x", prompt_version="monthly_v1"),
    )
    md = render_monthly_markdown("物件A", stats, narration)
    assert "総報告件数: 5 件" in md
    assert "| 設備不具合 | 2 |" in md
    assert "所見テキスト" in md
