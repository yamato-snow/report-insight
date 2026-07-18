# env 別ステート（IaC戦略 §2）。S3 バージョニング＋SSE、DynamoDB ロック。
# init 時に -backend-config で bucket 等を上書きしてもよい。ローカル検証は
# `terraform init -backend=false` で backend を無効化して validate する。
terraform {
  backend "s3" {
    bucket         = "ri-tfstate"
    key            = "dev/terraform.tfstate"
    region         = "ap-northeast-1"
    dynamodb_table = "ri-tflock"
    encrypt        = true
  }
}
