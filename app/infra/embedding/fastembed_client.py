"""fastembed による埋め込み（multilingual-e5-large / 1024次元・オフライン可）。

CPUバウンドなため asyncio.to_thread へ逃がす（コーディング規約 §3）。
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from fastembed import TextEmbedding


class FastEmbedClient:
    """EmbeddingClient の fastembed 実装。

    e5 系は "query:" / "passage:" のプレフィックスで精度が上がるため付与する。
    """

    def __init__(self, model_name: str) -> None:
        self._model = TextEmbedding(model_name=model_name)

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        prefixed = [f"passage: {t}" for t in texts]
        return await asyncio.to_thread(self._embed, prefixed)

    async def embed_query(self, text: str) -> list[float]:
        vectors = await asyncio.to_thread(self._embed, [f"query: {text}"])
        return vectors[0]

    def _embed(self, texts: list[str]) -> list[list[float]]:
        return [vec.tolist() for vec in self._model.embed(texts)]
