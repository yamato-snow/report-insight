"""バージョン付きプロンプトのローダ（LLM設計書 §2 / 規約 §8）。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_DIR = Path(__file__).parent


@lru_cache
def load_prompt(name: str) -> dict[str, Any]:
    """`classify_v1` のような名前で YAML プロンプトを読み込む。"""
    path = _DIR / f"{name}.yaml"
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data
