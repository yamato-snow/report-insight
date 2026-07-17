---
date: 2026-07-18
model: opus
status: ready
issue: ""
topic: report-insight P1 実装（F-3/F-4・評価・IaC・CI仕上げ）引き継ぎ
predecessor: report-insight-1day_plan.md
---

# report-insight P1 実装計画（別セッション引き継ぎ）

このドキュメントは **P0 完了後の状態を新しい実装セッション（Opus）へ引き継ぐ**ためのもの。
まず「## 1. 現在地」と「## 3. 引き継ぎ注意（P0の仮定・落とし穴）」を読んでから着手すること。
設計判断に迷ったら docs/（06=構造・09=CI・11=IaC）が正。軽微な逸脱は「仮定:」を明記して続行、
根幹が崩れる場合のみ中断して報告（P0と同じ運用）。

---

## 1. 現在地（P0 完了・2026-07-18）

- ブランチ: `feat/p0-scaffold-ingest-search`（コミット `c116fb1`。リモート未設定）
- 完了: **足場 / F-1 取込パイプライン / F-2 RAG検索**
- 品質ゲート: `make lint`（ruff + mypy strict + import-linter 3契約）green /
  unit 16件・integration 10件 green / `docker compose up → make demo` で 100件が
  S3→SQS→worker→DB まで自動通過（緊急通知23件を webhook-mock で確認）

### すでに動く主要フロー
- 取込: `app/services/ingest.py`（マスキング→分類→埋め込み→冪等UPSERT→通知）
- 検索: `app/services/search.py`（ハイブリッド検索→SSE→引用検証→0件ショートサーキット）
- API: `POST /api/v1/search`（SSE）, `/healthz`, `/readyz`（`app/api/`）
- worker: `app/worker/main.py`（SQS→ingest。失敗は再配信、3回で DLQ）

---

## 2. アーキテクチャ早わかり（新セッション用）

```
app/
├── core/       config.py(pydantic-settings) / db.py(unit_of_work) / di.py(composition root) / logging.py
├── domain/     entities.py / values.py(Enum) / errors.py   ← 外部依存ゼロ（import-linterで強制）
├── services/   ports.py(Protocol) / ingest.py / search.py  ← infra を import しない
├── infra/      db(models/repositories/mappers/migrations) / llm(anthropic+fake+prompts) /
│               embedding(fastembed+fake) / aws(s3/sqs) / masking(pii) / notify(slack)
├── api/        main.py / deps.py / error_handlers.py / schemas.py / sse.py / routers/
└── worker/     main.py
```

- **依存方向 `api|worker → services → domain`**。infra はポート実装のみ。組み立ては `core/di.py` のみ。
- **新しい外部I/Oを足すときは必ず `services/ports.py` に Protocol を追加 → infra に実装 → `core/di.py` で結線**。
  services から infra を直接 import すると import-linter が落ちる。
- ORM(`infra/db/models.py`) ⇔ ドメイン(`domain/entities.py`) は `infra/db/mappers.py` で変換。
- 認可は `SqlSearchRepository.permitted_property_ids` と各SQLの `property_id IN (...)` で強制（アプリ層で漏らさない）。
- テストは Fake ポート（`tests/unit/fakes.py`）で完結。integration は testcontainers+pgvector（`tests/integration/conftest.py`）。

---

## 3. 引き継ぎ注意（P0の仮定・落とし穴）※必読

1. **env ファイル名**: 実装環境の保護ガードで `.env.example` を作成できず `env.example`（ドット無し）で提供。
   `cp env.example .env`。新セッションでも `.env*` への Write/mv はガードで拒否される可能性が高い。
2. **埋め込みは provider 連動**: `LLM_PROVIDER=fake` の時は `FakeEmbeddingClient`（文字bigramハッシュ・
   決定的・オフライン）、`anthropic` の時のみ fastembed(e5-large)。`core/di.py:_build_embedder` 参照。
   → **評価(§4.3 Eval)や実LLM検証時は `.env` で `LLM_PROVIDER=anthropic` + `ANTHROPIC_API_KEY` 必須**。
