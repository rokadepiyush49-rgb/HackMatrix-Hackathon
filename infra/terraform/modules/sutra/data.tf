# ── PostgreSQL (RDS) ─────────────────────────────────────────────────────────
# Postgres is SUTRA's only system of record: bitemporal events, the evidence book, the audit hash
# chain and case state all need ACID transactions together (see docs/adr/002).
resource "aws_security_group" "db" {
  #checkov:skip=CKV2_AWS_5:Attached to the RDS instance through module.db (vpc_security_group_ids)
  name_prefix = "${local.name}-db-"
  description = "PostgreSQL from EKS nodes/pods only"
  vpc_id      = module.vpc.vpc_id
  ingress {
    description     = "Postgres from cluster"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [module.eks.node_security_group_id]
  }
  tags = local.tags
}

module "db" {
  source  = "terraform-aws-modules/rds/aws"
  version = "~> 6.10"

  identifier           = local.name
  engine               = "postgres"
  engine_version       = "17"
  family               = "postgres17"
  major_engine_version = "17"
  instance_class       = var.db_instance_class

  allocated_storage     = 50
  max_allocated_storage = 500 # storage autoscaling
  storage_type          = "gp3"
  storage_encrypted     = true
  kms_key_id            = aws_kms_key.data.arn

  db_name  = "sutra"
  username = "sutra_admin"
  port     = 5432
  # Master password generated and rotated by RDS in Secrets Manager — never in Terraform state.
  manage_master_user_password         = true
  iam_database_authentication_enabled = true

  multi_az               = var.db_multi_az
  db_subnet_group_name   = module.vpc.database_subnet_group_name
  vpc_security_group_ids = [aws_security_group.db.id]

  backup_retention_period          = 35            # the RDS maximum: point-in-time restore to any second in 5 weeks
  backup_window                    = "20:00-21:00" # 01:30-02:30 IST
  maintenance_window               = "Sun:21:30-Sun:22:30"
  deletion_protection              = true
  skip_final_snapshot              = false
  final_snapshot_identifier_prefix = "${local.name}-final"
  copy_tags_to_snapshot            = true

  performance_insights_enabled          = true
  performance_insights_kms_key_id       = aws_kms_key.data.arn
  performance_insights_retention_period = 7
  monitoring_interval                   = 60
  create_monitoring_role                = true
  enabled_cloudwatch_logs_exports       = ["postgresql", "upgrade"]

  parameters = [
    { name = "rds.force_ssl", value = "1" },                 # TLS for every connection
    { name = "log_min_duration_statement", value = "1000" }, # log statements slower than 1 s
    { name = "shared_preload_libraries", value = "pg_stat_statements,pgaudit", apply_method = "pending-reboot" },
    { name = "pgaudit.log", value = "ddl,role" }, # schema and privilege changes are audited
  ]

  tags = local.tags
}

# Cross-region automated-backup replication: point-in-time restore survives a region outage.
resource "aws_db_instance_automated_backups_replication" "dr" {
  count                  = var.enable_dr ? 1 : 0
  provider               = aws.dr
  source_db_instance_arn = module.db.db_instance_arn
  kms_key_id             = aws_kms_key.dr[0].arn
  retention_period       = 14
}

resource "aws_kms_key" "dr" {
  #checkov:skip=CKV2_AWS_64:Default key policy on purpose - IAM policies in this account grant its use
  count                   = var.enable_dr ? 1 : 0
  provider                = aws.dr
  description             = "${local.name}: DR copies (backups, evidence replicas)"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  tags                    = local.tags
}

# ── Valkey (ElastiCache) ─────────────────────────────────────────────────────
# Shared rate-limit counters across API replicas. Valkey is the Linux Foundation fork of Redis;
# ElastiCache prices it lower than Redis OSS and it stays wire-compatible.
resource "aws_security_group" "cache" {
  name_prefix = "${local.name}-cache-"
  description = "Valkey from EKS nodes/pods only"
  vpc_id      = module.vpc.vpc_id
  ingress {
    description     = "Valkey from cluster"
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [module.eks.node_security_group_id]
  }
  tags = local.tags
}

resource "aws_elasticache_subnet_group" "cache" {
  name       = local.name
  subnet_ids = module.vpc.database_subnets
}

resource "random_password" "cache" {
  length  = 48
  special = false
}

resource "aws_elasticache_replication_group" "cache" {
  #checkov:skip=CKV2_AWS_50:Multi-AZ failover follows var.db_multi_az - on in prod, one node in staging to save cost
  replication_group_id       = local.name
  description                = "SUTRA shared counters"
  engine                     = "valkey"
  engine_version             = "8.0"
  node_type                  = var.cache_node_type
  num_cache_clusters         = var.db_multi_az ? 2 : 1
  automatic_failover_enabled = var.db_multi_az
  multi_az_enabled           = var.db_multi_az
  subnet_group_name          = aws_elasticache_subnet_group.cache.name
  security_group_ids         = [aws_security_group.cache.id]
  at_rest_encryption_enabled = true
  kms_key_id                 = aws_kms_key.data.arn
  transit_encryption_enabled = true
  auth_token                 = random_password.cache.result
  snapshot_retention_limit   = 1
  tags                       = local.tags
}

# ── Application secret ───────────────────────────────────────────────────────
# One JSON secret consumed by External Secrets Operator (see deploy/helm/sutra/templates/externalsecret.yaml).
resource "random_password" "app_db" {
  length  = 40
  special = false # goes inside a URL
}

resource "random_password" "jwt" {
  length  = 64
  special = false
}

resource "random_password" "pii_hmac" {
  length  = 64
  special = false
}

resource "aws_secretsmanager_secret" "app" {
  #checkov:skip=CKV2_AWS_57:Values come from Terraform random_password - rotate by re-applying with a coordinated rollout
  name                    = "sutra/${var.env}/app"
  description             = "SUTRA runtime secrets (DB URL, JWT and PII-HMAC keys, cache URI, LLM key)"
  kms_key_id              = aws_kms_key.data.arn
  recovery_window_in_days = 30
  tags                    = local.tags
}

resource "aws_secretsmanager_secret_version" "app" {
  secret_id = aws_secretsmanager_secret.app.id
  secret_string = jsonencode({
    # sutra_app is a least-privilege role created once by the bootstrap runbook (docs/operations/runbook.md).
    database_url           = "postgresql+psycopg://sutra_app:${random_password.app_db.result}@${module.db.db_instance_address}:5432/sutra?sslmode=require"
    jwt_secret             = random_password.jwt.result
    pii_hmac_key           = random_password.pii_hmac.result
    rate_limit_storage_uri = "rediss://:${random_password.cache.result}@${aws_elasticache_replication_group.cache.primary_endpoint_address}:6379/0"
    anthropic_api_key      = "" # set out of band; empty keeps the deterministic engine
  })
  # Rotation happens in Secrets Manager; Terraform must not roll it back on the next apply.
  lifecycle { ignore_changes = [secret_string] }
}
