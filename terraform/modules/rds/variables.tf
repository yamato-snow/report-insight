variable "name_prefix" {
  type = string
}

variable "subnet_ids" {
  description = "DB を配置するプライベートサブネット"
  type        = list(string)
}

variable "security_group_id" {
  description = "RDS 用セキュリティグループ"
  type        = string
}

variable "engine_version" {
  type    = string
  default = "16.4"
}

variable "parameter_group_family" {
  type    = string
  default = "postgres16"
}

variable "instance_class" {
  type    = string
  default = "db.t4g.micro"
}

variable "allocated_storage" {
  type    = number
  default = 20
}

variable "multi_az" {
  description = "prod は true、dev は false（IaC戦略 §3）"
  type        = bool
  default     = false
}

variable "backup_retention_period" {
  type    = number
  default = 7
}

variable "deletion_protection" {
  type    = bool
  default = true
}

variable "skip_final_snapshot" {
  description = "dev の撤収を容易にするため dev のみ true"
  type        = bool
  default     = false
}

variable "db_name" {
  type    = string
  default = "report_insight"
}

variable "master_username" {
  type    = string
  default = "app"
}

variable "tags" {
  type    = map(string)
  default = {}
}