3. **sudachipy Tokenizer はスレッド非安全**（"Already borrowed"）。`infra/masking/pii.py` で
   スレッドローカル化済み。新たに CPU バウンド処理を `asyncio.to_thread` で回すときは同じ罠に注意。
4. **SSE のDBセッション**: `api/routers/search.py` はジェネレータ内で `session_factory()` を開く
   （yield依存だとストリーム消費前に閉じるため）。月次PDF等でストリーミングする場合も同様に。
5. **0件ショートサーキットの意味**: DB設計§2のクエリに類似度閾値は無いので、`no_results` は
   「認可スコープ内に行が無い場合」に発火する。意味的に薄い一致は top-k を返し、回答プロンプトが
   「該当事例なし」を強制する二層構成。閾値を入れるなら設計文書側も更新すること。
6. **`confidence` カラムは `Float(precision=24)`（PG REAL 相当）**。SQLAlchemyに `Real` は無い。
7. **モデルID**: `env.example` は `claude-haiku-4-5-20251001` / `claude-sonnet-5`。実在IDに合わせて調整。
8. `pyproject.toml` に `app/api/routers/ui.py` の E501 per-file-ignore が既にある（P1のUI埋め込みHTML用の先行設定）。
9. **runtime Docker イメージは `--no-dev`**（Dockerfile）。dev依存(pytest等)はホスト/CIでのみ。
   新しい**実行時**依存を足したら `pyproject` の `[project].dependencies` 側へ（devに入れると本番で不足する）。
10. 監査ログ(`audit_logs`)テーブルは作成済みだが**まだ書き込んでいない**。§4.2 で検索・承認時に記録する。

---

## 4. P1 タスク分解（優先順・完了条件・該当設計）

推奨実装順: **4.1 F-3 → 4.2 F-4 → 4.3 評価 → 4.4 IaC → 4.5 CI仕上げ → 4.6 runbook**。
F-3/F-4 は 1本ずつ feat ブランチ + 1 PR = 1関心事（規約 §7）。Alembic リビジョンは PR あたり最大1本。

### 4.1 F-3 月次報告書（`services/monthly.py` 新規） — 設計: 02 §2.3 / 03 / 05 §2
- SQLで件数サマリ（分類別・緊急度別）を**確定計算**し、LLMには**文章化のみ**渡す（数値ハルシネーション防止）。
- ステータス機械: `generating → draft →(approve)→ approved`。同一物件×月の再生成は version+1 で保持。
- **approved 後の編集は `InvalidStateError`（→422）**。承認は `audit_logs` に記録。
- PDF: WeasyPrint（Markdown→HTML→PDF）。`infra/pdf/` を新設しポート `PdfRendererPort` を追加。
  ネイティブ依存はコンテナ内で完結（Dockerfile に pango/cairo 導入済み）。
- 生成は非同期(202)。P0の worker とは別に、API内 background task か既存 worker に月次ジョブ種別を追加。
  → **推奨: 生成もSQS経由にせず、`POST /monthly-reports` で 202 を返し `asyncio.create_task` かDBステータス
    ポーリングで実装**（要件は「生成中は202→ポーリングでdraft」）。設計を大きく変えないこと。
- 追加エンドポイント: `POST /monthly-reports` / `GET /monthly-reports/{id}`(生成中202) /
  `PATCH /monthly-reports/{id}`(save/approve) / `GET /monthly-reports/{id}/pdf`。
- 完了条件: generate(202)→draft→編集→approve→PDF がAPI経由で通り、approved後の編集が422。integrationテスト。

### 4.2 F-4 管理画面 + 権限（`api/routers/reports.py`, `ui.py`, `templates/`） — 設計: 03 §2-4 / 05 §7
- 追加API: `GET /reports`(カーソルページング・フィルタ) / `GET /reports/{id}` /
  `PATCH /reports/{id}/analysis`(人間修正→`human_verified`) / `GET /reports/review-queue`(needs_review) /
  `GET /properties`(権限内のみ)。**リポジトリに list/review_queue/list_properties を追加**
  （`get`/`update_analysis` は実装済み）。
