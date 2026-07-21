# Report Insight — タスクランナー（開発環境セットアップ 08 §5）
.DEFAULT_GOAL := help
COMPOSE := docker compose

.PHONY: help setup up down down-v migrate demo test test-integration test-pdf check-mermaid eval eval-loop scenario lint fmt shell logs

help: ## このヘルプを表示
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

setup: ## uv sync + pre-commit install + 埋め込みモデル事前DL
	uv sync --all-extras
	uv run pre-commit install || true
	uv run python -m app.infra.embedding.download

up: ## docker compose up -d（db/localstack/api/worker/webhook-mock）
	$(COMPOSE) up -d --build

down: ## compose 停止
	$(COMPOSE) down

down-v: ## compose 停止 + DB含め全消去
	$(COMPOSE) down -v

migrate: ## Alembic upgrade head
	$(COMPOSE) run --rm api alembic upgrade head

demo: ## 合成報告書100件を生成→S3投入→処理完了待ち→件数レポート
	$(COMPOSE) run --rm api python -m scripts.seed_demo --count 100

test: ## unit テスト（外部I/Oなし・高速）
	uv run pytest tests/unit -q

test-integration: ## integration テスト（compose の db/localstack を使用）
	uv run pytest -m integration -q

eval: ## LLM評価ハーネス（実API・要APIキー。LLM設計書 §4）
	uv run python -m tests.llm_eval.run

eval-loop: ## 劣化検知→改善フローの閉ループ実証（実APIなし・決定的・課金ゼロ）
	uv run python -m tests.llm_eval.loop_demo

scenario: ## 受入シナリオ（実APIなし・決定的・課金ゼロ）。NAME=xxx で1本に絞る
	uv run python -m tests.scenarios.run $(if $(NAME),--name $(NAME),)

check-mermaid: ## docs の Mermaid 図が GitHub で描画できるか検証（要 node）
	npm install --no-save --silent mermaid@11
	node scripts/check_mermaid.mjs

test-pdf: ## PDFの日本語描画テスト（WeasyPrintのネイティブ依存があるコンテナ内で実行）
	$(COMPOSE) run --rm api uv run --with pytest --with pytest-asyncio \
		pytest tests/pdf -q -p no:cacheprovider

lint: ## ruff + mypy + import-linter
	uv run ruff check app tests
	uv run ruff format --check app tests
	uv run mypy app
	uv run lint-imports

fmt: ## 自動整形
	uv run ruff check --fix app tests
	uv run ruff format app tests

shell: ## api コンテナのシェル
	$(COMPOSE) run --rm api bash

logs: ## worker/api のログ追尾
	$(COMPOSE) logs -f api worker
