# 監視: SNS 通知・主要アラーム・ダッシュボード（IaC戦略 §1 / CI設計 §6）

resource "aws_sns_topic" "alarms" {
  name = "${var.name_prefix}-alarms"
  tags = var.tags
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.alarm_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

# DLQ にメッセージが滞留＝取込失敗。即通知（構造化失敗率アラート。CI設計 §6）
resource "aws_cloudwatch_metric_alarm" "dlq_not_empty" {
  alarm_name          = "${var.name_prefix}-dlq-not-empty"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  dimensions          = { QueueName = var.dlq_name }
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]
  tags                = var.tags
}

# 取込キューの滞留（消費が追いつかない）
resource "aws_cloudwatch_metric_alarm" "queue_backlog" {
  alarm_name          = "${var.name_prefix}-queue-backlog"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 2
  threshold           = 100
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  dimensions          = { QueueName = var.queue_name }
  alarm_actions       = [aws_sns_topic.alarms.arn]
  tags                = var.tags
}

resource "aws_cloudwatch_metric_alarm" "api_cpu_high" {
  alarm_name          = "${var.name_prefix}-api-cpu-high"
  namespace           = "AWS/ECS"
  metric_name         = "CPUUtilization"
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 3
  threshold           = 85
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  dimensions          = { ClusterName = var.cluster_name, ServiceName = var.api_service_name }
  alarm_actions       = [aws_sns_topic.alarms.arn]
  tags                = var.tags
}

resource "aws_cloudwatch_metric_alarm" "rds_cpu_high" {
  alarm_name          = "${var.name_prefix}-rds-cpu-high"
  namespace           = "AWS/RDS"
  metric_name         = "CPUUtilization"
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 3
  threshold           = 85
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  dimensions          = { DBInstanceIdentifier = var.db_instance_id }
  alarm_actions       = [aws_sns_topic.alarms.arn]
  tags                = var.tags
}

# --- アプリ EMF 由来のアラーム（構造化失敗率 / LLMエラー率 / 日次コスト）---
# メトリクスは app/infra/observability/emf.py が worker/api の stdout から EMF で送出し、
# CloudWatch Logs が自動でメトリクス化する。閾値は runbook §2/§3/§5 に一致させる。

# 構造化失敗率 > 10% / 5分（分類パース失敗の割合。runbook §3）
resource "aws_cloudwatch_metric_alarm" "structured_failure_rate" {
  alarm_name          = "${var.name_prefix}-structured-failure-rate"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  threshold           = var.structured_failure_rate_threshold
  treat_missing_data  = "notBreaching"
  alarm_description   = "分類/構造化の失敗率が閾値超過（runbook §3）"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]
  tags                = var.tags

  metric_query {
    id          = "rate"
    expression  = "(FILL(failures,0)/total)*100"
    label       = "structured_failure_rate_pct"
    return_data = true
  }
  metric_query {
    id          = "failures"
    return_data = false
    metric {
      namespace   = var.metrics_namespace
      metric_name = "structured_failure"
      period      = 300
      stat        = "Sum"
      dimensions  = { Env = var.env, Service = var.worker_service_dimension }
    }
  }
  metric_query {
    id          = "total"
    return_data = false
    metric {
      namespace   = var.metrics_namespace
      metric_name = "ingest_total"
      period      = 300
      stat        = "Sum"
      dimensions  = { Env = var.env, Service = var.worker_service_dimension }
    }
  }
}

# LLM API エラー率 > 5% / 5分（縮退ラダーのトリガ。runbook §2）
resource "aws_cloudwatch_metric_alarm" "llm_error_rate" {
  alarm_name          = "${var.name_prefix}-llm-error-rate"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  threshold           = var.llm_error_rate_threshold
  treat_missing_data  = "notBreaching"
  alarm_description   = "LLM 呼び出しのエラー率が閾値超過（runbook §2 縮退ラダー）"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]
  tags                = var.tags

  metric_query {
    id          = "rate"
    expression  = "(FILL(errors,0)/total)*100"
    label       = "llm_error_rate_pct"
    return_data = true
  }
  metric_query {
    id          = "errors"
    return_data = false
    metric {
      namespace   = var.metrics_namespace
      metric_name = "llm_error"
      period      = 300
      stat        = "Sum"
      dimensions  = { Env = var.env, Service = var.worker_service_dimension }
    }
  }
  metric_query {
    id          = "total"
    return_data = false
    metric {
      namespace   = var.metrics_namespace
      metric_name = "ingest_total"
      period      = 300
      stat        = "Sum"
      dimensions  = { Env = var.env, Service = var.worker_service_dimension }
    }
  }
}

# 日次トークンコスト > ¥5,000（月次予算¥100,000 の先行指標。runbook §5 / ハンドブック S12）
# tokens_* は Env のみの集計ストリーム（emf.py が二重ディメンションで送出）を使う。
resource "aws_cloudwatch_metric_alarm" "daily_token_cost" {
  alarm_name          = "${var.name_prefix}-daily-token-cost"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  threshold           = var.daily_cost_yen_threshold
  treat_missing_data  = "notBreaching"
  alarm_description   = "日次トークンコスト（円・概算）が閾値超過（runbook §5）"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]
  tags                = var.tags

  metric_query {
    id          = "cost"
    expression  = "FILL(tin,0)*${var.yen_per_input_token}+FILL(tout,0)*${var.yen_per_output_token}"
    label       = "daily_token_cost_yen"
    return_data = true
  }
  metric_query {
    id          = "tin"
    return_data = false
    metric {
      namespace   = var.metrics_namespace
      metric_name = "tokens_input"
      period      = 86400
      stat        = "Sum"
      dimensions  = { Env = var.env }
    }
  }
  metric_query {
    id          = "tout"
    return_data = false
    metric {
      namespace   = var.metrics_namespace
      metric_name = "tokens_output"
      period      = 86400
      stat        = "Sum"
      dimensions  = { Env = var.env }
    }
  }
}

resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = "${var.name_prefix}-overview"
  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "SQS 取込キュー / DLQ"
          region = var.region
          metrics = [
            ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", var.queue_name],
            ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", var.dlq_name],
          ]
          period = 60
          view   = "timeSeries"
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "ECS / RDS CPU"
          region = var.region
          metrics = [
            ["AWS/ECS", "CPUUtilization", "ClusterName", var.cluster_name, "ServiceName", var.api_service_name],
            ["AWS/ECS", "CPUUtilization", "ClusterName", var.cluster_name, "ServiceName", var.worker_service_name],
            ["AWS/RDS", "CPUUtilization", "DBInstanceIdentifier", var.db_instance_id],
          ]
          period = 300
          view   = "timeSeries"
        }
      },
    ]
  })
}
