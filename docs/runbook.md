# 運用 Runbook — Report Insight

対象読者: オンコール担当。障害時の一次対応手順を「迷わず実行できる」粒度で記す。
設計の根拠は [基本設計 §4](02_basic_design.md)・[CI/CD・DevSecOps §5-6](09_cicd_devsecops.md)・
[LLM設計 §5-6](05_llm_design.md)・[ADR-003](adr/ADR-003-llm-strategy.md)。

- リソース命名: `ri-<env>-*`（例 `ri-prod-report-queue` / `ri-prod-report-dlq`）。
- アラームは SNS `ri-<env>-alarms` → Slack。ログは structlog の構造化JSON を CloudWatch Logs へ。
  追跡キーは `request_id`（API）と `report_id` / `source_key`（取込）。
- ダッシュボード: CloudWatch `ri-<env>-overview`（SQS 滞留 / ECS・RDS CPU）。

---

## 0. アラーム → 対応の対応表

| アラーム | 意味 | 一次対応 | 参照 |
|---|---|---|---|
| `ri-<env>-dlq-not-empty` | 取込が3回失敗し DLQ に滞留 | §1 DLQ 再処理 | 基本設計 §4 |
| `ri-<env>-queue-backlog` | 取込キューの滞留（消費が追いつかない） | §4 スループット | |
| 構造化失敗率 > 10%（5分） | 分類/構造化が高頻度で失敗 | §3 構造化失敗 | 基本設計 §4 |
| LLM API エラー率 > 5% | LLM 障害/レート超過 | §2 LLM 縮退 | ADR-003 |
| `ri-<env>-api-cpu-high` / `-rds-cpu-high` | 負荷過多 | §4 スループット | |
| 日次トークンコスト > ¥5,000 | コスト先行検知 | §5 コスト | LLM設計 §5 |

---

## 1. DLQ 再処理手順（`dlq-not-empty`）

**症状**: `ri-<env>-report-dlq` にメッセージ（取込に3回失敗＝`maxReceiveCount=3` 超過）。

### 1-1. 原因の切り分け（先に必ず実施）

1. worker ログを `source_key` で確認し失敗理由を特定する。
   ```bash
   aws logs tail /ecs/ri-<env>/worker --since 1h --filter-pattern '"ingest" "error"'
   ```
2. 失敗の型を判別する:
   - **一過性**（LLM 5xx・レート超過・DB 一時断）→ 復旧後にそのまま再処理でよい（§1-3）。
   - **恒久的**（不正な JSON・存在しない `property_id`・スキーマ不一致）→ 再処理しても再び DLQ 行き。
     §1-2 で対象メッセージを退避・修正してから戻す。
3. 根本原因（LLM 障害等）が継続中なら、先に §2 を実施してから再処理する
   （さもないと再処理分がまた DLQ に戻る）。

### 1-2. 恒久エラーの隔離

- 該当 S3 オブジェクト（`source_key`）を確認し、ペイロードの不備を修正して S3 に再投入すると
  新規イベントとして取り込み直せる（`source_key` 冪等のため、成功済みは二重登録されない）。
- 修正不能な検体は DLQ から受信して別バケットへ退避し、業務側にエスカレーションする。

### 1-3. 再処理（DLQ → 取込キューへ差し戻し）

原因が解消していることを確認してから実行する。SQS のメッセージ移動タスクを使う。

```bash
DLQ_ARN=$(aws sqs get-queue-attributes --queue-url <DLQ_URL> \
  --attribute-names QueueArn --query 'Attributes.QueueArn' --output text)
MAIN_ARN=$(aws sqs get-queue-attributes --queue-url <QUEUE_URL> \
  --attribute-names QueueArn --query 'Attributes.QueueArn' --output text)

# DLQ から元の取込キューへ戻す（source=DLQ, destination=main）
aws sqs start-message-move-task \
  --source-arn "$DLQ_ARN" --destination-arn "$MAIN_ARN"

# 進捗確認
aws sqs list-message-move-tasks --source-arn "$DLQ_ARN"
```

- 差し戻し後、worker が再取込する。数分後に `ri-<env>-report-dlq` の
  `ApproximateNumberOfMessagesVisible` が 0 に戻り、アラームが OK 化することを確認する。
- 大量件数の場合は §4 で worker のタスク数を一時的に増やしてから再処理する。

---

## 2. LLM 障害時の縮退（LLM エラー率 > 5%）

方針: **コード変更なしで段階的に縮退**する（縮退ラダー。LLM設計 §5-6 / ADR-003）。

### 2-1. 縮退ラダー

