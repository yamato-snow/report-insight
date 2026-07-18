variable "name_prefix" {
  type = string
}

variable "region" {
  type = string
}

variable "cluster_name" {
  type = string
}

variable "api_service_name" {
  type = string
}

variable "worker_service_name" {
  type = string
}

variable "db_instance_id" {
  type = string
}

variable "queue_name" {
  type = string
}

variable "dlq_name" {
  type = string
}

variable "alarm_email" {
  description = "アラーム通知先（任意。空なら購読なし）"
  type        = string
  default     = ""
}

variable "tags" {
  type    = map(string)
  default = {}
}
