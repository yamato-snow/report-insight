output "state_bucket_name" {
  description = "envs/*/backend.tf の bucket に指定する値"
  value       = aws_s3_bucket.tfstate.id
}

output "state_bucket_arn" {
  description = "state バケットの ARN（後続の OIDC ロール権限で参照する）"
  value       = aws_s3_bucket.tfstate.arn
}

output "lock_table_name" {
  description = "envs/*/backend.tf の dynamodb_table に指定する値"
  value       = aws_dynamodb_table.tflock.name
}

output "lock_table_arn" {
  description = "ロックテーブルの ARN（後続の OIDC ロール権限で参照する）"
  value       = aws_dynamodb_table.tflock.arn
}
