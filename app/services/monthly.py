"""F-3 月次報告書: 件数サマリの確定計算 → LLM 文章化 → 承認 → PDF（基本設計 §2.3 / 05 §2）。

数値は SQL の確定計算（MonthlyStats）のみを正とし、LLM には文章化だけを任せる
（数値ハルシネーション防止）。状態機械 generating→draft→(approve)→approved はこの層に閉じ、
approved 後の編集は InvalidStateError（→422）で拒否する。
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.core.logging import get_logger
from app.domain.entities import MonthlyNarration, MonthlyReport, MonthlyStats, User
from app.domain.errors import InvalidStateError
from app.domain.values import AuditAction, Category, MonthlyStatus, Urgency
from app.services.ports import (
    AuditPort,
    LLMClient,
    MonthlyReportRepository,
    PermissionResolver,
)

logger = get_logger(__name__)

_CATEGORY_LABELS: dict[Category, str] = {
    Category.CLEANING: "清掃",
    Category.EQUIPMENT_FAILURE: "設備不具合",
    Category.CLAIM: "苦情・要望",
    Category.OTHER: "その他",
}
_URGENCY_LABELS: dict[Urgency, str] = {
    Urgency.HIGH: "高",
    Urgency.MEDIUM: "中",
    Urgency.LOW: "低",
}


class MonthlyService:
    """月次報告書ユースケース。生成は非同期（202→ポーリング）で run_generation が担う。"""

    def __init__(
        self,
        *,
        llm: LLMClient,
        repository: MonthlyReportRepository,
        audit: AuditPort,
        permissions: PermissionResolver,
    ) -> None:
        self._llm = llm
        self._repo = repository
        self._audit = audit
        self._permissions = permissions

    async def request_generation(self, user: User, property_id: int, month: date) -> MonthlyReport:
        """新しい生成ジョブを登録（status=generating・version+1）して即返す。

        month は月初に正規化して保存。範囲外物件は PermissionDenied（→403）。
        """
        first_of_month = month.replace(day=1)
        permitted = await self._permissions.permitted_property_ids(user)
        report = await self._repo.create_generating(property_id, first_of_month, permitted)
        logger.info(
            "monthly.requested",
            monthly_id=report.id,
            property_id=property_id,
            month=first_of_month.isoformat(),
            version=report.version,
        )
        return report

    async def run_generation(self, monthly_id: int) -> MonthlyReport:
        """生成本体（バックグラウンド・システム実行）。集計→文章化→draft 転移。

        失敗時は status=failed に倒して例外を送出する（呼び出し側でログ）。
        """
        report = await self._repo.get_internal(monthly_id)
        try:
            stats = await self._repo.compute_stats(report.property_id, report.month)
            name = await self._repo.property_name(report.property_id)
            narration = await self._llm.narrate_monthly(property_name=name, stats=stats)
            body = render_monthly_markdown(name, stats, narration)
            drafted = await self._repo.set_body(monthly_id, body, MonthlyStatus.DRAFT)
        except Exception:
            await self._repo.set_body(monthly_id, report.body_markdown, MonthlyStatus.FAILED)
            logger.exception("monthly.generation_failed", monthly_id=monthly_id)
            raise
        logger.info(
            "monthly.drafted",
            monthly_id=monthly_id,
            total=stats.total,
            input_tokens=narration.meta.input_tokens,
            output_tokens=narration.meta.output_tokens,
        )
        return drafted

    async def get(self, user: User, monthly_id: int) -> MonthlyReport:
        permitted = await self._permissions.permitted_property_ids(user)
        return await self._repo.get(monthly_id, permitted)

    async def save_draft(self, user: User, monthly_id: int, body_markdown: str) -> MonthlyReport:
        """draft の本文を人手修正して保存。approved 後や生成中の編集は拒否（→422）。"""
        permitted = await self._permissions.permitted_property_ids(user)
        report = await self._repo.get(monthly_id, permitted)
        if report.status is not MonthlyStatus.DRAFT:
            raise InvalidStateError(
                f"status={report.status} の月次報告書は編集できません（draft のみ可）"
            )
        return await self._repo.set_body(monthly_id, body_markdown, MonthlyStatus.DRAFT)

    async def approve(self, user: User, monthly_id: int) -> MonthlyReport:
        """draft を承認して確定。承認は監査ログに記録する（09 §6）。"""
        permitted = await self._permissions.permitted_property_ids(user)
        report = await self._repo.get(monthly_id, permitted)
        if report.status is not MonthlyStatus.DRAFT:
            raise InvalidStateError(
                f"status={report.status} の月次報告書は承認できません（draft のみ可）"
            )
        approved = await self._repo.approve(monthly_id, user.id, datetime.now(UTC))
        await self._audit.record(
            user_id=user.id,
            action=AuditAction.APPROVE_MONTHLY.value,
            payload={
                "monthly_id": monthly_id,
                "property_id": approved.property_id,
                "month": approved.month.isoformat(),
                "version": approved.version,
            },
        )
        logger.info("monthly.approved", monthly_id=monthly_id, approver_id=user.id)
        return approved


def render_monthly_markdown(
    property_name: str, stats: MonthlyStats, narration: MonthlyNarration
) -> str:
    """本文 Markdown を確定生成する。数表は stats（確定値）から、所見は LLM 散文から。"""
    title = f"{stats.month.year}年{stats.month.month}月 {property_name} 月次報告"
    lines = [
        f"# {title}",
        "",
        "## 概要",
        "",
        f"- 総報告件数: {stats.total} 件",
        f"- 要対応件数: {stats.action_required} 件",
        "",
        "## 分類別件数",
        "",
        "| 分類 | 件数 |",
        "| --- | ---: |",
    ]
    for category in Category:
        lines.append(f"| {_CATEGORY_LABELS[category]} | {stats.by_category.get(category, 0)} |")
    lines += [
        "",
        "## 緊急度別件数",
        "",
        "| 緊急度 | 件数 |",
        "| --- | ---: |",
    ]
    for urgency in Urgency:
        lines.append(f"| {_URGENCY_LABELS[urgency]} | {stats.by_urgency.get(urgency, 0)} |")
    lines += [
        "",
        "## 所見",
        "",
        narration.body.strip(),
        "",
    ]
    return "\n".join(lines)
