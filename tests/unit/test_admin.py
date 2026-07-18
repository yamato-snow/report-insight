"""F-4 AdminService の unit テスト（フィルタ委譲・分類上書き＋監査記録）。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from app.domain.entities import Property, Report, ReportAnalysis, ReportListFilters, User
from app.domain.values import AnalysisStatus, Category, Role, Urgency
from app.services.admin import AdminService
from tests.unit.fakes import FakeAudit


class FakePermissions:
    def __init__(self, permitted: list[int]) -> None:
        self._permitted = permitted

    async def permitted_property_ids(self, user: User) -> list[int]:
        return self._permitted


class FakePropertyLister:
    def __init__(self, props: list[Property]) -> None:
        self._props = props

    async def list_properties(self, user: User) -> list[Property]:
        return self._props


def _analysis(status: AnalysisStatus = AnalysisStatus.AUTO_CLASSIFIED) -> ReportAnalysis:
    return ReportAnalysis(
        report_id=1,
        category=Category.OTHER,
        urgency=Urgency.LOW,
        action_required=False,
        normalized_summary="要約",
        confidence=0.9,
        status=status,
        model_id="fake",
        prompt_version="v1",
    )


def _report(report_id: int, *, status: AnalysisStatus) -> Report:
    return Report(
        id=report_id,
        property_id=101,
        source_key=f"k{report_id}",
        reported_at=datetime(2026, 6, 1, tzinfo=UTC),
        reporter_role="staff",
        raw_text="本文",
        analysis=_analysis(status),
    )


class FakeReportRepo:
    def __init__(self, reports: list[Report]) -> None:
        self._reports = reports
        self.update_calls: list[tuple[int, Category, Urgency, bool]] = []

    async def list_reports(
        self,
        filters: ReportListFilters,
        permitted_property_ids: Sequence[int],
        cursor: int | None,
        limit: int,
    ) -> list[Report]:
        return [r for r in self._reports if r.property_id in set(permitted_property_ids)][:limit]

    async def review_queue(
        self, permitted_property_ids: Sequence[int], cursor: int | None, limit: int
    ) -> list[Report]:
        return [
            r
            for r in self._reports
            if r.property_id in set(permitted_property_ids)
            and r.analysis is not None
            and r.analysis.status is AnalysisStatus.NEEDS_REVIEW
        ][:limit]

    async def get(self, report_id: int, permitted_property_ids: Sequence[int]) -> Report:
        raise NotImplementedError

    async def update_analysis(
        self,
        report_id: int,
        category: Category,
        urgency: Urgency,
        action_required: bool,
        permitted_property_ids: Sequence[int],
    ) -> ReportAnalysis:
        self.update_calls.append((report_id, category, urgency, action_required))
        return _analysis(AnalysisStatus.HUMAN_VERIFIED)

    async def upsert_ingested(self, *args: object, **kwargs: object) -> int | None:
        raise NotImplementedError


_QA = User(id=2, email="qa@e.com", role=Role.QA, branch_id=None)


def _service(repo: FakeReportRepo, permitted: list[int]) -> tuple[AdminService, FakeAudit]:
    audit = FakeAudit()
    service = AdminService(
        reports=repo,
        properties=FakePropertyLister([]),
        audit=audit,
        permissions=FakePermissions(permitted),
    )
    return service, audit


async def test_review_queue_returns_only_needs_review() -> None:
    reports = [
        _report(1, status=AnalysisStatus.AUTO_CLASSIFIED),
        _report(2, status=AnalysisStatus.NEEDS_REVIEW),
    ]
    service, _ = _service(FakeReportRepo(reports), [101])
    queue = await service.review_queue(_QA, None, 20)
    assert [r.id for r in queue] == [2]


async def test_override_analysis_records_audit() -> None:
    repo = FakeReportRepo([_report(1, status=AnalysisStatus.NEEDS_REVIEW)])
    service, audit = _service(repo, [101])

    result = await service.override_analysis(
        _QA, 1, Category.EQUIPMENT_FAILURE, Urgency.HIGH, action_required=True
    )
    assert result.status is AnalysisStatus.HUMAN_VERIFIED
    assert repo.update_calls == [(1, Category.EQUIPMENT_FAILURE, Urgency.HIGH, True)]
    assert audit.records and audit.records[0]["action"] == "override_analysis"


async def test_list_reports_scoped_to_permitted() -> None:
    reports = [_report(1, status=AnalysisStatus.AUTO_CLASSIFIED)]
    service, _ = _service(FakeReportRepo(reports), [])  # 権限ゼロ
    assert await service.list_reports(_QA, ReportListFilters(), None, 20) == []
