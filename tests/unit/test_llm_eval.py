"""LLM 評価ハーネスのスモークテスト（Fake で純粋ロジックを検証・実APIは呼ばない）。

実測（実LLM）は `make eval` で行う。ここではデータセット規模・分類評価の集計・
injection 判定・メトリクス閾値ロジックが壊れていないことだけを保証する。
"""

from __future__ import annotations

import pytest

from app.infra.llm.fake_client import FakeLLMClient
from tests.llm_eval.datasets import (
    classification_cases,
    faithfulness_cases,
    search_cases,
)
from tests.llm_eval.evaluators import eval_classification, parse_citations
from tests.llm_eval.metrics import (
    THRESHOLD_CLASSIFY_ACCURACY,
    ClassificationReport,
    SearchReport,
)
from tests.unit.fakes import FakeMasker


def test_dataset_sizes_meet_spec() -> None:
    assert len(classification_cases(100)) == 100
    assert len(search_cases()) == 30
    assert len(faithfulness_cases()) == 20
    # doc_id は一意（recall@k の1:1対応の前提）
    doc_ids = [c.doc_id for c in search_cases()]
    assert len(set(doc_ids)) == len(doc_ids)
    # injection 検体が分類セットに含まれる
    assert any("injection" in c.tags for c in classification_cases(100))


async def test_eval_classification_runs_with_fake() -> None:
    report = await eval_classification(FakeLLMClient(), FakeMasker(), classification_cases(50))
    assert report.total == 50
    assert 0.0 <= report.accuracy <= 1.0
    assert 0.0 <= report.urgency_high_recall <= 1.0
    # FakeLLM はキーワード分類。機械室のinjection検体を cleaning に誤らないこと（§7）。
    assert report.injection_total >= 1
    assert report.injection_ok


def test_metrics_threshold_logic() -> None:
    good = ClassificationReport(
        total=100,
        accuracy=0.92,
        urgency_high_recall=0.96,
        injection_total=1,
        injection_correct=1,
    )
    assert good.passed()
    bad = ClassificationReport(
        total=100,
        accuracy=0.80,
        urgency_high_recall=0.96,
        injection_total=1,
        injection_correct=1,
    )
    assert not bad.passed()
    # injection が汚染されたら閾値を満たしても不合格
    polluted = ClassificationReport(
        total=100,
        accuracy=0.99,
        urgency_high_recall=0.99,
        injection_total=2,
        injection_correct=1,
    )
    assert not polluted.passed()

    search_ok = SearchReport(total=30, recall_at_k=0.87, citation_existence_rate=1.0)
    assert search_ok.passed()
    search_bad = SearchReport(total=30, recall_at_k=0.87, citation_existence_rate=0.9)
    assert not search_bad.passed()  # 引用実在率100%未満は不合格


def test_parse_citations() -> None:
    assert parse_citations("根拠 [report:12] と [report:7]") == {12, 7}
    assert parse_citations("引用なし") == set()


def test_threshold_constant_is_090() -> None:
    assert THRESHOLD_CLASSIFY_ACCURACY == pytest.approx(0.90)
