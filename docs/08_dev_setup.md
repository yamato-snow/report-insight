# 開発環境セットアップ — Report Insight

| 項目 | 内容 |
|---|---|
| 文書バージョン | 1.0 |
| 方針 | **ローカルは Docker Compose で完結**。AWS 実環境なしでフル機能をデモできる |

---

## 1. 前提ツール

| ツール | バージョン | 用途 |
|---|---|---|
| Docker Desktop | 最新 | compose 一式の実行 |
| uv | 最新 | Python 依存管理・仮想環境 |
| make | - | タスクランナー |

Python 3.12 本体は uv が自動取得するためインストール不要。

## 2. クイックスタート

```bash
git clone <repo> && cd report-insight
make setup          # uv sync + pre-commit install + 埋め込みモデルの事前DL
cp .env.example .env   # ANTHROPIC_API_KEY のみ自分の値に書き換え
make up             # docker compose up -d（db / localstack / api / worker / webhook-mock）
make migrate        # Alembic マイグレーション適用
make demo           # 合成報告書100件を S3(LocalStack) に投入 → 取込→構造化まで自動実行
open http://localhost:8000   # 管理画面
```

`ANTHROPIC_API_KEY` を設定しない場合も `LLM_PROVIDER=fake` にすれば FakeLLMClient で全フローが動く（分類は決定的なスタブ値。デモ・開発の既定はこちら）。

## 3. Docker Compose 構成

| サービス | イメージ / 内容 | ポート |
|---|---|---|
| db | pgvector/pgvector:pg16 | 5432 |
| localstack | localstack/localstack（S3・SQS） | 4566 |
| api | 本リポジトリ Dockerfile（FastAPI, ホットリロード） | 8000 |
| worker | 同上（SQSコンシューマ） | - |
| webhook-mock | 通知ペイロード検証用の受け口（緊急度「高」通知が届く先） | 9000 |

- api / worker はソースを bind mount し、変更は即時反映（uvicorn --reload / worker は watchfiles）
- localstack は起動時 init スクリプトでバケット・キュー・S3イベント通知を作成（healthcheck で db/localstack の ready を待ってから api/worker が起動）
- 本番との差分は「AWSエンドポイントURL」の env 1点のみに閉じる（[アーキテクチャ規約 §3](06_architecture.md) の infra/aws）

## 4. 環境変数（.env.example）

```bash
# --- LLM ---
LLM_PROVIDER=fake                  # fake | anthropic
ANTHROPIC_API_KEY=
MODEL_CLASSIFY=claude-haiku-x      # 分類・構造化（Haiku級）
MODEL_GENERATE=claude-sonnet-x     # RAG回答・月次報告書（Sonnet級）
LLM_MAX_CONCURRENCY=4
CONFIDENCE_THRESHOLD=0.85          # 未満は needs_review へ

# --- AWS（ローカルは LocalStack） ---
AWS_ENDPOINT_URL=http://localstack:4566
AWS_REGION=ap-northeast-1
S3_INBOX_BUCKET=report-inbox
SQS_QUEUE_URL=http://localstack:4566/000000000000/report-queue

# --- DB / 通知 ---
DATABASE_URL=postgresql+asyncpg://app:app@db:5432/report_insight
SLACK_WEBHOOK_URL=http://webhook-mock:9000/webhook
```

シークレットの実値は `.env`（gitignore 済み）のみ。本番は Secrets Manager（基本設計 §3）。

## 5. Make ターゲット一覧

| ターゲット | 内容 |
|---|---|
| `make setup` | uv sync・pre-commit install・埋め込みモデルDL |
| `make up` / `make down` | compose 起動 / 停止（`down-v` でDB含め全消去） |
| `make migrate` | Alembic upgrade head |
| `make demo` | 合成報告書100件の生成→S3投入→処理完了待ち→件数レポート |
| `make test` | unit テスト（外部I/Oなし・高速） |
| `make test-integration` | integration テスト（compose の db/localstack を使用） |
| `make eval` | LLM評価ハーネス実行（実API・要APIキー。LLM設計書 §4） |
| `make lint` / `make fmt` | ruff + mypy + import-linter / 自動整形 |

## 6. よくあるトラブル

| 症状 | 対処 |
|---|---|
| worker が起動直後に落ちる | localstack の init 完了前に接続している。`make up` は healthcheck 待ちを含むため、単体 `docker compose up worker` を避ける |
| 埋め込み生成が初回だけ遅い | モデルDLが走っている。`make setup` の事前DLを実行したか確認 |
| WeasyPrint のビルドエラー | ローカルに直接インストールしない。PDF生成はコンテナ内でのみ実行される設計 |
| Apple Silicon で localstack が不安定 | `platform: linux/amd64` 指定を外す（compose.yaml のコメント参照） |

## 7. 開発フロー

1. ブランチを切る（[コーディング規約 §7](07_coding_standards.md)）
2. 実装 → `make test` → `make lint`（pre-commit でも自動実行）
3. infra 変更時のみ `make test-integration`、プロンプト変更時のみ `make eval`
4. PR 作成（CI: lint → test → 条件付き eval。基本設計 §6）
