output "alb_dns_name" {
  description = "API の公開エンドポイント（ALB DNS）"
  value       = module.ecs.alb_dns_name
}

output "inbox_bucket" {
  value = module.pipeline.inbox_bucket
}

output "queue_url" {
  value = module.pipeline.queue_url
}

output "db_endpoint" {
  value = module.rds.db_endpoint
}

output "dashboard_name" {
  value = module.observability.dashboard_name
}
