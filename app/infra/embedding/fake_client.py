"""決定的な埋め込み（文字bigramのハッシュ）。デモ・テストを完全オフラインにする。

意味ベクトルではないが、共有する文字bigramが多いほど cosine 類似が高くなるため、
語彙の重なりで検索順位が決まり、パイプライン/検索の統合テストが決定的に成立する。
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence


def _hash_bucket(token: str, dim: int) -> int:
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % dim


def _vectorize(text: str, dim: int) -> list[float]:
    vec = [0.0] * dim
    normalized = text.replace("passage: ", "").replace("query: ", "")
    tokens = [normalized[i : i + 2] for i in range(max(len(normalized) - 1, 1))]
    for token in tokens:
        vec[_hash_bucket(token, dim)] += 1.0
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0.0:
        vec[0] = 1.0
        return vec
    return [v / norm for v in vec]


class FakeEmbeddingClient:
    """EmbeddingClient の決定的実装。"""

    def __init__(self, dim: int = 1024) -> None:
        self._dim = dim

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [_vectorize(t, self._dim) for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        return _vectorize(text, self._dim)
