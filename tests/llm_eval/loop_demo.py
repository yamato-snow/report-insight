"""劣化検知 → 改善フローの閉ループ実証（実APIなし・決定的・課金ゼロ）。

`make eval-loop`（= python -m tests.llm_eval.loop_demo）で3段を通しで走らせる:

  ① ベースライン : クリーンな合成データを分類 → 精度を基準として記録
  ② 劣化注入     : 表記ゆれ（漢字→かな）を混ぜた"汚いデータ"を分類 → 精度が落ち、
                    ベースライン差分回帰が「劣化」を検知（RED）        ← 劣化検知
  ③ 改善適用     : human-verified 対応表（golden_corrections.json）で正規化してから
                    分類 → 精度が回復し、回帰が解消（GREEN）            ← 改善フロー

FakeLLMClient はキーワード依存の決定的分類器なので、表記ゆれで確実に精度が落ち、
正規化で確実に戻る。= ハーネスが「本番の静かな劣化」を捉え、修正の還流で回復できることの証明。

判定: ②で劣化を検知し、かつ③で回復できたら成功（exit 0）。どちらか欠ければ失敗（exit 1）。
本番の取込パイプラインへの正規化配線・実メトリクス送出は P2（観測層）で行う。
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from scripts.synth import NoiseConfig, generate

from app.infra.llm.fake_client import FakeLLMClient
from app.infra.text.normalize import TextNormalizer
from tests.llm_eval.datasets import ClassificationCase
from tests.llm_eval.evaluators import eval_classification
from tests.llm_eval.metrics import ClassificationReport
from tests.llm_eval.regression import compare, format_table
from tests.unit.fakes import FakeMasker

_GOLDEN_PATH = Path(__file__).resolve().parent / "golden_corrections.json"


def _cases(
    count: int, noise: NoiseConfig, normalizer: TextNormalizer | None
) -> list[ClassificationCase]:
    """合成データを分類ケースへ変換する。normalizer 指定時は分類前に正規化を適用。"""
    cases: list[ClassificationCase] = []
    for payload, sample in generate(count, noise=noise):
        text = str(payload["raw_text"])
        if normalizer is not None:
            text = normalizer.normalize(text)
        cases.append(
            ClassificationCase(
                raw_text=text,
                reporter_role=sample.reporter_role,
                expected_category=sample.label.category.value,
                expected_urgency=sample.label.urgency.value,
                tags=tuple(sample.tags),
            )
        )
    return cases


async def _classify(cases: list[ClassificationCase]) -> ClassificationReport:
    # マスキングは PII 用で表記ゆれと直交するため、恒等マスカで変数を分離する。
    return await eval_classification(FakeLLMClient(), FakeMasker(), cases)


def _metrics(rep: ClassificationReport) -> dict[str, object]:
    return {
        "classification": {
            "accuracy": round(rep.accuracy, 4),
            "urgency_high_recall": round(rep.urgency_high_recall, 4),
            "injection_ok": rep.injection_ok,
        }
    }


def _print(title: str) -> None:
    print(f"\n=== {title} ===")  # noqa: T201 — デモCLI出力


async def _run() -> int:
    count = int(os.environ.get("EVAL_LOOP_COUNT", "300"))
    notation = float(os.environ.get("EVAL_LOOP_NOTATION", "0.6"))
    missing = float(os.environ.get("EVAL_LOOP_MISSING", "0.2"))
    noise = NoiseConfig(notation=notation, missing=missing)

    normalizer = TextNormalizer.from_file(_GOLDEN_PATH)

    # ① ベースライン（クリーン）
    base_rep = await _classify(_cases(count, NoiseConfig.clean(), None))
    base_metrics = _metrics(base_rep)

    # ② 劣化注入（汚いデータ・正規化なし）
    noisy_rep = await _classify(_cases(count, noise, None))
    noisy_metrics = _metrics(noisy_rep)

    # ③ 改善適用（汚いデータ・正規化あり）
    fixed_rep = await _classify(_cases(count, noise, normalizer))
    fixed_metrics = _metrics(fixed_rep)

    _print(f"① ベースライン（クリーン {count}件）")
    print(  # noqa: T201
        f"分類精度 acc={base_rep.accuracy:.3f} / 緊急recall={base_rep.urgency_high_recall:.3f}"
        " を基準値として記録"
    )
    print(  # noqa: T201
        "  ※ この基準は FakeLLMClient（キーワード依存の決定的stub）の素の精度で、"
        "実モデルの 0.94 より低いのは設計どおり。本デモの主眼は絶対値でなく"
        "「基準からの相対的な劣化を検知し、修正で戻せるか」。"
    )

    _print(f"② 劣化注入（表記ゆれ {notation:.0%}／欠損 {missing:.0%}・正規化なし）")
    noisy_reg = compare(base_metrics, noisy_metrics)
    print(format_table(noisy_reg))  # noqa: T201
    detected = noisy_reg.regressed
    print(f"劣化検知: {'あり（回帰を検知）' if detected else 'なし（見逃し）'}")  # noqa: T201

    _print(f"③ 改善適用（同じ汚いデータ＋正規化辞書 {len(normalizer)}語）")
    fixed_reg = compare(base_metrics, fixed_metrics)
    print(format_table(fixed_reg))  # noqa: T201
    recovered = not fixed_reg.regressed
    print(  # noqa: T201
        f"回復: acc {noisy_rep.accuracy:.3f} → {fixed_rep.accuracy:.3f}"
        f"（{'回帰解消＝改善フロー成立' if recovered else '未回復'}）"
    )

    _print("閉ループ判定")
    ok = detected and recovered
    print(  # noqa: T201
        f"劣化を検知={detected} / 改善で回復={recovered} -> "
        f"{'閉ループ成立（PASS）' if ok else '不成立（FAIL）'}"
    )
    return 0 if ok else 1


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    sys.exit(main())
