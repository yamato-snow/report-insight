---
date: 2026-07-19
model: fable
status: done
issue: ""
topic: p3 prod 向け VPC Interface エンドポイント導入＋endpoints SG 分離
predecessor: p2-observability-metrics-cost-alarm_handoff.md
---

# p3: prod 向け VPC Interface エンドポイント導入計画

## 背景

- Fable 昇格理由: ネットワーク境界の設計判断（F2: 設計ドリフト防止）。SG 構造・エンドポイント構成・コスト判断を先に固定する。
- 現状: Interface エンドポイントは Secrets Manager のみ（SG は ECS SG を共有し、自己参照
  ingress 443 で到達させている）。ECR pull / CloudWatch Logs / SQS は NAT 経由。
- 目的: prod は ECR(api,dkr)・Logs・SQS を Interface エンドポイント化して NAT 依存と
  AZ 間障害面を縮小する。dev は NAT 経由のまま（コスト優先）。S3 は既存 Gateway を流用。
- 併せて Fable レビュー指摘の是正を行う: **エンドポイント用 SG を ECS SG から分離**する。
  現行の自己参照 ingress 443 は「ECS タスク同士の 443 横通信」まで許可してしまい、
  エンドポイント追加のたびに ECS SG の意味が肥大化するため。
- 注意: 本計画は **AVD-AWS-0104（ecs_https の 0.0.0.0/0:443）の解除には寄与しない**。
  Anthropic API / Slack webhook / HuggingFace への公開 egress が残るため。/0 の完全排除は
  [p4-egress-zero-trust_plan.md](p4-egress-zero-trust_plan.md) の役割（p4 は本計画の
  endpoints SG・エンドポイント基盤を前提にする。**実施順は p3 → p4**）。

## 対象範囲

- `terraform/modules/network/main.tf` / `variables.tf` / `outputs.tf`
- `terraform/envs/dev/{main.tf,variables.tf,terraform.tfvars}`
- `terraform/envs/prod/{main.tf,variables.tf,terraform.tfvars}`
- （コメント修正のみ）`terraform/envs/prod/main.tf` 1行目のヘッダコメントが「dev 環境:」の
  まま。「prod 環境:」に直す（構成同一ポリシーの本文には影響なし）

## 設計

### 1. endpoints 専用 SG（常時作成・env 非依存）

```hcl
resource "aws_security_group" "vpce" {
  name        = "${var.name_prefix}-vpce-sg"
  description = "Interface VPC endpoints (ingress 443 from ECS tasks only)"
  vpc_id      = aws_vpc.this.id
  tags        = merge(var.tags, { Name = "${var.name_prefix}-vpce-sg" })
}

resource "aws_vpc_security_group_ingress_rule" "vpce_https_from_ecs" {
  security_group_id            = aws_security_group.vpce.id
  referenced_security_group_id = aws_security_group.ecs.id
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
}
```

- egress ルールは不要（SG はステートフル。エンドポイント ENI から通信を開始しない）。
- 既存 `aws_vpc_endpoint.secretsmanager` の `security_group_ids` を
  `[aws_security_group.vpce.id]` に変更（ModifyVpcEndpoint の in-place 更新。再作成なし）。
- 同一 apply で `aws_vpc_security_group_ingress_rule.ecs_endpoints_https`（自己参照 443）を
  **削除**。到達性は vpce SG の ingress ルールで置換される。
- `outputs.tf` に `vpce_sg_id` を追加（p4 が ECS egress の参照先として使う）。

### 2. Interface エンドポイントの for_each 制御（tfvars 分岐）

```hcl
# variables.tf
variable "enable_interface_endpoints" {
  description = "ECR/Logs/SQS の Interface エンドポイントを作成するか（prod=true, dev=false）"
  type        = bool
  default     = false
}

# main.tf
locals {
  interface_services = var.enable_interface_endpoints ? {
    ecr_api = "ecr.api"
    ecr_dkr = "ecr.dkr"
    logs    = "logs"
    sqs     = "sqs"
  } : {}
}

resource "aws_vpc_endpoint" "interface" {
  for_each            = local.interface_services
  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${data.aws_region.current.name}.${each.value}"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.vpce.id]
  private_dns_enabled = true
  tags                = merge(var.tags, { Name = "${var.name_prefix}-${each.key}-endpoint" })
}
```

- `secretsmanager` は既存リソースのまま独立させて置く（for_each に取り込むと state 移行
  （moved ブロック）が必要になる。取り込みは任意の後続リファクタとし、本計画ではやらない）。
- private_dns_enabled=true により、アプリ・ECS agent・awslogs ドライバは**設定変更なし**で
  エンドポイント経由に切り替わる（SDK のエンドポイント URL 変更不要）。
- ECR pull はレイヤ本体を S3 から取得するため既存 S3 Gateway エンドポイントが必須前提
  （既にある。route_table_ids が private RT 全数を向いていることを維持）。

### 3. env 側配線（構成同一ポリシー維持）

- `envs/{dev,prod}/variables.tf` に `enable_interface_endpoints`（default false）を追加。
- `envs/{dev,prod}/main.tf` の `module "network"` に
  `enable_interface_endpoints = var.enable_interface_endpoints` を1行追加（両 env 同一）。
- `envs/prod/terraform.tfvars` に `enable_interface_endpoints = true` を追加。
  `envs/dev/terraform.tfvars` には `enable_interface_endpoints = false` を明示（差分の可視化）。

## コスト概算（ap-northeast-1・2026-07 時点の公表単価）

