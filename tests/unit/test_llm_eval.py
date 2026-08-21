"""LLM 評価ハーネスのスモークテスト（Fake で純粋ロジックを検証・実APIは呼ばない）。

実測（実LLM）は `make eval` で行う。ここではデータセット規模・分類評価の集計・
injection 判定・メトリクス閾値ロジックが壊れていないことだけを保証する。
"""

from __future__ import annotations

import pytest
from scripts.export_eval_cases import merge as merge_eval_cases

from app.infra.llm.fake_client import FakeLLMClient
from tests.llm_eval.datasets import (
    classification_cases,
    faithfulness_cases,
    human_classification_cases,
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
    # 検索: 基本30問 + ハードネガティブ10問（LLM設計書 §4）
    assert len(search_cases()) == 40
    assert len(faithfulness_cases()) == 20
    # doc_id は一意（recall@k の1:1対応の前提）
    doc_ids = [c.doc_id for c in search_cases()]
    assert len(set(doc_ids)) == len(doc_ids)
    # injection 検体が分類セットに含まれる
    assert any("injection" in c.tags for c in classification_cases(100))


def test_hard_negatives_reference_existing_docs() -> None:
    cases = search_cases()
    hard = [c for c in cases if c.distractor_doc_id is not None]
    assert len(hard) == 10
    doc_ids = {c.doc_id for c in cases}
    for case in hard:
        # 紛らわしい文書は同一コーパス内の実在文書を指す（自己参照は不可）
        assert case.distractor_doc_id in doc_ids
        assert case.distractor_doc_id != case.doc_id


def test_search_report_hard_negative_win_rate() -> None:
    # 10問中8勝 → 0.8。ハードネガティブ0問なら 1.0（未計測を失格にしない）
    r = SearchReport(
        total=40,
        recall_at_k=0.9,
        citation_existence_rate=1.0,
        hard_negative_total=10,
        hard_negative_wins=8,
    )
    assert r.hard_negative_win_rate == pytest.approx(0.8)
    none_measured = SearchReport(total=30, recall_at_k=0.9, citation_existence_rate=1.0)
    assert none_measured.hard_negative_win_rate == 1.0
    # 合否は従来指標のみで決まる（win rate は観測用）
    assert r.passed()


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


def test_human_cases_loader_roundtrip(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """export_eval_cases.merge → human_classification_cases の往復と重複排除。"""
    out = tmp_path / "human_cases.json"
    case = {
        "source_key": "reports/2026-06/0042.json",
        "raw_text": "1階の集合ポスト付近に落書きを発見しました。",
        "reporter_role": "管理員",
        "expected_category": "cleaning",
        "expected_urgency": "low",
        "expected_action_required": False,
        "tags": ["human_verified"],
    }
    added, total = merge_eval_cases(out, [case])
    assert (added, total) == (1, 1)

    # 同じ source_key の再修正は後勝ちで置き換え（件数は増えない）
    revised = dict(case, expected_category="claim")
    added, total = merge_eval_cases(out, [revised])
    assert (added, total) == (0, 1)

    loaded = human_classification_cases(out)
    assert len(loaded) == 1
    assert loaded[0].expected_category == "claim"
    assert "human_verified" in loaded[0].tags


def test_human_cases_missing_file_is_empty(tmp_path) -> None:  # type: ignore[no-untyped-def]
    assert human_classification_cases(tmp_path / "nope.json") == []
