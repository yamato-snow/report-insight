# dev 環境: モジュール呼び出しのみ（リソース直書き禁止。IaC戦略 §1）。
# 環境差分は terraform.tfvars と backend.tf だけで表現し、この構成は prod と同一に保つ。

locals {
  name_prefix = "ri-${var.env}"
  tags = {
    Project   = "report-insight"
    Env       = var.env
    ManagedBy = "terraform"
  }
}

# シークレットは「箱」だけ作る。値の投入は初期構築時に管理者が CLI で行う（IaC戦略 §6）。
resource "aws_secretsmanager_secret" "database_url" {
  name = "${local.name_prefix}/database-url"
  tags = local.tags
}

resource "aws_secretsmanager_secret" "anthropic_api_key" {
  name = "${local.name_prefix}/anthropic-api-key"
  tags = local.tags
}

resource "aws_secretsmanager_secret" "slack_webhook_url" {
  name = "${local.name_prefix}/slack-webhook-url"
  tags = local.tags
}

module "network" {
  source               = "../../modules/network"
  name_prefix          = local.name_prefix
  vpc_cidr             = var.vpc_cidr
  azs                  = var.azs
  public_subnet_cidrs  = var.public_subnet_cidrs
  private_subnet_cidrs = var.private_subnet_cidrs
  single_nat_gateway   = var.single_nat_gateway
  container_port       = var.container_port
  tags                 = local.tags
}

module "pipeline" {
  source      = "../../modules/pipeline"
  name_prefix = local.name_prefix
  tags        = local.tags
}

module "rds" {
  source              = "../../modules/rds"
  name_prefix         = local.name_prefix
  subnet_ids          = module.network.private_subnet_ids
  security_group_id   = module.network.rds_sg_id
  instance_class      = var.db_instance_class
  multi_az            = var.multi_az
  deletion_protection = var.deletion_protection
  skip_final_snapshot = var.skip_final_snapshot
  tags                = local.tags
}

module "ecs" {
  source               = "../../modules/ecs"
  name_prefix          = local.name_prefix
  region               = var.region
  vpc_id               = module.network.vpc_id
  public_subnet_ids    = module.network.public_subnet_ids
  private_subnet_ids   = module.network.private_subnet_ids
  alb_sg_id            = module.network.alb_sg_id
  ecs_sg_id            = module.network.ecs_sg_id
  container_port       = var.container_port
  image                = var.image
  capacity_provider    = var.capacity_provider
  api_desired_count    = var.api_desired_count
  worker_desired_count = var.worker_desired_count

  environment = {
    LLM_PROVIDER    = var.llm_provider
    MODEL_CLASSIFY  = var.model_classify
    MODEL_GENERATE  = var.model_generate
    AWS_REGION      = var.region
    S3_INBOX_BUCKET = module.pipeline.inbox_bucket
    SQS_QUEUE_URL   = module.pipeline.queue_url
    RI_ENV          = var.env
  }
  secret_arns = {
    DATABASE_URL      = aws_secretsmanager_secret.database_url.arn
    ANTHROPIC_API_KEY = aws_secretsmanager_secret.anthropic_api_key.arn
    SLACK_WEBHOOK_URL = aws_secretsmanager_secret.slack_webhook_url.arn
  }
  app_secret_arns = [
    aws_secretsmanager_secret.database_url.arn,
    aws_secretsmanager_secret.anthropic_api_key.arn,
    aws_secretsmanager_secret.slack_webhook_url.arn,
    module.rds.master_user_secret_arn,
  ]

  s3_bucket_arn = module.pipeline.inbox_bucket_arn
  queue_arn     = module.pipeline.queue_arn
  tags          = local.tags
}

module "observability" {
  source              = "../../modules/observability"
  name_prefix         = local.name_prefix
  region              = var.region
  cluster_name        = module.ecs.cluster_name
  api_service_name    = module.ecs.api_service_name
  worker_service_name = module.ecs.worker_service_name
  db_instance_id      = module.rds.db_instance_id
  queue_name          = module.pipeline.queue_name
  dlq_name            = module.pipeline.dlq_name
  alarm_email         = var.alarm_email
  env                 = var.env
  tags                = local.tags
}
