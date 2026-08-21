terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
  }

  # backend は指定しない（local state）。state 保管先そのものを作るルートなので
  # S3 backend を指すと鶏と卵になる。IaC戦略 §2 を参照。
}
