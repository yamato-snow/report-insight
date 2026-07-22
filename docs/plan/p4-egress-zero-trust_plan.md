---
date: 2026-07-19
model: fable
status: draft
issue: ""
topic: p4 ECS egress の 0.0.0.0/0 完全排除（Bedrock 切替＋通知 SNS 化＋モデル焼き込み）
predecessor: p3-vpc-endpoints-prod_plan.md
---

# p4: ECS egress 0.0.0.0/0 完全排除計画（AVD-AWS-0104 解除）

## 背景

- Fable 昇格理由: /0 排除は LLM 呼び出し経路・通知経路・イメージビルドをまたぐ
  アーキテクチャ判断（F2: 設計ドリフト防止）。方式比較と段階順序を先に固定する。
- 現状の残余 /0 は `ecs_https`（tcp/443, 0.0.0.0/0）1本。これに依存する公開宛先は
  調査の結果 **3系統** ある（.trivyignore の理由文は Anthropic のみ記載で不正確）:
  1. `api.anthropic.com` — LLM 呼び出し（api/worker 両方）
  2. `hooks.slack.com` — 緊急通知 webhook（`app/infra/notify/slack.py`）
  3. `huggingface.co` / CDN — fastembed の `multilingual-e5-large` を**実行時に**
     ダウンロード（Dockerfile に焼き込みステップがなく、`app/infra/embedding/download.py`
     はどこからも呼ばれていない）
- 3系統すべてを AWS 内経路（PrivateLink）または排除に置き換えたときのみ /0 ルールを
  削除でき、AVD-AWS-0104 を .trivyignore から解除できる。1つでも残せば /0 は残る。
- 前提: [p3-vpc-endpoints-prod_plan.md](p3-vpc-endpoints-prod_plan.md) 完了
  （vpce SG・Interface エンドポイント基盤）。**実施順は p3 → p4**。

## 方式比較（3案）

| 観点 | 案1: Bedrock 切替＋SNS 通知＋モデル焼き込み | 案2: Egress proxy（固定経由点） | 案3: AWS Network Firewall ドメイン allowlist |
|---|---|---|---|
| AVD-AWS-0104 を実際に解除できるか | **◎ 可**。/0 ルール自体を削除できる（全 egress が SG 参照 or prefix list になる） | **× 不可**。/0 が proxy の SG に移動するだけで Trivy は proxy SG で発火（同一リポジトリ内なので抑制が必要なまま） | **× 不可**。SG レイヤはドメインを表現できず ecs_https の /0 は残る（補償統制であり検出は消えない） |
| 実質のセキュリティ効果 | ◎ 全宛先が閉域（PrivateLink）。公開インターネット egress ゼロ | ○ proxy でドメイン allowlist 強制可（実効性はある） | ◎ FQDN allowlist をマネージドで強制 |
| アプリ改修 | 中: LLM クライアント差し替え（`LLM_PROVIDER` 分岐は既存）＋通知の SNS 化＋Dockerfile 1行 | 小: `HTTPS_PROXY` 環境変数（httpx/SDK は対応済み） | 不要 |
| dev/prod コスト（月額・概算） | prod +約$41（bedrock-runtime/sns エンドポイント 2AZ）。dev +約$20（1AZ×2種…dev にも必須、後述）。**NAT 廃止（任意 Phase）で prod −$91/dev −$45 相殺可** | EC2 proxy 冗長化 t4g.small×2 ≈ $25＋EIP＋保守。dev にも必要 | firewall endpoint $0.395/h ≈ **$288/月/AZ**＋$0.065/GB。2AZ で $577/月 |
| 運用負荷 | 低（フルマネージド。モデル可用性の追随のみ） | **高**（proxy のパッチ・HA・証明書・allowlist 保守） | 低〜中（ルール保守。コストが支配的） |
| 可逆性 | 高（`LLM_PROVIDER=anthropic` に戻し /0 ルール復元。API キーの Secret は当面残す） | 高 | 高 |
| モデル等価性 | 要検証: `claude-sonnet-5` / `claude-haiku-4-5` の Bedrock ap-northeast-1（または APAC 推論プロファイル）提供状況。未提供なら `claude-sonnet-4-6` 等へ暫定ダウングレードの判断が必要（Phase 0 ゲート） | 等価（API 直のまま） | 等価 |

**推奨: 案1**。目的（AVD-AWS-0104 の完全解除）を達成できるのは案1のみ。案2 は検出が
移動するだけで目的未達のうえ運用負荷が最も高い。案3 は実効性は高いがポートフォリオ規模に
対しコストが2桁過大で、かつ検出も解除できない（本番大規模環境で「/0 は残すが FQDN 制御を
併設する」補償統制としてなら妥当、という位置づけを比較表の結論として記録する）。
案1 は Slack webhook・HF ダウンロードという「Anthropic 以外の /0 依存」も同時に潰せる
唯一の案であり、Bedrock 統合はポートフォリオ（応募先案件）の加点要素でもある。

