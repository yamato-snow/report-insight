---
date: 2026-07-20
model: fable
status: approved
issue: ""
topic: tfstate backend 修復（自アカウントの S3+DynamoDB を bootstrap Terraform で作成）
predecessor: p2-observability-metrics-cost-alarm_handoff.md
---

# tfstate backend 修復: bootstrap Terraform で自前の state 保管を用意する

## 背景

- Fable 昇格理由: state 保管はインフラ全体の土台であり、方式（CLI 直叩き vs bootstrap
  Terraform）の選定を先に固定する必要がある（F2: 設計ドリフト防止）。
- 現状の `terraform/envs/{dev,prod}/backend.tf` は `bucket = "ri-tfstate"` を参照するが、
  このバケットは**自アカウント非所有**（eu-central-1 の第三者バケット。init 時 HTTP 301）。
  このままでは実 apply・OIDC deploy（P2 第2歩）へ一切進めない。
- 方式決定（CEO 合意 2026-07-20）: **bootstrap Terraform 方式**を採る。
  - state バケット自身を main の Terraform で管理すると鶏と卵の循環になるため、
    `terraform/bootstrap/` を**別 state（local）の独立ルート**として切り出すのが定石
  - CLI 直叩きでも作れるが、IaC 管理方針（ポートフォリオの一貫性）に合わせ bootstrap を採用

## 設計（固定事項）

1. **ディレクトリ**: `terraform/bootstrap/`（main.tf / variables.tf / outputs.tf /
   versions.tf / README.md）。backend は**指定しない**（local state。
   `terraform.tfstate*` は .gitignore 対象で**コミットしない**）
2. **リソース**（region: ap-northeast-1）:
   - `aws_s3_bucket` — 名前は全世界一意にするため `ri-tfstate-<account_id>`
     （`ri-tfstate-<account_id>`。account_id は variable で受け、tfvars に固定。
     **公開リポジトリに実値は書かない**）
   - バージョニング有効（誤破壊からの復旧手段）
   - SSE（AES256）有効・`aws_s3_bucket_public_access_block` 全4項目 true
   - `aws_dynamodb_table` — `ri-tflock`（PAY_PER_REQUEST・hash_key `LockID`）。
     テーブル名はアカウント内一意でよいので既存 backend.tf の名前を踏襲
   - lifecycle `prevent_destroy = true`（state 置き場の誤 destroy 防止）
3. **backend.tf の更新**: `envs/dev` と `envs/prod` の `bucket` を
   `ri-tfstate-<account_id>` へ変更（key・region・dynamodb_table は現行のまま）
4. **apply の扱い**: これまでの「apply 厳禁」は main インフラのルール。
   **bootstrap の apply（バケット＋テーブル作成のみ）は本計画の範囲内で実施してよい**
   （CEO 承認 2026-07-20。費用: S3 保管数円/月＋DynamoDB オンデマンドほぼ 0）。
   main 側（envs/dev, envs/prod）の apply は引き続き**厳禁**

## 対象範囲

- `terraform/bootstrap/`（新規）
- `terraform/envs/dev/backend.tf` / `terraform/envs/prod/backend.tf`（bucket 名のみ変更）
- `.gitignore`（bootstrap の local state 除外が既存パターンで拾えているか確認）
- `docs/11_iac_strategy.md`（bootstrap の位置づけ・初回手順を1節追記）

## 検証手順

1. `terraform -chdir=terraform/bootstrap init && terraform -chdir=terraform/bootstrap plan`
   — 期待差分: S3 バケット系＋DynamoDB の add のみ
2. `terraform -chdir=terraform/bootstrap apply`（**この apply のみ許可**）
3. `aws s3api head-bucket --bucket ri-tfstate-<account_id>` ＋
   `aws dynamodb describe-table --table-name ri-tflock` で実在確認
4. `terraform -chdir=terraform/envs/dev init -reconfigure` が**素通しで成功**すること
   （301 エラーの解消確認）。続けて `terraform validate`。
   `terraform plan` はリモート state（空）に対する全 add となることを確認するだけでよい
   （**apply はしない**）。prod も同様
5. `trivy` 相当（CI iac-scan）で新規検出が出ないこと（PR の CI で確認）

## 完了条件

- [ ] `terraform/bootstrap/` が上記設計どおり存在し、plan/apply が clean に通っている
- [ ] `ri-tfstate-<account_id>`（versioning/SSE/public block）と `ri-tflock` が実在する
- [ ] dev/prod の backend.tf が新バケットを指し、`init -reconfigure` が 301 なしで成功する
- [ ] bootstrap の local state がコミットされていない（git status clean）
- [ ] `docs/11_iac_strategy.md` に bootstrap 節が追記されている
- [ ] PR 作成（terraform/ + docs/ のみ。llm-regression 非発火）
- [ ] main インフラ（envs/dev, envs/prod）の apply は**していない**

## 対象外（今回やらないこと）

- envs/dev・envs/prod の apply（OIDC deploy＝P2 第2歩の plan で別途判断）
- CI からの terraform 実行（OIDC ロール整備とセットで P2 第2歩へ）
- 旧バケット名 `ri-tfstate` に関する後始末（他者所有のため作業対象が存在しない）
- state のリージョン冗長化・レプリケーション

## ロールバック方法

- backend.tf の変更は revert のみで戻る（まだどの env も実 state を持っていないため
  state 移行（migrate）は発生しない）
- 作成したバケット/テーブルが不要になった場合: `prevent_destroy` を外して
  `terraform -chdir=terraform/bootstrap destroy`（バージョニングされたオブジェクトの
  空化が必要な場合は s3api で削除してから）。費用影響は数円/月なので放置でも実害なし
