"""unit テスト用の Fake ポート実装（外部I/Oゼロ。コーディング規約 §6）。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from app.domain.entities import (
    LLMCallMeta,
    MaskingResult,
    Report,
    ReportAnalysis,
    SearchFilters,
    SearchHit,
    User,
)
from app.domain.values import AnalysisStatus, Category, Urgency


class FakeStorage:
    def __init__(self, objects: dict[str, bytes] | None = None) -> None:
        self.objects = objects or {}

    async def get_object(self, key: str) -> bytes:
        return self.objects[key]

    async def put_object(self, key: str, body: bytes) -> None:
        self.objects[key] = body


class FakeMasker:
    """マスキングを検証しないテスト用の恒等マスカ。"""

    async def mask(self, text: str) -> MaskingResult:
        return MaskingResult(masked_text=text, mapping={})


class FakeNotifier:
    def __init__(self) -> None:
        self.calls: list[tuple[Report, ReportAnalysis]] = []

    async def notify_urgent(self, report: Report, analysis: ReportAnalysis) -> None:
        self.calls.append((report, analysis))


class FakeReportRepository:
    def __init__(self, *, force_duplicate: bool = False) -> None:
        self.force_duplicate = force_duplicate
        self.saved: list[tuple[Report, ReportAnalysis, list]] = []
        self._next_id = 1
        self._seen_keys: set[str] = set()

    async def upsert_ingested(
        self,
        report: Report,
        analysis: ReportAnalysis,
        chunks: Sequence[tuple[str, list[float]]],
    ) -> int | None:
        if self.force_duplicate or report.source_key in self._seen_keys:
            return None
        self._seen_keys.add(report.source_key)
        report_id = self._next_id
        self._next_id += 1
        self.saved.append((report, analysis, list(chunks)))
        return report_id

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
        raise NotImplementedError


class FakeSearchRepository:
    def __init__(
        self,
        *,
        permitted: list[int] | None = None,
        hits: list[SearchHit] | None = None,
        existing: set[int] | None = None,
    ) -> None:
        self._permitted = permitted if permitted is not None else [101]
        self._hits = hits or []
        self._existing = existing

    async def permitted_property_ids(self, user: User) -> list[int]:
        return self._permitted

    async def hybrid_search(
        self,
        query_vec: Sequence[float],
        filters: SearchFilters,
        permitted_property_ids: Sequence[int],
        limit: int,
    ) -> list[SearchHit]:
        return self._hits[:limit]

    async def existing_report_ids(
        self, report_ids: Sequence[int], permitted_property_ids: Sequence[int]
    ) -> set[int]:
        if self._existing is not None:
            return {rid for rid in report_ids if rid in self._existing}
        # 既定は hits に含まれる report_id を実在とみなす
        real = {h.report_id for h in self._hits}
        return {rid for rid in report_ids if rid in real}


class CitingFakeLLM:
    """指定したIDを引用する回答を返す Fake（引用検証テスト用）。"""

    def __init__(self, cite_ids: list[int]) -> None:
        self._cite_ids = cite_ids

    async def classify_report(self, masked_text: str):  # pragma: no cover - 未使用
        raise NotImplementedError

    def stream_answer(self, query: str, sources):  # type: ignore[no-untyped-def]
        cite_ids = self._cite_ids

        class _Stream:
            def __aiter__(self):  # type: ignore[no-untyped-def]
                async def gen():  # type: ignore[no-untyped-def]
                    yield "回答本文 "
                    for cid in cite_ids:
                        yield f"[report:{cid}]"

                return gen()

            @property
            def usage(self) -> LLMCallMeta:
                return LLMCallMeta(
                    model_id="fake",
                    prompt_version="answer_v1",
                    input_tokens=10,
                    output_tokens=5,
                )

        return _Stream()


class FakePdfRenderer:
    """WeasyPrint を使わない決定的 PDF レンダラ（ホスト/CI でネイティブ依存を避ける）。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def render(self, *, title: str, body_markdown: str) -> bytes:
        self.calls.append((title, body_markdown))
        return b"%PDF-1.4 fake\n" + body_markdown.encode("utf-8") + b"\n%%EOF"


class FakeMetrics:
    """メトリクス送出を記録する Fake（MetricsPort。外部I/Oゼロ）。"""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.tokens: list[tuple[int, int]] = []

    def incr(self, name: str, value: int = 1, **dimensions: str) -> None:
        self.counts[name] = self.counts.get(name, 0) + value

    def emit_tokens(self, *, input_tokens: int, output_tokens: int, **dimensions: str) -> None:
        self.tokens.append((input_tokens, output_tokens))


class FakeAudit:
    """監査ログの記録を検証するための Fake。"""

    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    async def record(self, *, user_id: int, action: str, payload: dict[str, object]) -> None:
        self.records.append({"user_id": user_id, "action": action, "payload": payload})


def make_hit(report_id: int, *, summary: str = "要約", property_id: int = 101) -> SearchHit:
    return SearchHit(
        report_id=report_id,
        property_id=property_id,
        content=f"{summary} 本文",
        summary=summary,
        reported_at=datetime(2026, 6, 10, tzinfo=UTC),
        similarity=0.9,
    )


def make_analysis_status(confidence: float) -> AnalysisStatus:
    return AnalysisStatus.NEEDS_REVIEW if confidence < 0.85 else AnalysisStatus.AUTO_CLASSIFIED
