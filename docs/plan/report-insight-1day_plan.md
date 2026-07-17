---
date: 2026-07-17
model: fable
status: draft
issue: ""
topic: report-insight 1日実装計画
---

# report-insight 1日実装計画

## 背景

AIソリューション受託案件（バックエンド）応募用ポートフォリオ。設計ドキュメント（要件定義・基本設計・API/DB/LLM設計・ADR×3）は本リポジトリ docs/ に整備済み。**フルスコープ（F-1〜F-4＋評価＋IaC＋CI/CD）を1日で実装する。**

昇格理由: 新規構築で技術選定・設計判断が集中するため Fable 設計（F1: 設計判断の密度が高いタスク相当）。

## 前提（設計は docs/ が正。実装時に読み直すこと）

- [基本設計書](../02_basic_design.md)（構成図・処理フロー）
- [API設計書](../03_api_design.md) / [DB設計書](../04_db_design.md) / [LLM設計書](../05_llm_design.md)
- [アーキテクチャ規約](../06_architecture.md)（**ディレクトリ構造・依存ルールはこれが正**。import-linter で機械検査）
- [コーディング規約](../07_coding_standards.md) / [開発環境セットアップ](../08_dev_setup.md)（compose 構成・env・Make ターゲットはここで確定済み）
- [CI/CD・DevSecOps設計](../09_cicd_devsecops.md)（CIのゲート構成はこれが正）/ [テスト計画書](../10_test_plan.md)（テストレベル定義・トレーサビリティ・出口基準）

### 実装レベルの確定事項（ドリフト防止のためここで固定）

| 項目 | 決定 |
|---|---|
| ランタイム | Python 3.12 / FastAPI / SQLAlchemy 2 (async) / Alembic / uv |
| ローカル環境 | docker compose: PostgreSQL16+pgvector, LocalStack(S3/SQS)。AWS SDK のエンドポイントを env で切替 |
| LLM | anthropic SDK。モデルIDは env 設定（分類=Haiku級 / 生成=Sonnet級）。テストは FakeLLMClient、評価のみ実API |
| 埋め込み | fastembed の multilingual-e5-large（1024次元・オフライン可）。`EmbeddingClient` 抽象で Voyage 等へ切替可能に |
| 通知 | Slack Incoming Webhook（ローカルはモックサーバでペイロード検証） |
| PDF | WeasyPrint（Markdown→HTML→PDF、デザインは最小） |
| フロント | Jinja2 + HTMX（基本設計 §1 の方針どおり SPA にしない） |
| デモデータ | 合成報告書ジェネレータで100件（境界例・悪文・表記ゆれを含める。評価セットと共用） |
| lint/型 | ruff + mypy(strict は core/domain のみ) |

## 実施順序（1日タイムボックス）

| ブロック | 内容 | 優先度 |
|---|---|---|
| 午前① | 足場: pyproject/uv, docker compose, Alembic 初期マイグレーション（DB設計書の全テーブル）, core/(設定・DB・ロギング), CI 骨格 | P0 |
| 午前② | F-1 取込パイプライン: LocalStack S3→SQS→worker, PIIマスキング, 分類・構造化(structured output), confidence 閾値→needs_review, 緊急度高→Webhook通知, 冪等UPSERT | P0 |
| 午後① | F-2 RAG検索: 埋め込み生成, ハイブリッド検索SQL(認可フィルタ込み), POST /search SSE(sources→token→done), 引用実在検証, 0件ショートサーキット | P0 |
| 午後② | F-3/F-4: 月次報告書(SQL集計→LLM文章化→draft→approve→PDF), 管理画面(一覧/フィルタ/検索/承認/未分類キュー), 権限マトリクス実装 | P1 |
| 夕方① | LLM評価: 評価セット合成(分類100/検索30/忠実性20), 評価ハーネス, 1回実行して結果を README に記録 | P1 |
| 夕方② | Terraform 一式(modules 5種+envs/dev), GitHub Actions 仕上げ（09のセキュリティゲート含む）, 運用Runbook(docs/runbook.md: DLQ再処理・縮退手順), README のセットアップ手順・ステータス更新 | P1 |
| ストレッチ | AWS dev 環境へ terraform apply + 実デプロイ, デモ動画(2分) | P2 |

