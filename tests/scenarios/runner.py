"""シナリオJSONを実パイプライン（IngestService）に流し、期待値と突合するランナー本体。

出力は構造化データのみ（表示はしない）。CLI（run.py）・pytest・画面用エンドポイントの
いずれからも同じ結果を得られるようにするための純粋な検証ロジック。

判定は決定的で課金ゼロ:
- 分類は FakeLLMClient（キーワードベースの決定的分類器）
- 埋め込みは FakeEmbeddingClient
- マスキングだけは本物の PIIMasker を使う（PII が実際に伏字化されるかを検証するため）

シナリオは「AIの精度」ではなく「パイプラインの振り分け挙動」を検証する。
分類精度そのものの評価は tests/llm_eval（make eval・実API）が担う。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from tests.unit.fakes import FakeNotifier, FakeReportRepository, FakeStorage

from app.domain.values import DEFAULT_CONFIDENCE_THRESHOLD, AnalysisStatus, Category, Urgency
from app.infra.embedding.fake_client import FakeEmbeddingClient
from app.infra.llm.fake_client import FakeLLMClient
from app.infra.masking.pii import PIIMasker
from app.services.ingest import IngestService
from app.services.ports import ReportRepository

CASES_DIR = Path(__file__).resolve().parent / "cases"


@dataclass
class Check:
    """1つの期待項目の判定結果。"""

    field: str
    expected: Any
    actual: Any
    ok: bool


@dataclass
class InputResult:
    """入力1件分の判定。"""

    text: str
    checks: list[Check]

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)


@dataclass
class ScenarioResult:
    """シナリオ1本の判定。"""

    name: str
    path: str
    requirements: list[str]
    inputs: list[InputResult]
    overall_checks: list[Check] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(i.ok for i in self.inputs) and all(c.ok for c in self.overall_checks)

    @property
    def failed_checks(self) -> list[Check]:
        out = [c for i in self.inputs for c in i.checks if not c.ok]
        out += [c for c in self.overall_checks if not c.ok]
        return out


def _payload(source_key: str, text: str) -> bytes:
    return json.dumps(
        {
            "source_key": source_key,
            "property_id": 101,
            "reported_at": "2026-06-15T09:00:00+09:00",
            "reporter_role": "巡回スタッフ",
            "raw_text": text,
            "photo_meta": {},
        },
        ensure_ascii=False,
    ).encode()


def _capturing_masker(real: PIIMasker) -> tuple[PIIMasker, list[str]]:
    """LLM へ渡ったマスク後テキストを記録するラッパ（PII 検証用）。"""
    sent: list[str] = []
    original = real.mask

    async def _mask(text: str):  # type: ignore[no-untyped-def]
        result = await original(text)
        sent.append(result.masked_text)
        return result

    real.mask = _mask  # type: ignore[method-assign]
    return real, sent


def _load_spec(path: Path) -> dict[str, Any]:
    spec: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return spec


async def run_scenario(path: Path) -> ScenarioResult:
    """1シナリオを実行して判定結果を返す。"""
    spec = _load_spec(path)
    storage = FakeStorage()
    notifier = FakeNotifier()
    repo = FakeReportRepository()

    masker, sent_to_llm = _capturing_masker(PIIMasker())
    service = IngestService(
        storage=storage,
        masker=masker,
        llm=FakeLLMClient(),
        embedder=FakeEmbeddingClient(dim=64),
        repository=cast("ReportRepository", repo),
        notifier=notifier,
        confidence_threshold=DEFAULT_CONFIDENCE_THRESHOLD,
    )

    input_results: list[InputResult] = []
    notified_count = 0
    queued_count = 0
    duplicate_count = 0
    lost = 0

    for i, item in enumerate(spec["inputs"]):
        source_key = item.get("source_key", f"reports/scenario/{path.stem}-{i:03d}.json")
        text = item["text"]
        await storage.put_object(source_key, _payload(source_key, text))
        before = len(sent_to_llm)
        outcome = await service.ingest_from_key(source_key)

        # 保存された分析（重複時は None）
        analysis = repo.saved[-1][1] if (repo.saved and not outcome.duplicate) else None
        queued = analysis is not None and analysis.status is AnalysisStatus.NEEDS_REVIEW
        if outcome.notified:
            notified_count += 1
        if queued:
            queued_count += 1
        if outcome.duplicate:
            duplicate_count += 1
        if analysis is None and not outcome.duplicate:
            lost += 1

        checks = _check_input(
            expect=item.get("expect", {}),
            outcome_notified=outcome.notified,
            outcome_duplicate=outcome.duplicate,
            queued=queued,
            category=analysis.category if analysis else None,
            urgency=analysis.urgency if analysis else None,
            llm_input=sent_to_llm[before] if len(sent_to_llm) > before else None,
        )
        input_results.append(InputResult(text=text, checks=checks))

    overall = _check_overall(
        spec.get("expect_overall", {}),
        lost=lost,
        notified=notified_count,
        queued=queued_count,
        duplicates=duplicate_count,
    )

    return ScenarioResult(
        name=spec["name"],
        path=str(path.relative_to(CASES_DIR.parent.parent.parent)),
        requirements=spec.get("requirements", []),
        inputs=input_results,
        overall_checks=overall,
    )


def _check_input(
    *,
    expect: dict[str, Any],
    outcome_notified: bool,
    outcome_duplicate: bool,
    queued: bool,
    category: Category | None,
    urgency: Urgency | None,
    llm_input: str | None,
) -> list[Check]:
    checks: list[Check] = []
    if "category" in expect:
        checks.append(
            Check(
                "category",
                expect["category"],
                category.value if category else None,
                category is not None and category.value == expect["category"],
            )
        )
    if "urgency" in expect:
        checks.append(
            Check(
                "urgency",
                expect["urgency"],
                urgency.value if urgency else None,
                urgency is not None and urgency.value == expect["urgency"],
            )
        )
    if "notified" in expect:
        checks.append(
            Check(
                "notified",
                expect["notified"],
                outcome_notified,
                outcome_notified == expect["notified"],
            )
        )
    if "queued" in expect:
        checks.append(Check("queued", expect["queued"], queued, queued == expect["queued"]))
    if "duplicate" in expect:
        checks.append(
            Check(
                "duplicate",
                expect["duplicate"],
                outcome_duplicate,
                outcome_duplicate == expect["duplicate"],
            )
        )
    if "pii_absent_in_llm_input" in expect:
        leaked = [p for p in expect["pii_absent_in_llm_input"] if llm_input and p in llm_input]
        checks.append(
            Check(
                "pii_absent_in_llm_input",
                "(伏字化)",
                f"漏洩: {leaked}" if leaked else "(伏字化済み)",
                not leaked,
            )
        )
    return checks


def _check_overall(
    expect: dict[str, Any], *, lost: int, notified: int, queued: int, duplicates: int
) -> list[Check]:
    actual = {"lost": lost, "notified": notified, "queued": queued, "duplicates": duplicates}
    return [Check(k, v, actual[k], actual[k] == v) for k, v in expect.items() if k in actual]


def list_scenarios() -> list[Path]:
    return sorted(CASES_DIR.glob("*.json"))