- 権限マトリクス（03 §4）を実装。**他支店の `GET /reports/{id}` は403**（`SqlReportRepository.get` は
  既に PermissionDenied を投げるので配線するだけ）。検索の混入防止はP0で担保済み。
- 管理画面: Jinja2 + HTMX（SPAにしない。02 §1）。一覧/フィルタ/検索/承認/未分類キュー。
  **LLM出力Markdownのレンダリングは必ずサニタイズ（XSS。05 §7）**。`ui.py` の per-file-ignore は用意済み。
- 監査: 検索・承認・分類上書きを `audit_logs` に記録（03/09 §6）。SqlAuditRepository を追加。
- 完了条件: 一覧フィルタ・検索・未分類キュー・月次承認が操作可能（手動確認可）。
  **支店管理者が他支店にアクセスで403（検索混入なし）のテスト**必須。

### 4.3 LLM評価（`tests/llm_eval/`） — 設計: 05 §4 / 完了条件で README 記録
- 評価セット3種: 分類100（`scripts/synth.py` の Sample.label を再利用。**既に正解ラベル付きで生成可能**）/
  検索30問（質問+正解report_id）/ 忠実性20問（LLM-as-judge）。
- ハーネス `tests/llm_eval/run.py`（`make eval`。実API・要APIキー）。メトリクス: 分類accuracy≥90%、
  緊急度high recall≥95%、recall@8≥85%、忠実性≥4.0、引用実在率100%。
- **プロンプトインジェクション検体**（synth の `tags=["injection"]` サンプル）で分類が汚染されないことを検証。
- 1回実行して結果を README のステータス欄に記録。
- 注意: 評価は実LLM+fastembed（`LLM_PROVIDER=anthropic`）。§3-2 参照。コストは1回約¥300想定。

### 4.4 Terraform（`terraform/`） — 設計: 02 §5 / 11 / ADR-004
- modules 5種: network / ecs(api+worker) / rds(pgvector) / pipeline(S3+SQS+DLQ+通知) / observability。
- envs/dev（+ prod は tfvars 差分のみ）。ステート=S3+DynamoDBロック。シークレット非保持（11が正）。
- 完了条件: `terraform validate` と `terraform plan`（envs/dev・ダミーtfvars）が通る。**apply はP2（任意）**。

### 4.5 CI 仕上げ（`.github/workflows/ci.yml` 拡張） — 設計: 09 §1-2 が正
- P0はlint+unitのみ。追加: gitleaks → bandit(SAST) → pip-audit(SCA) → integration →
  `prompts/`変更時のみLLM回帰評価 → main で Docker build → Trivy(image) → SBOM(Syft)。
- IaC変更時 Trivy(config)。OIDCフェデレーション（静的キーゼロ）。main ブランチ保護。
- Alembic の `upgrade→downgrade→upgrade` を integration ジョブで検証（DB設計§3）。

### 4.6 運用 Runbook（`docs/runbook.md`） — 設計: 09 §6 / 02 §4
- DLQ 再処理手順・LLM障害時の縮退（メタデータ検索のみ）・構造化失敗率アラート対応。

---

## 5. 動かし方・検証コマンド

```bash
uv sync --all-extras
cp env.example .env
make up && make migrate && make demo   # フルパイプライン確認
make test              # unit（速い）
make test-integration  # testcontainers+pgvector（Docker必須）
make lint              # ruff + mypy strict + import-linter（マージ前必須）
make eval              # 実API評価（要 LLM_PROVIDER=anthropic + APIキー）
```

- P1で新エンドポイントを足したら **integration の TestClient テスト**を追加（`tests/integration/test_search_pipeline.py` が雛形）。
- 変更後は必ず `make lint` と両テストを green にしてから 1 PR = 1関心事でコミット（規約 §7）。

---

## 6. スコープ外（今回も対象外・要件定義どおり）
- AWS 本番相当環境の運用 / SSO(SAML)実接続（AuthBackend 抽象のまま）/ 現行システム実連携 /
  写真画像解析（Phase 2）/ PDFの精緻デザイン・多言語。

## 7. ロールバック
- 新規リポジトリ・外部副作用なし。コミット単位 `git revert`、ローカルDBは `make down-v` で再構築。