| 項目 | 単価 | prod（2AZ） | dev |
|---|---|---|---|
| Interface エンドポイント時間課金 | $0.014/AZ-h | 4種×2AZ×730h ≈ **$81.8/月** | $0（作らない） |
| エンドポイントデータ処理 | $0.01/GB | 通過 GB × $0.01 | — |
| （参考）NAT GW 時間課金 | $0.062/h | 2台 ≈ $90.5/月（継続） | 1台 ≈ $45.3/月 |
| （参考）NAT データ処理 | $0.062/GB | エンドポイント移行分は不課金化 | — |

- 判断: 低トラフィック前提では**固定費 +約$82/月の純増**（NAT は Anthropic 向けが残るため
  廃止できない）。データ単価は NAT $0.062/GB → エンドポイント $0.01/GB に下がるため、
  イメージ pull・ログ・SQS ポーリングのデータ量が増えるほど差は縮む。
- それでも prod で採る価値: (1) ECR/Logs/SQS が NAT・IGW 障害と分離され AZ 内で完結する
  （multi_az 構成の趣旨と整合）、(2) AWS 宛トラフィックが閉域化する、(3) p4 の /0 排除の
  前提基盤になる、(4) ポートフォリオとして PrivateLink 設計を示せる。フラグ制御なので
  不要になれば tfvars 1行で撤収できる。

## 検証手順（apply はしない）

1. `cd terraform/envs/dev` — `backend_override.tf`（local backend）を一時配置して
   `terraform init -reconfigure && terraform validate && terraform plan`
   - 期待差分: vpce SG 追加 / SM エンドポイントの SG 差し替え（in-place）/
     `ecs_endpoints_https` 削除のみ。Interface エンドポイント4種は**出ない**こと
2. `cd terraform/envs/prod` — 同様に validate / plan
   - 期待差分: dev の差分に加えて Interface エンドポイント4種の追加
3. `trivy config terraform/` — 既存 .trivyignore の3件以外の新規検出が**ない**こと
4. 検証後 `backend_override.tf` を削除（コミットしない）

## 完了条件

- [ ] `modules/network` に vpce SG・vpce_https_from_ecs ingress・`enable_interface_endpoints`
      変数・Interface エンドポイント for_each・`vpce_sg_id` output が追加されている
- [ ] `aws_vpc_endpoint.secretsmanager` の SG が vpce SG に差し替わり、
      `ecs_endpoints_https`（自己参照 443）が削除されている
- [ ] envs/dev・envs/prod の main.tf/variables.tf/tfvars が上記どおり配線され、
      main.tf の構成が dev/prod で同一のまま（差分は tfvars のみ）
- [ ] envs/prod/main.tf のヘッダコメントが「prod 環境:」に修正されている
- [ ] dev/prod 両方で `terraform validate` green・`terraform plan` が期待差分どおり
      （plan 出力の要約を PR 説明に貼る）
- [ ] `trivy config` で新規検出ゼロ（.trivyignore の変更なし）

## 対象外（今回やらないこと）

- **apply（絶対にしない。plan 差分の提示まで）**
- ecs_https（0.0.0.0/0:443）の削除・.trivyignore AVD-AWS-0104 の解除（→ p4）
- Bedrock 切替・Slack 通知の SNS 化・Dockerfile 変更（→ p4）
- secretsmanager エンドポイントの for_each への統合（moved を伴う state リファクタ）
- NAT Gateway の削減・経路変更
- dev への Interface エンドポイント導入

## ロールバック方法

- 未 apply のためコード revert のみで完結（`git revert` 1コミット）。
- 万一 apply 後に問題が出た場合: `enable_interface_endpoints = false` で4種を撤収
  （SM への到達は vpce SG 経由で維持される）。SM エンドポイントの SG を旧構成に戻すには
  `security_group_ids = [ecs_sg]` へ再変更＋ `ecs_endpoints_https` 復元（いずれも in-place）。

## 実装時差分（2026-07-19・Opus）

- **plan diff の検証方法**: リモート state（S3 backend）へは接続せず、各 env に一時
  `backend_override.tf`（local backend）を置き `terraform plan -refresh=false` を実行。
  state 空のため出力は全リソース「to add」（in-place 差し替え／削除の形では出ない）。
  offline で確認できる本質シグナルで代替判定した:
  - dev: `Plan: 70 to add`。`aws_vpc_endpoint.interface` は **0件**、`ecs_endpoints_https` **0件**、
    `aws_security_group.vpce`＋`vpce_https_from_ecs` 生成 ✓
  - prod: `Plan: 76 to add`（dev比 +4=Interface4種／+2=prod2台目NAT・EIP）。
    `aws_vpc_endpoint.interface["ecr_api"|"ecr_dkr"|"logs"|"sqs"]` の **4件** 生成、
    vpce SG 系一式生成、`ecs_endpoints_https` **0件** ✓
  - 検証後 `backend_override.tf` は両 env とも削除済（未コミット）。
- **trivy 未実行**: 本環境に trivy/tfsec/checkov 未インストールのため `trivy config` は走らせられず。
  `.trivyignore` は無変更。新規リソースはいずれも /0 ルールを追加しない（vpce SG は egress 無し・
  ingress は ECS SG 参照のみ、Interface エンドポイントは公開性なし、SM は SG 参照先の差し替えのみ）
  ため AVD-AWS-0104/0107 の新規検出は理論上生じない見込み。**要 CI(iac-scan) 上での確認**。
- `terraform validate` は dev/prod とも green、`terraform fmt -recursive -check` clean。
