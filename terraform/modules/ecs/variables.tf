variable "name_prefix" {
  type = string
}

variable "region" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "public_subnet_ids" {
  type = list(string)
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "alb_sg_id" {
  type = string
}

variable "ecs_sg_id" {
  type = string
}

variable "container_port" {
  type    = number
  default = 8000
}

variable "image" {
  description = "api/worker 共通のコンテナイメージ（ECR）。command で役割を分ける"
  type        = string
}

variable "api_cpu" {
  type    = number
  default = 512
}

variable "api_memory" {
  type    = number
  default = 1024
}

variable "api_desired_count" {
  type    = number
  default = 1
}

variable "api_min_count" {
  type    = number
  default = 1
}

variable "api_max_count" {
  type    = number
  default = 4
}

variable "worker_cpu" {
  type    = number
  default = 512
}

variable "worker_memory" {
  type    = number
  default = 1024
}

variable "worker_desired_count" {
  type    = number
  default = 1
}

variable "capacity_provider" {
  description = "FARGATE（prod）または FARGATE_SPOT（dev）"
  type        = string
  default     = "FARGATE_SPOT"
}

variable "environment" {
  description = "コンテナのプレーン環境変数"
  type        = map(string)
  default     = {}
}

variable "secret_arns" {
  description = "コンテナ secrets（環境変数名 → Secrets Manager ARN）"
  type        = map(string)
  default     = {}
}

variable "s3_bucket_arn" {
  type = string
}

variable "queue_arn" {
  type = string
}

variable "app_secret_arns" {
  description = "タスクロール/実行ロールが取得を許可されるシークレット ARN 群"
  type        = list(string)
  default     = []
}

variable "log_retention_days" {
  type    = number
  default = 30
}

variable "tags" {
  type    = map(string)
  default = {}
}
