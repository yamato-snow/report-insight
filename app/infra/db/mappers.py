"""ORM ⇔ ドメインエンティティの変換（アーキテクチャ規約 §4: ORMは infra に閉じる）。"""

from __future__ import annotations

from app.domain.entities import Property, Report, ReportAnalysis, User
from app.domain.values import AnalysisStatus, Category, Role, Urgency
from app.infra.db import models


def user_to_domain(row: models.User) -> User:
    return User(
        id=row.id,
        email=row.email,
        role=Role(row.role),
        branch_id=row.branch_id,
    )


def property_to_domain(row: models.Property) -> Property:
    return Property(
        id=row.id,
        branch_id=row.branch_id,
        name=row.name,
        address=row.address,
    )


def analysis_to_domain(row: models.ReportAnalysis) -> ReportAnalysis:
    return ReportAnalysis(
        report_id=row.report_id,
        category=Category(row.category),
        urgency=Urgency(row.urgency),
        action_required=row.action_required,
        normalized_summary=row.normalized_summary,
        confidence=row.confidence,
        status=AnalysisStatus(row.status),
        model_id=row.model_id,
        prompt_version=row.prompt_version,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        analyzed_at=row.analyzed_at,
    )


def report_to_domain(row: models.Report) -> Report:
    return Report(
        id=row.id,
        property_id=row.property_id,
        source_key=row.source_key,
        reported_at=row.reported_at,
        reporter_role=row.reporter_role,
        raw_text=row.raw_text,
        photo_meta=dict(row.photo_meta or {}),
        created_at=row.created_at,
        analysis=analysis_to_domain(row.analysis) if row.analysis else None,
    )
