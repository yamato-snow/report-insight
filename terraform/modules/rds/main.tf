# RDS PostgreSQL + pgvector（IaC戦略 §1 / §6 / §9）
# マスターパスワードは manage_master_user_password で Secrets Manager 自動管理（Terraform に値を持たせない）。

resource "aws_db_subnet_group" "this" {
  name       = "${var.name_prefix}-db-subnets"
  subnet_ids = var.subnet_ids
  tags       = merge(var.tags, { Name = "${var.name_prefix}-db-subnets" })
}

resource "aws_db_parameter_group" "this" {
  name   = "${var.name_prefix}-pg"
  family = var.parameter_group_family
  tags   = var.tags

  # pgvector は拡張のため shared_preload_libraries は不要。接続ログのみ有効化。
  parameter {
    name  = "log_connections"
    value = "1"
  }
}

resource "aws_db_instance" "this" {
  identifier     = "${var.name_prefix}-db"
  engine         = "postgres"
  engine_version = var.engine_version
  instance_class = var.instance_class

  allocated_storage     = var.allocated_storage
  max_allocated_storage = var.allocated_storage * 2
  storage_type          = "gp3"
  storage_encrypted     = true

  db_name  = var.db_name
  username = var.master_username
  # 平文パスワードを保持しない（IaC戦略 §6）
  manage_master_user_password = true

  multi_az               = var.multi_az
  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [var.security_group_id]
  parameter_group_name   = aws_db_parameter_group.this.name

  backup_retention_period   = var.backup_retention_period
  deletion_protection       = var.deletion_protection
  skip_final_snapshot       = var.skip_final_snapshot
  final_snapshot_identifier = var.skip_final_snapshot ? null : "${var.name_prefix}-db-final"

  auto_minor_version_upgrade = true
  apply_immediately          = false

  tags = merge(var.tags, { Name = "${var.name_prefix}-db" })

  # 破壊ガードレール（IaC戦略 §9）。dev 撤収時のみコード側で外す運用とする。
  lifecycle {
    prevent_destroy = true
  }
}
