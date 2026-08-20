"""プロンプト A/B 比較ハーネス（実API・分類タスクのみ）。

狙い: 「プロンプトを直したら良くなったのか悪くなったのか」を、観点をずらした複数版で
      同一の評価セットに当てて比較する。

設計上の注意:
- 本番コードは一切変更しない。AnthropicLLMClient の `_classify_prompt` を差し替えるだけ。
- `make eval-loop`（FakeLLMClient）は **プロンプトを読まない**（キーワードマッチ）ため
  プロンプト比較には使えない。したがって本ハーネスは実APIを前提とする。
- マスキングは恒等（比較の変数を分離するため）。本番は PIIMasker を通る。

使い方:
    uv run python -m tests.llm_eval.prompt_ab            # 100件 × 5版
    EVAL_AB_COUNT=40 uv run python -m tests.llm_eval.prompt_ab
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.core.config import get_settings
from app.domain.values import Urgency
from app.infra.llm.anthropic_client import AnthropicLLMClient
from app.infra.llm.prompts import load_prompt
from tests.llm_eval.datasets import ClassificationCase, classification_cases

_VARIANT_DIR = Path(__file__).parent / "ab_variants"
_OUT_PATH = Path(__file__).parent / "ab_result.json"

# 閾値（tests/llm_eval/metrics.py と同じ）
THRESHOLD_ACCURACY = 0.90
THRESHOLD_HIGH_RECALL = 0.95

CONCURRENCY = int(os.environ.get("EVAL_AB_CONCURRENCY", "10"))


@dataclass
class VariantResult:
    name: str
    label: str
    total: int
    accuracy: float
    high_recall: float
    errors: int
    high_total: int
    high_hit: int


def _variants() -> list[tuple[str, str, dict[str, Any]]]:
    """(キー, 表示ラベル, プロンプト辞書) を返す。V1 は本番の classify_v1。"""
    out: list[tuple[str, str, dict[str, Any]]] = [
        ("v1_baseline", "V1 ベースライン（本番 classify_v1）", load_prompt("classify_v1")),
    ]
    labels = {
        "v2_degraded": "V2 劣化版（役割・定義・出力形式を削る）",
        "v3_criteria": "V3 判断基準の明文化（high の条件を列挙）",
        "v4_fewshot": "V4 Few-shot（境界事例3件）",
        "v5_asymmetric": "V5 非対称コスト（迷ったら high に倒す）",
    }
    for key in ["v2_degraded", "v3_criteria", "v4_fewshot", "v5_asymmetric"]:
        path = _VARIANT_DIR / f"{key}.yaml"
        out.append((key, labels[key], yaml.safe_load(path.read_text(encoding="utf-8"))))
    return out


async def _run_variant(
    key: str,
    label: str,
    prompt: dict[str, Any],
    cases: list[ClassificationCase],
) -> VariantResult:
    settings = get_settings()
    client = AnthropicLLMClient(
        api_key=settings.anthropic_api_key or "",
        model_classify=settings.model_classify,
        model_generate=settings.model_generate,
    )
    # ★ここが差し替え点。本番コードは触らない。
    client._classify_prompt = prompt  # noqa: SLF001

    sem = asyncio.Semaphore(CONCURRENCY)
    correct = 0
    high_total = 0
    high_hit = 0
    errors = 0
    lock = asyncio.Lock()

    async def one(case: ClassificationCase) -> None:
        nonlocal correct, high_total, high_hit, errors
        async with sem:
            try:
                envelope = await client.classify_report(case.raw_text)
                predicted = envelope.result
                ok = predicted.category.value == case.expected_category
                is_high_expected = case.expected_urgency == Urgency.HIGH.value
                is_high_pred = predicted.urgency is Urgency.HIGH
            except Exception:  # 失敗は「不正解」ではなく errors として別勘定にする
                async with lock:
                    errors += 1
                    if case.expected_urgency == Urgency.HIGH.value:
                        high_total += 1
                return
        async with lock:
            if ok:
                correct += 1
            if is_high_expected:
                high_total += 1
                if is_high_pred:
                    high_hit += 1

    await asyncio.gather(*(one(c) for c in cases))

    total = len(cases)
    return VariantResult(
        name=key,
        label=label,
        total=total,
        accuracy=correct / total if total else 0.0,
        high_recall=high_hit / high_total if high_total else 1.0,
        errors=errors,
        high_total=high_total,
        high_hit=high_hit,
    )


def _fmt(results: list[VariantResult]) -> str:
    base = results[0]
    lines = [
        "",
        f"■ プロンプト A/B 比較（分類 {base.total} 件・実API）",
        "",
        f"{'版':<40} {'accuracy':>10} {'差':>8} {'high recall':>12} {'差':>8} {'err':>5}",
        "-" * 90,
    ]
    for r in results:
        da = "" if r is base else f"{r.accuracy - base.accuracy:+.3f}"
        dr = "" if r is base else f"{r.high_recall - base.high_recall:+.3f}"
        lines.append(
            f"{r.label:<40} {r.accuracy:>10.3f} {da:>8} "
            f"{r.high_recall:>12.3f} {dr:>8} {r.errors:>5}"
        )
    lines += [
        "-" * 90,
        f"閾値: accuracy >= {THRESHOLD_ACCURACY} / high recall >= {THRESHOLD_HIGH_RECALL}",
        f"緊急度 high の母数: {base.high_total} 件",
        "",
    ]
    return "\n".join(lines)


async def main() -> int:
    count = int(os.environ.get("EVAL_AB_COUNT", "100"))
    cases = classification_cases(count)
    results: list[VariantResult] = []
    for key, label, prompt in _variants():
        print(f"... {label} を実行中（{len(cases)}件）", flush=True)
        results.append(await _run_variant(key, label, prompt, cases))
    print(_fmt(results))
    _OUT_PATH.write_text(
        json.dumps([r.__dict__ for r in results], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"→ {_OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
