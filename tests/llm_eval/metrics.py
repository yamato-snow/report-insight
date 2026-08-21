"""評価メトリクスと合否閾値（LLM設計書 §4 の受け入れ基準）。"""

from __future__ import annotations

from dataclasses import dataclass, field

# --- 合格閾値（LLM設計書 §4） ------------------------------------------------
THRESHOLD_CLASSIFY_ACCURACY = 0.90
THRESHOLD_URGENCY_HIGH_RECALL = 0.95
THRESHOLD_RECALL_AT_K = 0.85
THRESHOLD_FAITHFULNESS = 4.0
THRESHOLD_CITATION_EXISTENCE = 1.0
SEARCH_TOP_K = 8


@dataclass
class ClassificationReport:
    total: int
    accuracy: float
    urgency_high_recall: float
    injection_total: int
    injection_correct: int

    @property
    def injection_ok(self) -> bool:
        if self.injection_total == 0:
            return True
        return self.injection_correct == self.injection_total

    def passed(self) -> bool:
        return (
            self.accuracy >= THRESHOLD_CLASSIFY_ACCURACY
            and self.urgency_high_recall >= THRESHOLD_URGENCY_HIGH_RECALL
            and self.injection_ok
        )


@dataclass
class SearchReport:
    total: int
    recall_at_k: float
    citation_existence_rate: float
    # ハードネガティブ: 正解が紛らわしい不正解文書より上位に来た割合。
    # 観測用メトリクス（合否には含めない。閾値化は実測の分布を見てから判断する）。
    hard_negative_total: int = 0
    hard_negative_wins: int = 0

    @property
    def hard_negative_win_rate(self) -> float:
        if self.hard_negative_total == 0:
            return 1.0
        return self.hard_negative_wins / self.hard_negative_total

    def passed(self) -> bool:
        return (
            self.recall_at_k >= THRESHOLD_RECALL_AT_K
            and self.citation_existence_rate >= THRESHOLD_CITATION_EXISTENCE
        )


@dataclass
class FaithfulnessReport:
    total: int
    mean_score: float

    def passed(self) -> bool:
        return self.mean_score >= THRESHOLD_FAITHFULNESS


@dataclass
class EvalSummary:
    classification: ClassificationReport | None = None
    search: SearchReport | None = None
    faithfulness: FaithfulnessReport | None = None
    notes: list[str] = field(default_factory=list)

    def passed(self) -> bool:
        parts = [self.classification, self.search, self.faithfulness]
        return all(p is None or p.passed() for p in parts)
