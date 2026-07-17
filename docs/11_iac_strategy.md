# IaC戦略 — Report Insight

| 項目 | 内容 |
|---|---|
| 文書バージョン | 1.0 |
| ツール | Terraform（選定理由: [ADR-004](adr/ADR-004-iac-tool.md)） |
| 原則 | **コンソール手動変更の禁止**。すべての変更は PR → plan レビュー → apply の経路のみ |

---

## 1. ディレクトリ構成

```
terraform/
├── envs/
│   ├── dev/
│   │   ├── main.tf          # モジュール呼び出しのみ（リソース直書き禁止）
│   │   ├── backend.tf       # env別ステート
│   │   └── terraform.tfvars # env差分（インスタンスサイズ・AZ数等）
│   └── prod/
└── modules/
    ├── network/       # VPC・サブネット・SG・VPCエンドポイント
    ├── ecs/           # クラスタ・サービス・タスク定義（api / worker）・オートスケール
    ├── rds/           # PostgreSQL + pgvector・パラメータグループ・バックアップ
    ├── pipeline/      # S3・SQS・DLQ・イベント通知
    └── observability/ # CloudWatch ダッシュボード・アラーム・ロググループ
```

- **環境差分は tfvars のみで表現する**。`count`/`for_each` による env 分岐をモジュール内に書かない（dev で検証した構成がそのまま prod になる保証を壊さないため）
- Terraform Workspace は使わない（backend 分離のほうが事故時の爆発半径が明確）

## 2. ステート管理

| 項目 | 設計 |
|---|---|
| バックエンド | S3（バージョニング有効・SSE暗号化）＋ DynamoDB ロック |
| 分離単位 | env ごとに別 state（dev の破壊操作が prod に波及しない） |
| アクセス | state バケットは CI ロールと管理者のみ。state には機微値が入り得るため閲覧権限も絞る |

## 3. 環境戦略

| 環境 | 構成 | コスト方針 |
|---|---|---|
| dev | RDS 単一AZ・Fargate Spot・最小タスク数 | 月約$50。夜間は worker 0タスク化可 |
| prod | RDS Multi-AZ・オンデマンド・api×2 | 可用性要件（業務時間内99%）に必要な最小限 |

## 4. 命名・タグ規約

- リソース名：`ri-<env>-<用途>`（例：`ri-dev-report-inbox`）
- 全リソース共通タグ：`Project=report-insight` / `Env=<env>` / `ManagedBy=terraform`
- コスト配分タグを有効化し、Cost Explorer で env 別・サービス別に集計可能にする（LLM APIコストはアプリ側計測と合算してダッシュボード化。LLM設計書 §5）

## 5. CI統合（[CI/CD・DevSecOps設計](09_cicd_devsecops.md)との接続）

| タイミング | 実行内容 |
|---|---|
| PR（terraform/ 変更時） | `fmt -check` → `validate` → `tflint` → Trivy config スキャン → `plan` を実行し、**plan 差分を PR コメントに自動投稿**（レビュアは差分を見て承認） |
| main マージ | dev へ自動 `apply` |
| prod | GitHub Environments の手動承認後に `apply`（承認ログ＝変更管理の監査証跡） |

- CI からの AWS 認証は OIDC（静的キーなし）。plan 用ロール（ReadOnly＋state 書込）と apply 用ロールを分離
- `-target` オプションの使用は障害対応時のみ・PR に理由を明記（部分適用の常用は state と実体の乖離を生む）

## 6. シークレットの扱い

- **tfvars・state に平文シークレットを書かない**。Terraform が作るのは Secrets Manager の「箱」まで。値の投入は初期構築時に管理者が CLI で行う（`aws secretsmanager put-secret-value`）
- RDS マスターパスワードは `manage_master_user_password`（Secrets Manager 自動管理）を使用し、Terraform に値を持たせない

## 7. インポートと例外

- 手動作成が避けられないリソース（初期の OIDC プロバイダ等）は作成後ただちに `terraform import` してコード管理下に入れる
- 例外的にコード外管理とするもの（Route 53 の親ゾーン等、クライアント既存資産）は README に一覧化して境界を明示する

## 8. ドリフト検知

- 週次で `terraform plan` をスケジュール実行（GitHub Actions cron）し、差分があれば Slack 通知
- ドリフト発見時の原則：**コードを実体に合わせるのではなく、実体をコードに戻す**（手動変更の正当性が認められた場合のみコード側を修正して取り込む）

## 9. 破壊操作のガードレール

- RDS・S3（取込バケット）に `prevent_destroy` を設定
- `terraform destroy` は dev のみ許可（ストレッチのデモ環境撤収用）。prod の destroy はロール権限で拒否
