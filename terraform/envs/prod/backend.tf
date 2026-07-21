# prod 別ステート（IaC戦略 §2）。dev とは key を分離し爆発半径を限定する。
# bucket は「部分設定」。アカウント ID を含むため公開リポジトリに実値を置かない（IaC戦略 §2.1）。
#   terraform init -backend-config=backend.hcl        （backend.hcl は .gitignore 対象）
terraform {
  backend "s3" {
    key            = "prod/terraform.tfstate"
    region         = "ap-northeast-1"
    dynamodb_table = "ri-tflock"
    encrypt        = true
  }
}
