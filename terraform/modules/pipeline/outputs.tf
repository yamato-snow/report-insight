output "inbox_bucket" {
  value = aws_s3_bucket.inbox.bucket
}

output "inbox_bucket_arn" {
  value = aws_s3_bucket.inbox.arn
}

output "queue_url" {
  value = aws_sqs_queue.main.id
}

output "queue_arn" {
  value = aws_sqs_queue.main.arn
}

output "queue_name" {
  value = aws_sqs_queue.main.name
}

output "dlq_arn" {
  value = aws_sqs_queue.dlq.arn
}

output "dlq_name" {
  value = aws_sqs_queue.dlq.name
}
