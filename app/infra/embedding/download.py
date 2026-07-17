"""埋め込みモデルの事前DL（make setup / Makefile。開発環境 08 §5）。"""

from __future__ import annotations

from fastembed import TextEmbedding

from app.core.config import get_settings


def main() -> None:
    settings = get_settings()
    print(f"事前DL: {settings.embedding_model}")  # noqa: T201 — CLI ユーティリティ
    TextEmbedding(model_name=settings.embedding_model)
    print("完了")  # noqa: T201


if __name__ == "__main__":
    main()
