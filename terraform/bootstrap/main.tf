# Terraform state の保管先（S3）とロック（DynamoDB）を作る bootstrap ルート。
# main インフラ（envs/dev, envs/prod）とは state を分離した独立ルートで、
# ここだけ local state を使う。IaC戦略 §2「bootstrap の位置づけ」を参照。

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project   = "report-insight"
      ManagedBy = "terraform"
      Component = "tfstate-bootstrap"
    }
  }
}

locals {
  state_bucket_name = "ri-tfstate-${var.account_id}"
}

resource "aws_s3_bucket" "tfstate" {
  bucket = local.state_bucket_name

  # state 置き場の誤 destroy 防止（IaC戦略 §9）
  lifecycle {
    prevent_destroy = true
  }
}

# 誤破壊・巻き戻しからの復旧手段
resource "aws_s3_bucket_versioning" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_dynamodb_table" "tflock" {
  name         = var.lock_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }

  lifecycle {
    prevent_destroy = true
  }
}
