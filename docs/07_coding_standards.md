# コーディング規約 — Report Insight

| 項目 | 内容 |
|---|---|
| 文書バージョン | 1.0 |
| 原則 | **規約は可能な限りツールで機械的に強制する**（人間のレビューは設計判断に使う） |

---

## 1. ツールチェーン（pyproject.toml で一元管理）

| ツール | 用途 | 実行タイミング |
|---|---|---|
| ruff | lint + format（Black互換） | pre-commit / CI |
| mypy | 型検査（domain/services は strict） | pre-commit / CI |
| import-linter | レイヤ依存方向の機械検査（[アーキテクチャ規約 §2](06_architecture.md)） | CI |
| pytest | テスト | CI |
| pre-commit | 上記のコミット前フック | ローカル |

### 主要設定（抜粋）

```toml
[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "ASYNC", "S", "PL", "RUF"]
# S: bandit系セキュリティ / ASYNC: ブロッキングI/O検出 / PL: pylint系

[tool.mypy]
python_version = "3.12"
strict = true            # domain / services / infra に適用
# api/templates 周りのみ個別緩和を許可（理由コメント必須）
```

## 2. 型・命名

- 全公開関数に型アノテーション必須。`Any` は domain / services で禁止（infra の外部SDK境界のみ許可、理由コメント必須）
- Enum は `domain/values.py` に集約。文字列リテラルの分類値（`"high"` 等）をロジック中に直書きしない
- 命名：モジュール/関数 `snake_case`、クラス `PascalCase`、定数 `UPPER_SNAKE`。略語は禁止（`rpt` ✗ `report` ✓）。ドメイン用語は要件定義書の用語に合わせる（例：`urgency`、`normalized_summary`）

## 3. 非同期の規約

- API・services・infra は async で統一。**イベントループ内でのブロッキングI/O禁止**（ruff ASYNC ルールで検出）
- CPUバウンド処理（埋め込み生成・形態素解析）は `asyncio.to_thread` へ逃がす
- LLM 呼び出しの同時実行数は `asyncio.Semaphore` で制御し、値は設定（env）に出す

## 4. エラー処理

- ドメイン例外（`domain/errors.py`）以外を services から投げない。外部SDK例外は infra で捕捉してドメイン例外 or リトライ可能例外に変換する
- `except Exception` の握りつぶし禁止。捕捉するなら「ログ＋status 更新＋再送出 or DLQ 行き」のいずれかを必ず行う
- worker は**リトライ可能（レートリミット・一時障害）／不能（パース不能データ）**を例外型で区別し、不能は即 DLQ・可能は SQS 再配信に任せる
- API のエラー応答は Problem Details（[API設計書 §1](03_api_design.md)）。変換は `api/error_handlers.py` のみで行う

## 5. ロギング

- structlog の構造化JSONのみ。`print` 禁止
- 必須バインド：`request_id`（API）／`report_id`・`source_key`（worker）
- **PII・報告書原文をログに出さない**（マスキング後テキストのみ可）。LLM呼び出しはトークン数・モデルID・レイテンシを必ず記録（コスト集計の一次データ。LLM設計書 §5）

## 6. テスト規約

| 種別 | 対象 | ルール |
|---|---|---|
| unit | domain / services | Fake ポートのみ使用。外部I/Oゼロ・1件100ms以内 |
| integration | infra / API | compose 上の実 PostgreSQL・LocalStack を使用。`@pytest.mark.integration` |
| llm_eval | プロンプト品質 | 実API。CI ではプロンプト変更時のみ（LLM設計書 §4） |

- テスト名は `test_<対象>_<条件>_<期待>`（例：`test_ingest_low_confidence_marks_needs_review`）
- Arrange-Act-Assert を空行で分離。1テスト1検証観点
- LLM の非決定性をテストに持ち込まない：unit/integration は必ず FakeLLMClient。「たまに落ちるテスト」を作らない

## 7. Git / PR 規約

- ブランチ：`feat/f1-ingest-pipeline` 形式（`feat|fix|docs|refactor|chore/<内容>`）
- コミット：Conventional Commits（`feat: 取込パイプラインの冪等UPSERTを実装`）。日本語可
- 1 PR = 1 関心事、Alembic リビジョンは PR あたり最大1本（DB設計書 §3）
- PR 説明に「plan からの逸脱・仮定」を明記する欄を設ける（`仮定:` 記法。plan-handoff 運用と整合）

## 8. ドキュメント

- 公開サービス関数に docstring（Google スタイル・日本語可）。自明な private 関数には不要
- 設計判断の変更は ADR 追加（軽量5行でよい）。docs/ とコードが食い違ったら**同一PRで docs を直す**
- プロンプト変更は `infra/llm/prompts/` のバージョン番号を上げ、旧版を残す（品質トレースのため。DB に prompt_version を記録している）
