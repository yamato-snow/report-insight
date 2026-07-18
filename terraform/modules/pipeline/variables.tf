variable "name_prefix" {
  type = string
}

variable "visibility_timeout_seconds" {
  description = "取込ワーカーの処理時間に合わせる（可視性タイムアウト）"
  type        = number
  default     = 120
}

variable "max_receive_count" {
  description = "この回数を超えて失敗したメッセージは DLQ へ（基本設計 §2.1）"
  type        = number
  default     = 3
}

variable "tags" {
  type    = map(string)
  default = {}
}
