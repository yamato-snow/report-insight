variable "name_prefix" {
  description = "リソース名の接頭辞（ri-<env>）"
  type        = string
}

variable "vpc_cidr" {
  description = "VPC の CIDR"
  type        = string
}

variable "azs" {
  description = "利用する AZ 名の一覧（env 差分は tfvars で表現）"
  type        = list(string)
}

variable "public_subnet_cidrs" {
  description = "パブリックサブネット CIDR（ALB 用）。azs と同数"
  type        = list(string)
}

variable "private_subnet_cidrs" {
  description = "プライベートサブネット CIDR（ECS/RDS 用）。azs と同数"
  type        = list(string)
}

variable "single_nat_gateway" {
  description = "NAT を1つに集約するか（dev のコスト最適化）"
  type        = bool
  default     = true
}

variable "container_port" {
  description = "ECS サービスが待ち受けるコンテナポート"
  type        = number
  default     = 8000
}

variable "enable_interface_endpoints" {
  description = "ECR/Logs/SQS の Interface エンドポイントを作成するか（prod=true, dev=false）"
  type        = bool
  default     = false
}

variable "tags" {
  description = "共通タグ"
  type        = map(string)
  default     = {}
}
