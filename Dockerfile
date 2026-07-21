# syntax=docker/dockerfile:1
# Report Insight — api / worker / webhook-mock 共通イメージ
# WeasyPrint のネイティブ依存をコンテナ内で完結させる（開発環境 08 §6）
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

# WeasyPrint(pango/cairo) と fastembed(onnxruntime) の実行時ライブラリ。
# fonts-noto-cjk は月次報告書PDFの日本語描画に必須（無いと全文字が豆腐□になる。F-3-3）。
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpango-1.0-0 libpangocairo-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 \
        libffi-dev libjpeg62-turbo shared-mime-info \
        libgomp1 \
        fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.8.8 /uv /usr/local/bin/uv

WORKDIR /app

# 依存だけ先に解決してレイヤキャッシュを効かせる（runtimeイメージは dev 依存を含めない）
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-install-project --no-dev

# アプリ本体
COPY . .
RUN uv sync --no-dev

EXPOSE 8000
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
