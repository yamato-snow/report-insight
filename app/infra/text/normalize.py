"""表記ゆれ正規化（かな→正規形）。改善フロー（human-verified 修正 → 精度回復）の受け手。

現場報告の表記ゆれ（「ろうすい」↔「漏水」等）は、キーワード依存の分類の手掛かりを外し
精度を下げる。運用で蓄積した人手確認済みの対応表（golden_corrections.json）を読み込み、
分類前に正規形へ揃えることで劣化を回復させる。

= 「needs_review の人手修正 → 正規化辞書に還流 → 再評価で精度回復」という改善ループの実装単位。
本 P1 では評価ハーネスで効果を実証する。取込パイプライン（IngestService）への配線は
P2（本番観測層）で行う。
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Correction:
    """人手確認済みの1対応（表記ゆれ → 正規形）。overrides からの還流で蓄積する。"""

    variant: str
    canonical: str
    source: str = "human_verified"


class TextNormalizer:
    """対応表に基づき表記ゆれを正規形へ置換する。副作用なし・決定的。"""

    def __init__(self, corrections: Mapping[str, str] | Iterable[Correction]) -> None:
        if isinstance(corrections, Mapping):
            pairs = [(v, c) for v, c in corrections.items()]
        else:
            pairs = [(c.variant, c.canonical) for c in corrections]
        # 長い variant を先に置換し、部分文字列の取りこぼし/二重変換を避ける。
        self._ordered: list[tuple[str, str]] = sorted(pairs, key=lambda p: len(p[0]), reverse=True)

    def normalize(self, text: str) -> str:
        for variant, canonical in self._ordered:
            if variant:
                text = text.replace(variant, canonical)
        return text

    def __len__(self) -> int:
        return len(self._ordered)

    @classmethod
    def empty(cls) -> TextNormalizer:
        """正規化なし（改善フロー適用前のベースライン用）。"""
        return cls({})

    @classmethod
    def from_file(cls, path: str | Path) -> TextNormalizer:
        """golden_corrections.json を読む（{"corrections": [{variant, canonical, source}]}）。"""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls([Correction(**item) for item in data.get("corrections", [])])
