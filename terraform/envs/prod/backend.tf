# prod 別ステート（IaC戦略 §2）。dev とは key を分離し爆発半径を限定する。
terraform {
  backend "s3" {
    bucket         = "ri-tfstate"
    key            = "prod/terraform.tfstate"
    region         = "ap-northeast-1"
    dynamodb_table = "ri-tflock"
    encrypt        = true
  }
}
