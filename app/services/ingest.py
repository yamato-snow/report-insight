"""F-1 取込パイプライン: 取込→マスキング→構造化→埋め込み→保存→通知（基本設計 §2.1）。

外部I/Oはすべてポート経由。閾値・分岐などのビジネス判断はこの層に閉じる（規約 §2）。
"""

from __future__ import annotations

import json

from pydantic import BaseModel

from app.core.logging import get_logger
from app.domain.entities import (
    IngestMessage,
    Report,
    ReportAnalysis,
)
from app.domain.values import LONG_TEXT_CHARS, AnalysisStatus, Urgency
from app.services.ports import (
    EmbeddingClient,
    LLMClient,
    NotificationPort,
    ObjectStoragePort,
    PIIMaskerPort,
    ReportRepository,
)

logger = get_logger(__name__)


class IngestOutcome(BaseModel):
    """取込結果（worker/テストの検証用）。"""

    source_key: str
    report_id: int | None
    status: AnalysisStatus
    duplicate: bool
    notified: bool


class IngestService:
    """報告書1件の取込ユースケース。worker が1メッセージごとに呼ぶ。"""

    def __init__(
        self,
        *,
        storage: ObjectStoragePort,
        masker: PIIMaskerPort,
        llm: LLMClient,
        embedder: EmbeddingClient,
        repository: ReportRepository,
        notifier: NotificationPort,
        confidence_threshold: float,
    ) -> None:
        self._storage = storage
        self._masker = masker
        self._llm = llm
        self._embedder = embedder
        self._repo = repository
        self._notifier = notifier
        self._threshold = confidence_threshold

    async def ingest_from_key(self, source_key: str) -> IngestOutcome:
        """S3オブジェクトキーから報告書を取り込み構造化・保存する。

        Args:
            source_key: 冪等性キー（S3オブジェクトキー。DB設計書 §2）。
        """
        log = logger.bind(source_key=source_key)
        raw = await self._storage.get_object(source_key)
        message = IngestMessage.model_validate_json(raw)

        # PIIマスキング後のテキストのみ LLM API に送る（LLM設計書 §3）
        masked = await self._masker.mask(message.raw_text)
        envelope = await self._llm.classify_report(masked.masked_text)
        result = envelope.result

        status = (
            AnalysisStatus.NEEDS_REVIEW
            if result.confidence < self._threshold
            else AnalysisStatus.AUTO_CLASSIFIED
        )

        chunks_text = _build_chunks(result.normalized_summary, message.raw_text)
        vectors = await self._embedder.embed_documents(chunks_text)
        chunks = list(zip(chunks_text, vectors, strict=True))

        report = Report(
            property_id=message.property_id,
            source_key=message.source_key,
            reported_at=message.reported_at,
            reporter_role=message.reporter_role,
            raw_text=message.raw_text,
            photo_meta=message.photo_meta,
        )
        analysis = ReportAnalysis(
            report_id=0,  # 保存時に確定
            category=result.category,
            urgency=result.urgency,
            action_required=result.action_required,
            normalized_summary=result.normalized_summary,
            confidence=result.confidence,
            status=status,
            model_id=envelope.meta.model_id,
            prompt_version=envelope.meta.prompt_version,
            input_tokens=envelope.meta.input_tokens,
            output_tokens=envelope.meta.output_tokens,
        )

        report_id = await self._repo.upsert_ingested(report, analysis, chunks)
        if report_id is None:
            # 冪等: 既存のため二重登録・二重通知しない（基本設計 §2.1）
            log.info("ingest.duplicate_skipped")
            return IngestOutcome(
                source_key=source_key,
                report_id=None,
                status=status,
                duplicate=True,
                notified=False,
            )

        notified = False
        if result.urgency is Urgency.HIGH:
            report.id = report_id
            analysis.report_id = report_id
            await self._notifier.notify_urgent(report, analysis)
            notified = True

        log.info(
            "ingest.completed",
            report_id=report_id,
            category=result.category,
            urgency=result.urgency,
            status=status,
            confidence=round(result.confidence, 3),
            input_tokens=envelope.meta.input_tokens,
            output_tokens=envelope.meta.output_tokens,
            model_id=envelope.meta.model_id,
        )
        return IngestOutcome(
            source_key=source_key,
            report_id=report_id,
            status=status,
            duplicate=False,
            notified=notified,
        )


def _build_chunks(normalized_summary: str, raw_text: str) -> list[str]:
    """チャンク生成（DB設計書 §2: 原則1報告書=1チャンク、長文のみ意味段落で分割）。

    正規化サマリ＋原文を結合し、正規化語彙が検索にヒットしやすくする（表記ゆれ対策）。
    """
    if len(raw_text) <= LONG_TEXT_CHARS:
        return [f"{normalized_summary}\n\n{raw_text}"]

    paragraphs = [p.strip() for p in raw_text.split("\n\n") if p.strip()]
    if not paragraphs:
        return [f"{normalized_summary}\n\n{raw_text}"]
    # 先頭チャンクにサマリを載せ、以降は段落単位
    chunks = [f"{normalized_summary}\n\n{paragraphs[0]}"]
    chunks.extend(paragraphs[1:])
    return chunks


def parse_s3_event(body: str) -> list[str]:
    """SQS が受け取った S3 イベント通知から object key を抽出する。

    LocalStack / 本番 S3 のイベント JSON 双方に対応。テストキー入力（プレーン文字列）も許容。
    """
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return [body]

    records = payload.get("Records") if isinstance(payload, dict) else None
    if not records:
        # {"source_key": "..."} 形式の直接指定も許容
        if isinstance(payload, dict) and "source_key" in payload:
            return [str(payload["source_key"])]
        return []

    keys: list[str] = []
    for record in records:
        s3 = record.get("s3", {})
        key = s3.get("object", {}).get("key")
        if key:
            keys.append(str(key))
    return keys