## 対象範囲

- `Dockerfile`（モデル焼き込み1ステップ）
- `app/core/config.py` / `app/core/di.py` / `app/infra/llm/`（Bedrock クライアント分岐）
- `app/infra/notify/`（SNS 通知の追加・Slack webhook 置換）
- `terraform/modules/network/main.tf`（bedrock-runtime / sns エンドポイント追加、
  `ecs_https` 削除、置換 egress 2本追加）
- `terraform/modules/ecs/main.tf`（task role に bedrock/sns 権限）
- `terraform/envs/{dev,prod}/`（tfvars・環境変数配線）
- `terraform/.trivyignore`（AVD-AWS-0104 エントリ削除）

## 段階設計（各 Phase 独立で着地可能な順序）

### Phase 0: 事前検証ゲート（実装前に必ず）

- Bedrock で `anthropic.claude-sonnet-5` / `anthropic.claude-haiku-4-5`（または
  `apac.` 推論プロファイル）が ap-northeast-1 から呼べるか確認:
  `aws bedrock list-foundation-models --region ap-northeast-1` ＋ model access 有効化
  （model access 有効化はコンソール操作＝CEO 作業。ここが未達なら本計画全体を保留し、
  代替モデル採用の判断を Fable に差し戻す）
- Bedrock の従量単価を Anthropic API と比較しトークン単価の乖離を PR に記録する

### Phase 1: fastembed モデルのイメージ焼き込み（単独でも価値あり・先行可）

- Dockerfile の `RUN uv sync --no-dev` の後に追加:
  ```dockerfile
  # 埋め込みモデルをビルド時に焼き込み（実行時の HuggingFace 依存を排除）
  RUN python -m app.infra.embedding.download
  ```
- fastembed のキャッシュディレクトリがイメージ内に永続する（root 実行前提のため
  `$HOME/.cache` 配下）ことを `docker run` で確認。イメージサイズ増（+1〜2GB）は許容し、
  ECR ストレージ課金（$0.10/GB-月）を PR に記録
- 効果: HF 障害・レート制限と worker 起動の分離／コールドスタート短縮／NAT データ課金減。
  `download.py` の module パス（`app.infra.embedding.download` に `main()` 呼び出しがあるか）
  は実装時に確認し、エントリポイントが無ければ追加する

### Phase 2: LLM を Bedrock へ切替

- `LLM_PROVIDER=bedrock` の分岐を di.py に追加。クライアントは anthropic SDK の
  **`AnthropicBedrockMantle(aws_region=...)`**（Messages API 互換の Bedrock クライアント。
  認証は task role の SigV4 で API キー不要）。モデル ID は `anthropic.` プレフィックスを
  設定でマッピング（例: `anthropic.claude-haiku-4-5`。Phase 0 の確認結果に従う）
- SSE ストリーミング（検索応答）が Bedrock 経由でも動くことを integration テストで確認
- task role に `bedrock:InvokeModel` / `bedrock:InvokeModelWithResponseStream` を付与
  （Resource は対象 foundation-model / inference-profile ARN に限定）
- network モジュールの interface_services に `bedrock = "bedrock-runtime"` を追加
- `ANTHROPIC_API_KEY` の Secret と container secret 配線はロールバック用に**当面残す**
  （削除は /0 撤去後の後続クリーンアップ）

### Phase 3: Slack webhook → SNS ＋ AWS Chatbot

- `app/infra/notify/sns.py`（boto3 `sns:Publish`）を追加し、`NOTIFY_CHANNEL` 設定で
  Slack webhook と切替可能にする（di.py 分岐。既存 SlackNotifier は削除しない）
- Terraform: SNS トピック追加（pipeline モジュール内が自然）、task role に `sns:Publish`、
  interface_services に `sns = "sns"` を追加
- AWS Chatbot（Slack ワークスペース連携）の初回認可は**コンソール手作業＝CEO 作業**。
  Chatbot 設定自体（`aws_chatbot_slack_channel_configuration`）は Terraform 化する
- dev の webhook-mock を使う integration テストは既存経路（SlackNotifier）で維持

### Phase 4: /0 削除と Trivy 解除（Phase 1〜3 完了が前提）

