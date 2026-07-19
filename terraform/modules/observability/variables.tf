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

# --- アプリ EMF メトリクス（app/infra/observability/emf.py が送出）---
variable "env" {
  description = "EMF の Env ディメンション（dev/prod）。アプリの RI_ENV と一致させる"
  type        = string
}

variable "metrics_namespace" {
  description = "アプリ EMF の名前空間（app の metrics_namespace と一致）"
  type        = string
  default     = "ReportInsight"
}

variable "worker_service_dimension" {
  description = "取込メトリクス（構造化失敗率・LLMエラー率）の Service ディメンション値"
  type        = string
  default     = "worker"
}

variable "structured_failure_rate_threshold" {
  description = "構造化失敗率アラームの閾値（%）。runbook §3 に合わせ 10%"
  type        = number
  default     = 10
}

variable "llm_error_rate_threshold" {
  description = "LLM エラー率アラームの閾値（%）。runbook §2 に合わせ 5%"
  type        = number
  default     = 5
}

variable "daily_cost_yen_threshold" {
  description = "日次トークンコストアラームの閾値（円）。runbook §5 / ハンドブック S12 に合わせ 5,000"
  type        = number
  default     = 5000
}

variable "yen_per_input_token" {
  description = "入力トークン単価（円/トークン）。ブレンド概算でよい（先行指標のため）"
  type        = number
  default     = 0.0006
}

variable "yen_per_output_token" {
  description = "出力トークン単価（円/トークン）。ブレンド概算でよい（先行指標のため）"
  type        = number
  default     = 0.003
}

variable "tags" {
  type    = map(string)
  default = {}
}
