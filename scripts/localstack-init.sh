#!/usr/bin/env bash
# LocalStack 起動時に S3 バケット・SQS キュー・S3→SQS イベント通知を作成する
# （開発環境 08 §3: 起動時 init スクリプトでバケット・キュー・S3イベント通知を作成）
set -euo pipefail

REGION="${AWS_DEFAULT_REGION:-ap-northeast-1}"
BUCKET="report-inbox"
QUEUE="report-queue"

awslocal s3 mb "s3://${BUCKET}" || true

QUEUE_URL=$(awslocal sqs create-queue --queue-name "${QUEUE}" \
  --query 'QueueUrl' --output text)
QUEUE_ARN=$(awslocal sqs get-queue-attributes --queue-url "${QUEUE_URL}" \
  --attribute-names QueueArn --query 'Attributes.QueueArn' --output text)

# DLQ（最大3回失敗で隔離。基本設計 §2.1）
DLQ_URL=$(awslocal sqs create-queue --queue-name "${QUEUE}-dlq" \
  --query 'QueueUrl' --output text)
DLQ_ARN=$(awslocal sqs get-queue-attributes --queue-url "${DLQ_URL}" \
  --attribute-names QueueArn --query 'Attributes.QueueArn' --output text)

awslocal sqs set-queue-attributes --queue-url "${QUEUE_URL}" \
  --attributes "{\"VisibilityTimeout\":\"300\",\"RedrivePolicy\":\"{\\\"deadLetterTargetArn\\\":\\\"${DLQ_ARN}\\\",\\\"maxReceiveCount\\\":\\\"3\\\"}\"}"

# S3 → SQS イベント通知（ObjectCreated:Put）
awslocal s3api put-bucket-notification-configuration \
  --bucket "${BUCKET}" \
  --notification-configuration "{
    \"QueueConfigurations\": [{
      \"QueueArn\": \"${QUEUE_ARN}\",
      \"Events\": [\"s3:ObjectCreated:*\"]
    }]
  }"

echo "localstack-init: bucket=${BUCKET} queue=${QUEUE_URL} dlq=${DLQ_URL} done"
