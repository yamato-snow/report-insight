# Terraform（IaC）— Report Insight

設計は [docs/11_iac_strategy.md](../docs/11_iac_strategy.md) と
[ADR-004](../docs/adr/ADR-004-iac-tool.md) が正。**コンソール手動変更は禁止**。

## 構成

```
terraform/
├── modules/
│   ├── network/        VPC・サブネット・NAT・SG・VPCエンドポイント(S3/Secrets)
│   ├── ecs/            クラスタ・api(ALB配下)/worker タスク・サービス・CPUオートスケール
│   ├── rds/            PostgreSQL(+pgvector拡張)・パラメータ群・自動バックアップ・破壊ガード
│   ├── pipeline/       S3取込バケット・SQS・DLQ(redrive)・S3→SQSイベント通知
│   └── observability/  SNS・アラーム(DLQ/バックログ/ECS・RDS CPU)・ダッシュボード
└── envs/
    ├── dev/   単一AZ・FARGATE_SPOT・最小タスク（backend key = dev/）
    └── prod/  Multi-AZ・FARGATE・api×2（backend key = prod/）
```

- **環境差分は `terraform.tfvars` と `backend.tf` のみ**。`main.tf` は dev/prod で同一
  （dev で検証した構成がそのまま prod になる保証を壊さないため。IaC戦略 §1）。
- シークレットは「箱」だけ作り、値は管理者が CLI で投入（IaC戦略 §6）。RDS マスター
  パスワードは `manage_master_user_password`（Secrets Manager 自動管理）。

## 検証状況

- `terraform fmt -recursive -check`: **PASS**
- `terraform validate`（dev / prod）: **PASS**（`terraform init -backend=false` 後）
- `terraform plan`: AWS 認証（CI の OIDC ロール）と S3 backend が必要なため CI で実行する
  （IaC戦略 §5）。ローカルの資格情報なし環境では未実行。

## 実行手順

```bash
# ローカルで構文検証（AWS 認証不要）
cd envs/dev && terraform init -backend=false && terraform validate

# 実運用（CI もしくは管理者。要 AWS 認証 + state バケット/ロックテーブル）
terraform init            # backend.tf の S3/DynamoDB を使用
terraform plan  -var="image=<ECR_URI>:<tag>"
terraform apply -var="image=<ECR_URI>:<tag>"   # apply は P2（任意）
```

state 用の S3 バケット（`ri-tfstate`・バージョニング/SSE 有効）と DynamoDB ロックテーブル
（`ri-tflock`）は事前に用意する（ブートストラップ）。`apply` は P2 スコープ。
