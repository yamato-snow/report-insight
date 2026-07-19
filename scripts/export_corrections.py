"""レビュー由来の表記ゆれ対応を正規化辞書（golden_corrections.json）へ還流する。

改善フローの配線: needs_review の人手確認で「これは表記ゆれ（例: ろうすい=漏水）」と分かった
対応を、正規化辞書へ蓄積する。TextNormalizer がこれを読み、以後の分類前に適用して精度を保つ。
= 「人手修正 → 辞書に還流 → 再評価で回復」という改善ループの、入口側スクリプト。

本番では admin の override 監査ログ（app.services.admin）から表記ゆれ候補を抽出する導線を
P2 で足す。本スクリプトはレビューがまとめた {variant, canonical} 一覧を受け取り、既存辞書へ
重複排除しつつマージする最小実装（実DB非依存で回せる）。

使い方:
    python -m scripts.export_corrections --input review.json
    # review.json = {"corrections": [{"variant":"ろうすい","canonical":"漏水"}, ...]}
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

_DEFAULT_GOLDEN = Path(__file__).resolve().parents[1] / "tests/llm_eval/golden_corrections.json"


def _load_corrections(path: Path) -> list[dict[str, str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("corrections", []) if isinstance(data, dict) else data
    out: list[dict[str, str]] = []
    for item in items:
        variant = str(item["variant"]).strip()
        canonical = str(item["canonical"]).strip()
        if variant and canonical and variant != canonical:
            out.append(
                {
                    "variant": variant,
                    "canonical": canonical,
                    "source": str(item.get("source", "human_verified")),
                }
            )
    return out


def merge(golden_path: Path, incoming: list[dict[str, str]]) -> tuple[int, int]:
    """incoming を golden へマージ。(追加数, 総数) を返す。variant をキーに重複排除。"""
    existing = _load_corrections(golden_path) if golden_path.exists() else []
    by_variant: dict[str, dict[str, str]] = {c["variant"]: c for c in existing}
    added = 0
    for c in incoming:
        if c["variant"] not in by_variant:
            added += 1
        by_variant[c["variant"]] = c  # 後勝ち（レビューの最新確認を優先）
    corrections = sorted(by_variant.values(), key=lambda c: c["variant"])
    doc = {
        "_comment": (
            "現場報告の表記ゆれ→正規形の人手確認済み対応表。"
            "needs_review の修正から還流して蓄積する（scripts/export_corrections.py）。"
            "TextNormalizer が読み込み分類前に適用する。"
        ),
        "corrections": corrections,
    }
    golden_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return added, len(corrections)


def main() -> int:
    parser = argparse.ArgumentParser(description="表記ゆれ対応を正規化辞書へ還流する")
    parser.add_argument("--input", required=True, help="レビュー由来の対応JSON")
    parser.add_argument("--golden", default=str(_DEFAULT_GOLDEN), help="正規化辞書の出力先")
    args = parser.parse_args()

    incoming = _load_corrections(Path(args.input))
    added, total = merge(Path(args.golden), incoming)
    print(f"還流: +{added}語 追加（辞書 計{total}語） -> {args.golden}")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
