output "db_instance_id" {
  value = aws_db_instance.this.id
}

output "db_endpoint" {
  value = aws_db_instance.this.endpoint
}

output "db_address" {
  value = aws_db_instance.this.address
}

output "master_user_secret_arn" {
  description = "Secrets Manager が自動管理するマスターユーザ資格情報の ARN"
  value       = aws_db_instance.this.master_user_secret[0].secret_arn
}
