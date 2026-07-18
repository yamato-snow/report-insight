variable "region" {
  type    = string
  default = "ap-northeast-1"
}

variable "env" {
  type    = string
  default = "dev"
}

variable "vpc_cidr" {
  type    = string
  default = "10.20.0.0/16"
}

variable "azs" {
  type    = list(string)
  default = ["ap-northeast-1a", "ap-northeast-1c"]
}

variable "public_subnet_cidrs" {
  type    = list(string)
  default = ["10.20.0.0/24", "10.20.1.0/24"]
}

variable "private_subnet_cidrs" {
  type    = list(string)
  default = ["10.20.10.0/24", "10.20.11.0/24"]
}

variable "single_nat_gateway" {
  type    = bool
  default = true
}

variable "container_port" {
  type    = number
  default = 8000
}

variable "image" {
  description = "api/worker 共通のコンテナイメージ（ECR URI:tag）"
  type        = string
  default     = "PLACEHOLDER.dkr.ecr.ap-northeast-1.amazonaws.com/report-insight:latest"
}

variable "capacity_provider" {
  type    = string
  default = "FARGATE_SPOT"
}

variable "multi_az" {
  type    = bool
  default = false
}

variable "db_instance_class" {
  type    = string
  default = "db.t4g.micro"
}

variable "worker_desired_count" {
  type    = number
  default = 1
}

variable "api_desired_count" {
  type    = number
  default = 1
}

variable "deletion_protection" {
  type    = bool
  default = false
}

variable "skip_final_snapshot" {
  type    = bool
  default = true
}

variable "llm_provider" {
  type    = string
  default = "anthropic"
}

variable "model_classify" {
  type    = string
  default = "claude-haiku-4-5-20251001"
}

variable "model_generate" {
  type    = string
  default = "claude-sonnet-5"
}

variable "alarm_email" {
  type    = string
  default = ""
}
