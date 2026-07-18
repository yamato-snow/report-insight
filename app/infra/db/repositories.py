"""リポジトリ実装（ReportRepository / SearchRepository）。認可はSQLで強制（DB設計書 §2）。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime

from sqlalchemy import ColumnElement, and_, func, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.entities import (
    MonthlyReport,
    MonthlyStats,
    Property,
    Report,
    ReportAnalysis,
    ReportListFilters,
    SearchFilters,
    SearchHit,
    User,
)
from app.domain.errors import NotFoundError, PermissionDeniedError
from app.domain.values import AnalysisStatus, Category, MonthlyStatus, Urgency
from app.infra.db import models
from app.infra.db.mappers import (
    analysis_to_domain,
    monthly_to_domain,
    property_to_domain,
    report_to_domain,
    user_to_domain,
)


class SqlUserRepository:
    """利用者の読み取り（認証バックエンドの解決に使用。基本設計 §3）。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: int) -> User:
        row = (
            await self._session.execute(select(models.User).where(models.User.id == user_id))
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError(f"user_id={user_id} は存在しません")
        return user_to_domain(row)

    async def list_properties(self, user: User) -> list[Property]:
        stmt = select(models.Property)
        if not user.is_qa:
            stmt = stmt.where(models.Property.branch_id == user.branch_id)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [property_to_domain(r) for r in rows]


class SqlReportRepository:
    """ReportRepository の SQLAlchemy 実装。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_ingested(
        self,
        report: Report,
        analysis: ReportAnalysis,
        chunks: Sequence[tuple[str, list[float]]],
    ) -> int | None:
        # source_key 冪等: 既存なら DO NOTHING（RETURNING が空 = 二重配信）
        stmt = (
            pg_insert(models.Report)
            .values(
                property_id=report.property_id,
                source_key=report.source_key,
                reported_at=report.reported_at,
                reporter_role=report.reporter_role,
                raw_text=report.raw_text,
                photo_meta=report.photo_meta,
            )
            .on_conflict_do_nothing(index_elements=["source_key"])
            .returning(models.Report.id)
        )
        result = await self._session.execute(stmt)
        report_id = result.scalar_one_or_none()
        if report_id is None:
            return None

        await self._session.execute(
            insert(models.ReportAnalysis).values(
                report_id=report_id,
                category=analysis.category.value,
                urgency=analysis.urgency.value,
                action_required=analysis.action_required,
                normalized_summary=analysis.normalized_summary,
                confidence=analysis.confidence,
                status=analysis.status.value,
                model_id=analysis.model_id,
                prompt_version=analysis.prompt_version,
                input_tokens=analysis.input_tokens,
                output_tokens=analysis.output_tokens,
            )
        )
        if chunks:
            await self._session.execute(
                insert(models.ReportChunk),
                [
                    {
                        "report_id": report_id,
                        "chunk_index": i,
                        "content": content,
                        "embedding": vector,
                    }
                    for i, (content, vector) in enumerate(chunks)
                ],
            )
        return report_id

    async def get(self, report_id: int, permitted_property_ids: Sequence[int]) -> Report:
        stmt = (
            select(models.Report)
            .options(selectinload(models.Report.analysis))
            .where(models.Report.id == report_id)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise NotFoundError(f"report_id={report_id} は存在しません")
        if row.property_id not in set(permitted_property_ids):
            raise PermissionDeniedError(f"report_id={report_id} へのアクセス権がありません")
        return report_to_domain(row)

    async def update_analysis(
        self,
        report_id: int,
        category: Category,
        urgency: Urgency,
        action_required: bool,
        permitted_property_ids: Sequence[int],
    ) -> ReportAnalysis:
        report = (
            await self._session.execute(select(models.Report).where(models.Report.id == report_id))
        ).scalar_one_or_none()
        if report is None:
            raise NotFoundError(f"report_id={report_id} は存在しません")
        if report.property_id not in set(permitted_property_ids):
            raise PermissionDeniedError(f"report_id={report_id} へのアクセス権がありません")

        analysis = (
            await self._session.execute(
                select(models.ReportAnalysis).where(models.ReportAnalysis.report_id == report_id)
            )
        ).scalar_one_or_none()
        if analysis is None:
            raise NotFoundError(f"report_id={report_id} の分析結果がありません")

        analysis.category = category.value
        analysis.urgency = urgency.value
        analysis.action_required = action_required
        analysis.status = AnalysisStatus.HUMAN_VERIFIED.value
        await self._session.flush()
        return analysis_to_domain(analysis)

    async def list_reports(
        self,
        filters: ReportListFilters,
        permitted_property_ids: Sequence[int],
        cursor: int | None,
        limit: int,
    ) -> list[Report]:
        if not permitted_property_ids:
            return []
        conditions: list[ColumnElement[bool]] = [
            models.Report.property_id.in_(list(permitted_property_ids)),
        ]
        if filters.property_id is not None:
            conditions.append(models.Report.property_id == filters.property_id)
        if filters.category is not None:
            conditions.append(models.ReportAnalysis.category == filters.category.value)
        if filters.urgency is not None:
            conditions.append(models.ReportAnalysis.urgency == filters.urgency.value)
        if filters.status is not None:
            conditions.append(models.ReportAnalysis.status == filters.status.value)
        if cursor is not None:
            conditions.append(models.Report.id < cursor)
        return await self._list_with_analysis(conditions, limit)

    async def review_queue(
        self,
        permitted_property_ids: Sequence[int],
        cursor: int | None,
        limit: int,
    ) -> list[Report]:
        if not permitted_property_ids:
            return []
        conditions: list[ColumnElement[bool]] = [
            models.Report.property_id.in_(list(permitted_property_ids)),
            models.ReportAnalysis.status == AnalysisStatus.NEEDS_REVIEW.value,
        ]
        if cursor is not None:
            conditions.append(models.Report.id < cursor)
        return await self._list_with_analysis(conditions, limit)

    async def _list_with_analysis(
        self, conditions: Sequence[ColumnElement[bool]], limit: int
    ) -> list[Report]:
        # analysis を条件に含めるため inner join。id 降順で安定したカーソルページング。
        stmt = (
            select(models.Report)
            .join(models.ReportAnalysis, models.ReportAnalysis.report_id == models.Report.id)
            .options(selectinload(models.Report.analysis))
            .where(and_(*conditions))
            .order_by(models.Report.id.desc())
            .limit(limit)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [report_to_domain(row) for row in rows]


class SqlSearchRepository:
    """SearchRepository の SQLAlchemy 実装。ハイブリッド検索・認可・引用検証。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def permitted_property_ids(self, user: User) -> list[int]:
        stmt = select(models.Property.id)
        if not user.is_qa:
            stmt = stmt.where(models.Property.branch_id == user.branch_id)
        rows = (await self._session.execute(stmt)).scalars().all()
        return list(rows)

    async def hybrid_search(
        self,
        query_vec: Sequence[float],
        filters: SearchFilters,
        permitted_property_ids: Sequence[int],
        limit: int,
    ) -> list[SearchHit]:
        if not permitted_property_ids:
            return []

        distance = models.ReportChunk.embedding.cosine_distance(list(query_vec))
        conditions: list[ColumnElement[bool]] = [
            models.Report.property_id.in_(list(permitted_property_ids)),
        ]
        if filters.property_id is not None:
            conditions.append(models.Report.property_id == filters.property_id)
        if filters.category is not None:
            conditions.append(models.ReportAnalysis.category == filters.category.value)
        if filters.from_ is not None:
            conditions.append(models.Report.reported_at >= filters.from_)
        if filters.to is not None:
            conditions.append(models.Report.reported_at <= filters.to)

        stmt = (
            select(
                models.Report.id,
                models.Report.property_id,
                models.ReportChunk.content,
                models.ReportAnalysis.normalized_summary,
                models.Report.reported_at,
                (1 - distance).label("similarity"),
            )
            .join(models.Report, models.Report.id == models.ReportChunk.report_id)
            .join(
                models.ReportAnalysis,
                models.ReportAnalysis.report_id == models.Report.id,
            )
            .where(and_(*conditions))
            .order_by(distance)
            .limit(limit)
        )
        rows = (await self._session.execute(stmt)).all()
        return [
            SearchHit(
                report_id=row.id,
                property_id=row.property_id,
                content=row.content,
                summary=row.normalized_summary,
                reported_at=row.reported_at,
                similarity=float(row.similarity),
            )
            for row in rows
        ]

    async def existing_report_ids(
        self, report_ids: Sequence[int], permitted_property_ids: Sequence[int]
    ) -> set[int]:
        if not report_ids or not permitted_property_ids:
            return set()
        stmt = select(models.Report.id).where(
            and_(
                models.Report.id.in_(list(report_ids)),
                models.Report.property_id.in_(list(permitted_property_ids)),
            )
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return set(rows)


def _month_bounds(month: date) -> tuple[datetime, datetime]:
    """対象月の [月初, 翌月初) を timezone-aware で返す。"""
    start = datetime(month.year, month.month, 1, tzinfo=UTC)
    if month.month == 12:
        end = datetime(month.year + 1, 1, 1, tzinfo=UTC)
    else:
        end = datetime(month.year, month.month + 1, 1, tzinfo=UTC)
    return start, end


class SqlMonthlyReportRepository:
    """MonthlyReportRepository の SQLAlchemy 実装（F-3）。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def compute_stats(self, property_id: int, month: date) -> MonthlyStats:
        start, end = _month_bounds(month)
        month_filter = and_(
            models.Report.property_id == property_id,
            models.Report.reported_at >= start,
            models.Report.reported_at < end,
        )

        by_category: dict[Category, int] = {}
        cat_stmt = (
            select(models.ReportAnalysis.category, func.count().label("n"))
            .join(models.Report, models.Report.id == models.ReportAnalysis.report_id)
            .where(month_filter)
            .group_by(models.ReportAnalysis.category)
        )
        for category_value, n in (await self._session.execute(cat_stmt)).all():
            by_category[Category(category_value)] = int(n)

        by_urgency: dict[Urgency, int] = {}
        urg_stmt = (
            select(models.ReportAnalysis.urgency, func.count().label("n"))
            .join(models.Report, models.Report.id == models.ReportAnalysis.report_id)
            .where(month_filter)
            .group_by(models.ReportAnalysis.urgency)
        )
        for urgency_value, n in (await self._session.execute(urg_stmt)).all():
            by_urgency[Urgency(urgency_value)] = int(n)

        total = sum(by_category.values())
        action_stmt = (
            select(func.count())
            .select_from(models.ReportAnalysis)
            .join(models.Report, models.Report.id == models.ReportAnalysis.report_id)
            .where(and_(month_filter, models.ReportAnalysis.action_required.is_(True)))
        )
        action_required = int((await self._session.execute(action_stmt)).scalar_one())

        return MonthlyStats(
            property_id=property_id,
            month=month,
            total=total,
            by_category=by_category,
            by_urgency=by_urgency,
            action_required=action_required,
        )

    async def property_name(self, property_id: int) -> str:
        name = (
            await self._session.execute(
                select(models.Property.name).where(models.Property.id == property_id)
            )
        ).scalar_one_or_none()
        if name is None:
            raise NotFoundError(f"property_id={property_id} は存在しません")
        return name

    async def create_generating(
        self, property_id: int, month: date, permitted_property_ids: Sequence[int]
    ) -> MonthlyReport:
        if property_id not in set(permitted_property_ids):
            raise PermissionDeniedError(f"property_id={property_id} へのアクセス権がありません")

        current_max = (
            await self._session.execute(
                select(func.max(models.MonthlyReport.version)).where(
                    and_(
                        models.MonthlyReport.property_id == property_id,
                        models.MonthlyReport.month == month,
                    )
                )
            )
        ).scalar_one_or_none()
        version = (current_max or 0) + 1

        row_id = (
            await self._session.execute(
                insert(models.MonthlyReport)
                .values(
                    property_id=property_id,
                    month=month,
                    version=version,
                    body_markdown="",
                    status=MonthlyStatus.GENERATING.value,
                )
                .returning(models.MonthlyReport.id)
            )
        ).scalar_one()
        return await self.get_internal(row_id)

    async def get(self, monthly_id: int, permitted_property_ids: Sequence[int]) -> MonthlyReport:
        report = await self.get_internal(monthly_id)
        if report.property_id not in set(permitted_property_ids):
            raise PermissionDeniedError(f"monthly_id={monthly_id} へのアクセス権がありません")
        return report

    async def get_internal(self, monthly_id: int) -> MonthlyReport:
        row = (
            await self._session.execute(
                select(models.MonthlyReport).where(models.MonthlyReport.id == monthly_id)
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError(f"monthly_id={monthly_id} は存在しません")
        return monthly_to_domain(row)

    async def set_body(
        self, monthly_id: int, body_markdown: str, status: MonthlyStatus
    ) -> MonthlyReport:
        row = (
            await self._session.execute(
                select(models.MonthlyReport).where(models.MonthlyReport.id == monthly_id)
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError(f"monthly_id={monthly_id} は存在しません")
        row.body_markdown = body_markdown
        row.status = status.value
        await self._session.flush()
        return monthly_to_domain(row)

    async def approve(
        self, monthly_id: int, approver_id: int, approved_at: datetime
    ) -> MonthlyReport:
        row = (
            await self._session.execute(
                select(models.MonthlyReport).where(models.MonthlyReport.id == monthly_id)
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError(f"monthly_id={monthly_id} は存在しません")
        row.status = MonthlyStatus.APPROVED.value
        row.approved_by = approver_id
        row.approved_at = approved_at
        await self._session.flush()
        return monthly_to_domain(row)


class SqlAuditRepository:
    """AuditPort の SQLAlchemy 実装（検索・承認・分類上書きの追記専用ログ）。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(self, *, user_id: int, action: str, payload: dict[str, object]) -> None:
        await self._session.execute(
            insert(models.AuditLog).values(user_id=user_id, action=action, payload=payload)
        )
