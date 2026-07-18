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