- `ecs_https`（0.0.0.0/0:443）を削除し、置換 egress を追加:
  ```hcl
  resource "aws_vpc_security_group_egress_rule" "ecs_to_vpce" {
    security_group_id            = aws_security_group.ecs.id
    referenced_security_group_id = aws_security_group.vpce.id
    ip_protocol                  = "tcp"
    from_port                    = 443
    to_port                      = 443
  }
  resource "aws_vpc_security_group_egress_rule" "ecs_to_s3_gateway" {
    security_group_id = aws_security_group.ecs.id
    prefix_list_id    = aws_vpc_endpoint.s3.prefix_list_id
    ip_protocol       = "tcp"
    from_port         = 443
    to_port           = 443
  }
  ```
- **dev も Interface エンドポイント必須になる**（SG ルールは module 共有のため /0 削除は
  両 env に効く）: `envs/dev/terraform.tfvars` を `enable_interface_endpoints = true` に変更。
  dev のコスト増（1AZ×7種 ≈ $72/月）と NAT 廃止による相殺（−$45/月）を PR に記録
- `.trivyignore` から AVD-AWS-0104 エントリを削除し、`trivy config` で発火しないことを確認
- あわせて network モジュール内の egress コメント（Anthropic 経由の記述）を現状に合わせ更新

### Phase 5（任意・別判断）: NAT Gateway 廃止

- Phase 4 完了後、private subnet から 0.0.0.0/0 経路を使う通信は消滅する。
  NAT・EIP を削除すれば prod −$90.5/月、dev −$45.3/月
- ただし「新しい外部依存を足す際に NAT を再建する」摩擦が生まれるため、**別 issue として
  CEO 判断に委ねる**（本計画の完了条件に含めない）

## 検証手順（apply はしない）

1. `make lint` / unit / integration green（Phase 1〜3 の各着地点で）
2. `docker compose up → make demo` で取込〜検索〜通知の e2e が通る
   （LLM_PROVIDER=bedrock は AWS 認証情報が要るため、ローカルは anthropic のまま
   フラグ既定値で回帰確認。bedrock 経路は plan 差分と unit（クライアント生成分岐）で担保）
3. dev/prod 両方で local backend override により `terraform validate` / `terraform plan`。
   期待差分（エンドポイント追加・egress 差し替え・IAM）を PR に貼る
4. `trivy config terraform/` — AVD-AWS-0104 が**検出されず**、.trivyignore 残余が
   AVD-AWS-0107 / AVD-AWS-0054 の2件のみであること

## 完了条件

- [ ] Phase 0: Bedrock の対象モデル提供・model access が確認され、採用モデル ID が
      tfvars に固定されている（未提供の場合は中断して Fable に差し戻した記録がある）
- [ ] Phase 1: イメージビルドで埋め込みモデルが焼き込まれ、ネットワーク遮断状態の
      コンテナで埋め込み生成が成功する
- [ ] Phase 2: `LLM_PROVIDER=bedrock` 分岐・IAM・bedrock-runtime エンドポイントが実装され、
      integration（ストリーミング含む）が green
- [ ] Phase 3: SNS 通知経路・Chatbot 設定の Terraform・IAM・sns エンドポイントが実装され、
      通知の unit/integration が green
- [ ] Phase 4: `ecs_https` が削除され、`ecs_to_vpce`・`ecs_to_s3_gateway` に置換。
      dev tfvars が enable_interface_endpoints=true。`.trivyignore` から AVD-AWS-0104 が
      消え、`trivy config` で新規検出ゼロ
- [ ] dev/prod の `terraform validate` green・`terraform plan` の期待差分を PR 説明に記載
- [ ] apply は一切していない

## 対象外（今回やらないこと）

- **apply（絶対にしない）**
- NAT Gateway の廃止（Phase 5 は別 issue・CEO 判断）
- `ANTHROPIC_API_KEY` Secret の削除（ロールバック手段として残す）
- ALB の /0 ingress（AVD-AWS-0107）・HTTP リスナ（AVD-AWS-0054）の解消（既存の別トラック）
- Network Firewall・egress proxy の導入（比較の結果不採用。理由は本計画の比較表）
- secretsmanager エンドポイントの for_each 統合（p3 と同じく対象外）

## ロールバック方法

- Phase 単位で独立に revert 可能:
  - Phase 4: `ecs_https` と .trivyignore エントリを復元（コード revert のみ。未 apply なら
    それで完結、apply 済みなら plan/apply で SG ルールが復元される）
  - Phase 2/3: `LLM_PROVIDER=anthropic`・`NOTIFY_CHANNEL=slack` へ tfvars/env を戻す
    （旧経路のコード・Secret は残置してあるため設定変更のみで戻る）
  - Phase 1: Dockerfile の RUN 行を revert（実行時 DL に戻る）
- 順序制約: Phase 4 のロールバックを**最初に**行うこと（/0 が無い状態で Phase 2/3 を
  戻すと外部到達が失われ通知・LLM が停止する）