1. **モデルのフォールバック切替**: 主モデルの障害/レート超過なら、タスク定義の環境変数で
   モデルを切り替えて新リビジョンをデプロイ（ローリング）。
   - `MODEL_CLASSIFY` / `MODEL_GENERATE` を代替モデルへ（ADR-003 の候補）。
   - プロバイダ自体が全断なら一時的に `LLM_PROVIDER` の切替を検討（現状 anthropic 前提）。
2. **取込の一時停止（LLM 全断時）**: 分類は LLM 必須のため、全断中は取り込むほど DLQ が増える。
   worker を 0 タスクに縮退して**取込を止め、キューに滞留させる**（S3/SQS は保持される）。
   復旧後に worker を戻し、必要なら §1-3 で DLQ を再処理する。
   ```bash
   aws ecs update-service --cluster ri-<env>-cluster \
     --service ri-<env>-worker --desired-count 0        # 停止
   # 復旧後
   aws ecs update-service --cluster ri-<env>-cluster \
     --service ri-<env>-worker --desired-count <N>       # 再開
   ```
3. **検索は「メタデータ検索のみ」に自然縮退**: RAG の回答生成が失敗しても、ハイブリッド検索の
   `sources`（該当報告書のメタデータ）は先に返る。利用者へは「AI 回答は一時停止中、
   一覧/検索の該当結果は利用可」と周知する。**管理画面の一覧・フィルタ・未分類キューは
   LLM 非依存**でそのまま使える（F-4）。

### 2-2. 注意

- LLM 起因の品質劣化（モデル側の変動・コード無変更）は**デプロイのロールバックでは直らない**。
  縮退ラダーで対応する（CI設計 §5）。
- 復旧判断は LLM エラー率とダッシュボードで確認し、モデルを戻す場合も再度ローリングで反映する。

---

## 3. 構造化失敗率アラート対応（> 10% / 5分）

**症状**: 分類/構造化の失敗（`status=failed` や例外）が 5 分間で 10% 超。

1. 原因を切り分ける:
   - LLM 障害 → §2 の縮退ラダー。
   - **プロンプト/スキーマ回帰**（直近の `prompts/` 変更が Structured Output を壊した）
     → 該当変更を `git revert` し、`prompts/` 変更は CI の LLM 回帰評価（§4.5）を必ず通す。
   - 入力データ品質の悪化（悪文・文字化けの急増）→ 業務側へ連携。needs_review が増えるのは
     設計どおりの安全側挙動（低確信度は自動確定せず人手レビューへ回る）。
2. 影響範囲は `report_id` / `source_key` でログ追跡。失敗分は DLQ 経由で §1 のとおり再処理。
3. 恒久対策: プロンプトのバージョンを上げて修正し（規約 §8）、回帰評価の閾値
   （分類 accuracy ≥ 90% 等。LLM設計 §4）で担保する。

---

## 4. スループット/滞留（`queue-backlog` / CPU high）

- 取込滞留: worker を増やす。
  ```bash
  aws ecs update-service --cluster ri-<env>-cluster \
    --service ri-<env>-worker --desired-count <N>
  ```
- api CPU 高騰: api はターゲット追従オートスケール済み（CPU 70%）。上限（`api_max_count`）に
  張り付く場合は tfvars で上限を引き上げ、Terraform 経由で反映（手動変更は禁止。IaC戦略 §7）。
- RDS CPU 高騰: スロークエリを確認。恒久対策はインスタンスクラス変更（tfvars）で。

---

## 5. コスト先行検知（日次トークンコスト > ¥5,000）

- ダッシュボードと `input_tokens`/`output_tokens` ログ（LLM設計 §5）で急増源を特定する
  （分類 or 生成、特定物件のスパイク等）。
- 一過性でなければモデル選定・プロンプト長・チャンク設計を見直す。月次予算 ¥100,000 の
  先行指標として扱い、超過が続く場合はエスカレーション。

---

## 6. デプロイ/DB 関連

- デプロイ失敗はデプロイサーキットブレーカーで自動ロールバック（CI設計 §5）。手動確認は
  `/readyz` と主要API（一覧・検索・月次取得）の 200。
- DB マイグレーションは **expand-contract（後方互換）** が原則。`alembic downgrade` は開発用であり
  **本番ロールバック手段にしない**（CI設計 §5）。ローリング中に新旧タスクが混在しても動くよう
  「カラム追加→デプロイ→旧カラム削除は次リリース」に分割する。

---

## 7. エスカレーション

1. 一次対応（本 Runbook）で 30 分以内に収束しない、または影響が拡大している場合は
   開発担当へエスカレーション。
2. データ不整合・情報漏えいの疑い（他支店データ混入等）は即時エスカレーションし、
   `audit_logs`（検索・承認・分類上書き）と CloudWatch Logs を保全する。
3. 対応内容・タイムライン・恒久対策を障害記録として残す（次回の Runbook 改善に反映）。
