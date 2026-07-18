# 取込パイプライン基盤: S3(取込) → イベント通知 → SQS → worker、失敗は DLQ（基本設計 §2.1）

resource "aws_s3_bucket" "inbox" {
  bucket = "${var.name_prefix}-report-inbox"
  tags   = merge(var.tags, { Name = "${var.name_prefix}-report-inbox" })

  # 取込バケットは破壊ガードレール（IaC戦略 §9）
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "inbox" {
  bucket = aws_s3_bucket.inbox.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "inbox" {
  bucket = aws_s3_bucket.inbox.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "aws:kms"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "inbox" {
  bucket                  = aws_s3_bucket.inbox.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# --- SQS + DLQ ------------------------------------------------------------
resource "aws_sqs_queue" "dlq" {
  name                      = "${var.name_prefix}-report-dlq"
  message_retention_seconds = 1209600 # 14日
  sqs_managed_sse_enabled   = true
  tags                      = var.tags
}

resource "aws_sqs_queue" "main" {
  name                       = "${var.name_prefix}-report-queue"
  visibility_timeout_seconds = var.visibility_timeout_seconds
  sqs_managed_sse_enabled    = true
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = var.max_receive_count
  })
  tags = var.tags
}

# S3 → SQS 送信を許可（当該バケットからのみ）
data "aws_iam_policy_document" "sqs_from_s3" {
  statement {
    sid       = "AllowS3SendMessage"
    effect    = "Allow"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.main.arn]

    principals {
      type        = "Service"
      identifiers = ["s3.amazonaws.com"]
    }
    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_s3_bucket.inbox.arn]
    }
  }
}

resource "aws_sqs_queue_policy" "main" {
  queue_url = aws_sqs_queue.main.id
  policy    = data.aws_iam_policy_document.sqs_from_s3.json
}

resource "aws_s3_bucket_notification" "inbox" {
  bucket = aws_s3_bucket.inbox.id

  queue {
    queue_arn     = aws_sqs_queue.main.arn
    events        = ["s3:ObjectCreated:*"]
    filter_suffix = ".json"
  }

  depends_on = [aws_sqs_queue_policy.main]
}
