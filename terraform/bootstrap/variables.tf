variable "aws_region" {
  description = "bootstrap リソースを置くリージョン（state バケット／ロックテーブル）"
  type        = string
  default     = "ap-northeast-1"
}

variable "account_id" {
  description = "state バケット名の一意化に使う AWS アカウント ID（terraform.tfvars で固定）"
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.account_id))
    error_message = "account_id は 12 桁の数字で指定してください。"
  }
}

variable "lock_table_name" {
  description = "Terraform state ロック用 DynamoDB テーブル名（envs/*/backend.tf と一致させる）"
  type        = string
  default     = "ri-tflock"
}
