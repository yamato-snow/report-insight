# env 別ステート（IaC戦略 §2）。S3 バージョニング＋SSE、DynamoDB ロック。
# bucket は「部分設定」にしてある。state バケット名は `ri-tfstate-<account_id>` で
# アカウント ID を含むため、公開リポジトリに実値を置かない（IaC戦略 §2.1）。
# 初期化時に渡す:
#   terraform init -backend-config=backend.hcl        （backend.hcl は .gitignore 対象）
#   terraform init -backend-config="bucket=ri-tfstate-<account_id>"
# ローカル検証は `terraform init -backend=false` で backend を無効化して validate する。
terraform {
  backend "s3" {
    key            = "dev/terraform.tfstate"
    region         = "ap-northeast-1"
    dynamodb_table = "ri-tflock"
    encrypt        = true
  }
}
