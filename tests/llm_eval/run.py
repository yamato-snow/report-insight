"""LLM 評価ハーネス エントリポイント（make eval = python -m tests.llm_eval.run）。

実LLM + fastembed で分類・検索・忠実性を評価し、閾値（LLM設計書 §4）で合否判定する。
DB（pgvector）が必要。`make up && make migrate` 済みの状態で実行する。
provider=fake でもスモーク実行できるが、忠実性(judge)は実APIが必要なためスキップする。

出力: 標準出力にサマリ、`tests/llm_eval/last_result.json` に機械可読な結果。
合否は終了コードで返す（CI/README 記録用）。
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from anthropic import AsyncAnthropic
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.config import LLMProvider, get_settings
from app.core.db import unit_of_work
from app.core.di import build_container
from app.infra.db import models
from app.infra.db.repositories import SqlReportRepository, SqlSearchRepository
from app.services.ingest import IngestService
from tests.llm_eval.datasets import (
    classification_cases,
    faithfulness_cases,
    search_cases,
)
from tests.llm_eval.evaluators import (
    eval_classification,
    eval_faithfulness,
    eval_search,
)
from tests.llm_eval.metrics import EvalSummary
from tests.unit.fakes import FakeStorage

_RESULT_PATH = Path(__file__).resolve().parent / "last_result.json"
_EVAL_PROPERTY_ID = 101


async def _seed_reference(container) -> None:  # type: ignore[no-untyped-def]
    """評価に必要な最小の支店・物件・利用者を用意する（存在すれば無視）。"""
    async with unit_of_work(container.session_factory) as session:
        await session.execute(
            pg_insert(models.Branch)
            .values([{"id": 1, "name": "東京支店"}])
            .on_conflict_do_nothing()
        )
        await session.execute(
            pg_insert(models.Property)
            .values([{"id": _EVAL_PROPERTY_ID, "branch_id": 1, "name": "評価用物件"}])
            .on_conflict_do_nothing()
        )
        await session.execute(
            pg_insert(models.User)
            .values([{"id": 2, "branch_id": None, "email": "qa@e.com", "role": "qa"}])
            .on_conflict_do_nothing()
        )


async def _ingest_search_corpus(container) -> dict[str, int]:  # type: ignore[no-untyped-def]
    """検索評価用コーパスを ingest し、doc_id→report_id の対応を返す。"""
    cases = search_cases()
    objects: dict[str, bytes] = {}
    for case in cases:
        objects[case.doc_id] = json.dumps(
            {
                "source_key": case.doc_id,
                "property_id": _EVAL_PROPERTY_ID,
                "reported_at": "2026-06-15T09:00:00+00:00",
                "reporter_role": "巡回スタッフ",
                "raw_text": case.raw_text,
                "photo_meta": {},
            }
        ).encode("utf-8")
    storage = FakeStorage(objects)

    for case in cases:
        async with unit_of_work(container.session_factory) as session:
            service = IngestService(
                storage=storage,
                masker=container.masker,
                llm=container.llm,
                embedder=container.embedder,
                repository=SqlReportRepository(session),
                notifier=container.notifier,
                confidence_threshold=container.settings.confidence_threshold,
            )
            await service.ingest_from_key(case.doc_id)

    # doc_id→report_id は DB から権威的に構築する。ingest が duplicate（既存）を返しても
    # source_key から既存 id を引けるため、DB をリセットせず再実行しても壊れない（冪等）。
    async with container.session_factory() as session:
        rows = await session.execute(
            select(models.Report.source_key, models.Report.id).where(
                models.Report.source_key.in_([case.doc_id for case in cases])
            )
        )
    return {source_key: report_id for source_key, report_id in rows.all()}


_FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")


def _parse_score(text: str) -> float | None:
    """応答から最初の 1..5 の数字を取り出す（全角も許容）。拾えなければ None。"""
    for ch in text.translate(_FULLWIDTH_DIGITS):
        if ch in "12345":
            return float(ch)
    return None


def _make_judge(settings):  # type: ignore[no-untyped-def]
    """実APIの LLM-as-judge（1..5）。パース失敗時は None を返し、平均から除外する。"""
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def judge(question: str, answer: str, grounded_fact: str) -> float | None:
        system = (
            "あなたは回答の忠実性を採点する審査員です。"
            "回答が根拠事実と矛盾せず支持されているかを 1〜5 で評価してください。"
            "5=完全に忠実、1=根拠と矛盾または捏造。"
            "出力は半角数字1文字（1〜5）だけとし、前置き・記号・説明を一切書かないこと。"
        )
        user = f"質問: {question}\n根拠事実: {grounded_fact}\n回答: {answer}\nスコア(1-5):"
        # 稀に前置きが混じり数字が拾えないことがあるため数回試行する
        # （temperature は新しめのモデルで非対応のため指定しない）。
        for _ in range(3):
            resp = await client.messages.create(
                model=settings.model_generate,
                max_tokens=24,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            body = "".join(
                getattr(b, "text", "") for b in resp.content if getattr(b, "type", None) == "text"
            )
            score = _parse_score(body)
            if score is not None:
                return score
        return None

    return judge


async def _run() -> EvalSummary:
    settings = get_settings()
    container = build_container(settings)
    summary = EvalSummary()
    try:
        # 1) 分類（DB不要）
        summary.classification = await eval_classification(
            container.llm, container.masker, classification_cases(100)
        )

        # 2) 検索（DB必要）: 参照データ整備 → コーパス ingest → recall@k
        try:
            await _seed_reference(container)
            mapping = await _ingest_search_corpus(container)
            async with container.session_factory() as session:
                summary.search = await eval_search(
                    embedder=container.embedder,
                    repository=SqlSearchRepository(session),
                    doc_id_to_report_id=mapping,
                    cases=search_cases(),
                )
        except Exception as exc:  # noqa: BLE001 — 評価スクリプト境界（DB未起動等を記録して継続）
            summary.notes.append(f"検索評価スキップ: {exc}")

        # 3) 忠実性（実API judge が必要）
        if settings.llm_provider is LLMProvider.ANTHROPIC and summary.search is not None:
            async with container.session_factory() as session:
                summary.faithfulness = await eval_faithfulness(
                    llm=container.llm,
                    embedder=container.embedder,
                    repository=SqlSearchRepository(session),
                    judge=_make_judge(settings),
                    cases=faithfulness_cases(),
                )
        else:
            summary.notes.append("忠実性評価スキップ: provider=anthropic かつ検索成功時のみ実行")
    finally:
        await container.aclose()
    return summary


def _print_and_persist(summary: EvalSummary) -> None:
    result: dict[str, object] = {"passed": summary.passed(), "notes": summary.notes}
    print("=== LLM 評価結果 ===")  # noqa: T201 — 評価スクリプトのCLI出力
    if summary.classification is not None:
        c = summary.classification
        result["classification"] = {
            "accuracy": round(c.accuracy, 4),
            "urgency_high_recall": round(c.urgency_high_recall, 4),
            "injection_ok": c.injection_ok,
            "passed": c.passed(),
        }
        print(  # noqa: T201
            f"分類: acc={c.accuracy:.3f} high_recall={c.urgency_high_recall:.3f} "
            f"injection_ok={c.injection_ok} -> {'PASS' if c.passed() else 'FAIL'}"
        )
    if summary.search is not None:
        s = summary.search
        result["search"] = {
            "recall_at_k": round(s.recall_at_k, 4),
            "citation_existence_rate": round(s.citation_existence_rate, 4),
            "passed": s.passed(),
        }
        print(  # noqa: T201
            f"検索: recall@8={s.recall_at_k:.3f} citation={s.citation_existence_rate:.3f} "
            f"-> {'PASS' if s.passed() else 'FAIL'}"
        )
    if summary.faithfulness is not None:
        f = summary.faithfulness
        result["faithfulness"] = {"mean_score": round(f.mean_score, 3), "passed": f.passed()}
        print(f"忠実性: mean={f.mean_score:.2f} -> {'PASS' if f.passed() else 'FAIL'}")  # noqa: T201
    for note in summary.notes:
        print(f"注記: {note}")  # noqa: T201
    print(f"総合: {'PASS' if summary.passed() else 'FAIL'}")  # noqa: T201
    _RESULT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    summary = asyncio.run(_run())
    _print_and_persist(summary)
    return 0 if summary.passed() else 1


if __name__ == "__main__":
    sys.exit(main())