P0 が崩れたら P1 以降を翌日に送る判断をユーザーに仰ぐ（スコープ自体は削らない）。

## 対象範囲

本リポジトリ（products/report-insight）のみ。`app/` `tests/` `terraform/` `compose.yaml` `.github/workflows/` `scripts/`（デモデータ生成）、および README の実行手順・ステータス欄。docs/ の設計文書は原則変更しない（実装と食い違ったら「実装時差分」をここに追記して設計文書側を直す）。

## 完了条件

- [ ] `docker compose up` → `make demo` で合成報告書100件が S3(LocalStack)投入→SQS→worker 構造化→DB 保存まで自動で通る
- [ ] 緊急度「高」の報告書でモックWebhookに通知ペイロードが届くことをintegrationテストで検証
- [ ] confidence < 0.85 の報告書が needs_review になり `GET /reports/review-queue` に出る
- [ ] `POST /search` が SSE（sources→token→done）で回答し、引用は実在検証済みIDのみ。検索0件時は no_results イベントで LLM 非呼び出し
- [ ] 月次報告書が generate(202)→draft→編集→approve→PDF まで API 経由で通り、approved 後の編集が 422 になる
- [ ] 管理画面で一覧フィルタ・検索・未分類キュー・月次承認が操作できる（手動確認でよい）
- [ ] 支店管理者が他支店の報告書にアクセスすると 403（検索結果にも混入しない）テストがある
- [ ] pytest（unit + integration。integration は testcontainers or compose 上のDB実物）が全て green
- [ ] `tests/llm_eval/` に評価セット3種とハーネスがあり、実APIで1回実行した結果（分類accuracy・緊急度高recall・recall@8・忠実性・引用実在率）を README に記録
- [ ] `terraform validate` と `terraform plan`（envs/dev、ダミーtfvars）が通る
- [ ] GitHub Actions: lint(ruff/mypy/import-linter)→gitleaks→SAST(bandit)→SCA(pip-audit)→test は毎PR、LLM回帰評価は prompts 変更時のみ、main で build→Trivy スキャン→SBOM 生成まで定義済み（09_cicd_devsecops.md §1-2 のゲート構成に従う）
- [ ] 評価セットにプロンプトインジェクション攻撃サンプルが含まれ、分類が汚染されないことを回帰評価で検証（LLM設計書 §7）
- [ ] `docs/runbook.md`（DLQ再処理・LLM障害時縮退の手順）が存在する
- [ ] README のセットアップ/実行手順どおりに（APIキー以外）ゼロから再現可能で、ステータス欄が実態と一致

## 対象外（今回やらないこと）

- AWS 本番相当環境の構築・運用（dev への apply はストレッチのみ。やらなくても完了）
- SSO(SAML) の実接続（`AuthBackend` 抽象＋セッション認証代替。基本設計 §3 どおり）
- 現行報告システムとの実連携（S3 への直接 PUT で代替）
- 写真画像の解析（要件定義でも Phase 2）
- PDF の精緻なデザイン、多言語対応
- 要件定義書・基本設計書の大幅改稿（実装差分の追記のみ可）

## ロールバック方法

- 新規リポジトリのため、コミット単位の `git revert` または直近タグへの `git reset --hard` で戻せる。外部システムへの副作用なし
- ローカルDBは `docker compose down -v` で全消去・再構築可能
- ストレッチで AWS apply した場合のみ `terraform destroy`（envs/dev）で全撤去

## リスク

| リスク | 対応 |
|---|---|
| 1日でフルスコープは実装量が多い | 優先度 P0→P1→P2 の順に完了条件を満たす。P0 完了時点で一度コミット＆報告 |
| 実API評価のコスト・レート | 評価は夕方に1回のみ。開発中は FakeLLMClient |
| fastembed モデルDLに時間 | 午前①の足場段階で先行DLを Makefile に入れる |
| WeasyPrint のネイティブ依存 | Docker イメージ内で完結させる（ローカル直インストールに依存しない） |
