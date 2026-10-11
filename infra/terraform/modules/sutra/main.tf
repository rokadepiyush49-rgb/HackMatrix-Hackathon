# Zones are pinned by name: a zone AWS adds, or one that is briefly impaired, never reshuffles the subnets.
data "aws_availability_zones" "available" {
  filter {
    name   = "zone-name"
    values = [for letter in slice(["a", "b", "c", "d"], 0, var.az_count) : "${data.aws_region.current.name}${letter}"]
  }
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
  #checkov:skip=CKV2_AWS_64:Default key policy on purpose - IAM policies in this account grant its use
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
  #checkov:skip=CKV2_AWS_64:Default key policy on purpose - IAM policies in this account grant its use
  description             = "${local.name}: evidence packs (S3 Object Lock)"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  tags                    = local.tags
}

resource "aws_kms_alias" "evidence" {
  name          = "alias/${local.name}-evidence"
  target_key_id = aws_kms_key.evidence.key_id
}

# CloudWatch Logs can only use a customer-managed key that names it in the key policy.
resource "aws_kms_key" "logs" {
  description             = "${local.name}: CloudWatch log groups (WAF)"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # The default key policy: IAM policies in this account decide who else may use the key.
        Sid       = "AccountAdministersTheKey"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      },
      {
        Sid       = "CloudWatchLogsInThisAccount"
        Effect    = "Allow"
        Principal = { Service = "logs.${data.aws_region.current.name}.amazonaws.com" }
        Action    = ["kms:Encrypt*", "kms:Decrypt*", "kms:ReEncrypt*", "kms:GenerateDataKey*", "kms:Describe*"]
        Resource  = "*"
        Condition = {
          ArnLike = {
            "kms:EncryptionContext:aws:logs:arn" = "arn:aws:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:log-group:*"
          }
        }
      },
    ]
  })
  tags = local.tags
}

resource "aws_kms_alias" "logs" {
  name          = "alias/${local.name}-logs"
  target_key_id = aws_kms_key.logs.key_id
}
