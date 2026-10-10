data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  name = "sutra-${var.env}"
  azs  = slice(data.aws_availability_zones.available.names, 0, var.az_count)
  tags = {
    Project     = "sutra"
    Environment = var.env
    ManagedBy   = "terraform"
    DataClass   = "confidential-financial" # drives backup, logging and access reviews
  }
}

# ── Encryption keys ──────────────────────────────────────────────────────────
# One customer-managed key per data domain: revoking or auditing one never touches the others.
resource "aws_kms_key" "data" {
  description             = "${local.name}: RDS, ElastiCache, Secrets Manager"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  tags                    = local.tags
}

resource "aws_kms_alias" "data" {
  name          = "alias/${local.name}-data"
  target_key_id = aws_kms_key.data.key_id
}

resource "aws_kms_key" "evidence" {
  description             = "${local.name}: evidence packs (S3 Object Lock)"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  tags                    = local.tags
}

resource "aws_kms_alias" "evidence" {
  name          = "alias/${local.name}-evidence"
  target_key_id = aws_kms_key.evidence.key_id
}
