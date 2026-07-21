# bootstrap — Terraform state の保管先を作るルート

`envs/dev` と `envs/prod` が使う **S3 state バケット**と **DynamoDB ロックテーブル**だけを
作る独立ルート。state 保管先そのものを main の Terraform で管理すると鶏と卵の循環に
なるため、ここだけ **backend を指定せず local state** で運用する。

| リソース | 名前 | 備考 |
|---|---|---|
| S3 バケット | `ri-tfstate-<account_id>` | バージョニング有効・SSE(AES256)・public access block 全 true |
| DynamoDB テーブル | `ri-tflock` | PAY_PER_REQUEST・hash_key `LockID` |

どちらも `prevent_destroy = true`（IaC戦略 §9）。

## 初回手順

```bash
cd terraform/bootstrap
cp terraform.tfvars.example terraform.tfvars   # account_id を自アカウントに合わせる
terraform init
terraform plan     # 期待: S3 系 + DynamoDB の add のみ
terraform apply
```

作成後、`envs/*/backend.tf` の `bucket` が出力値と一致していることを確認し、各 env で
`terraform init -reconfigure` を実行する。

## 運用上の注意

- **local state (`terraform.tfstate`) はコミットしない**（`.gitignore` 対象）。
  再作成が必要になった場合は既存リソースを `terraform import` して取り込む
- このルートは一度作ったら基本的に触らない。CI からは実行しない
- 撤収する場合は `prevent_destroy` を外してから `terraform destroy`。バージョニング済み
  オブジェクトが残っていると S3 の削除が失敗するので、先に s3api で空にする
