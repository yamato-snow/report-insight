"""Slack Incoming Webhook 通知（緊急度「高」。基本設計 §2.1 / LLM設計書 §7）。

LLM出力が引き起こす自動アクションは「通知」のみ（状態変更は人間の操作を経る）。
"""

from __future__ import annotations

import httpx

from app.core.logging import get_logger
from app.domain.entities import Report, ReportAnalysis

logger = get_logger(__name__)


class SlackNotifier:
    """NotificationPort の Slack 実装。"""

    def __init__(self, webhook_url: str, timeout_seconds: float = 5.0) -> None:
        self._webhook_url = webhook_url
        self._timeout = timeout_seconds

    async def notify_urgent(self, report: Report, analysis: ReportAnalysis) -> None:
        payload = {
            "text": (
                f"🚨 緊急度「高」の報告書を検知しました\n"
                f"・report_id: {report.id}\n"
                f"・物件ID: {report.property_id}\n"
                f"・事象: {analysis.category.value}\n"
                f"・要約: {analysis.normalized_summary}\n"
                f"・報告日時: {report.reported_at.isoformat()}"
            ),
            "report_id": report.id,
            "property_id": report.property_id,
            "category": analysis.category.value,
            "urgency": analysis.urgency.value,
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(self._webhook_url, json=payload)
            response.raise_for_status()
        logger.info("notify.urgent_sent", report_id=report.id)
