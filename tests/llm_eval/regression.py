"""ベースライン差分回帰（劣化検知）。絶対閾値とは別に「前回比で下がったか」を見る。

metrics.py の絶対閾値は「基準を満たすか」を判定する。だが本番の劣化は、閾値は割らずとも
じわじわ精度が落ちる形で来る。regression は last_result.json（過去のベースライン）に対する
差分を取り、許容幅を超える低下を「劣化」として検知する。= 本番の静かな劣化を捉える目。

使い方（run.py / loop_demo から）:
    base = load_metrics("tests/llm_eval/baseline.json")
    cur = current_metrics(summary)
    result = compare(base, cur)
    if result.regressed: ...  # 劣化あり
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

# 監視するメトリクスと、劣化とみなす許容低下幅（この幅を超えて下がったら回帰）。
# いずれも「高いほど良い」指標。忠実性のみ 1〜5 スケールなので許容幅を広めに取る。
METRIC_TOLERANCE: dict[str, float] = {
    "classification.accuracy": 0.03,
    "classification.urgency_high_recall": 0.03,
    "search.recall_at_k": 0.03,
    "search.citation_existence_rate": 0.0,  # 引用実在は 1.0 必須。低下は即劣化。
    "faithfulness.mean_score": 0.3,
}


@dataclass(frozen=True)
class MetricDelta:
    metric: str
    baseline: float
    current: float
    tolerance: float

    @property
    def delta(self) -> float:
        return round(self.current - self.baseline, 4)

    @property
    def regressed(self) -> bool:
        return self.current < self.baseline - self.tolerance


@dataclass
class RegressionResult:
    deltas: list[MetricDelta] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)  # baseline/current に無く比較不能だった指標

    @property
    def regressed(self) -> bool:
        return any(d.regressed for d in self.deltas)

    def regressions(self) -> list[MetricDelta]:
        return [d for d in self.deltas if d.regressed]


def _get(metrics: Mapping[str, object], dotted: str) -> float | None:
    """ "classification.accuracy" のようなドットパスで値を引く。無ければ None。"""
    node: object = metrics
    for key in dotted.split("."):
        if not isinstance(node, Mapping) or key not in node:
            return None
        node = node[key]
    return float(node) if isinstance(node, (int, float)) else None


def compare(
    baseline: Mapping[str, object],
    current: Mapping[str, object],
    *,
    tolerance: Mapping[str, float] | None = None,
) -> RegressionResult:
    tol = dict(METRIC_TOLERANCE)
    if tolerance:
        tol.update(tolerance)
    result = RegressionResult()
    for metric, default_tol in tol.items():
        b = _get(baseline, metric)
        c = _get(current, metric)
        if b is None or c is None:
            result.missing.append(metric)
            continue
        result.deltas.append(
            MetricDelta(metric=metric, baseline=b, current=c, tolerance=default_tol)
        )
    return result


def load_metrics(path: str | Path) -> dict[str, object]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_metrics(path: str | Path, metrics: Mapping[str, object]) -> None:
    Path(path).write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")


def format_table(result: RegressionResult) -> str:
    """人が読める差分表（loop_demo / CI ログ用）。"""
    lines = [f"{'metric':<34} {'baseline':>9} {'current':>9} {'Δ':>8}  verdict"]
    for d in result.deltas:
        verdict = "REGRESSED" if d.regressed else "ok"
        sign = "+" if d.delta >= 0 else ""
        lines.append(
            f"{d.metric:<34} {d.baseline:>9.3f} {d.current:>9.3f} {sign}{d.delta:>7.3f}  {verdict}"
        )
    for m in result.missing:
        lines.append(f"{m:<34} {'-':>9} {'-':>9} {'-':>8}  skipped(no-data)")
    return "\n".join(lines)
