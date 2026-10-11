# Evidence packs are legal records. S3 Object Lock makes every object write-once for the retention
# period; in COMPLIANCE mode not even the root account can delete or shorten it. Versioning is
# required by Object Lock and keeps every write; the manifest hash in Postgres proves integrity.
resource "aws_s3_bucket" "evidence" {
  #checkov:skip=CKV_AWS_18:No access-log bucket in this stack yet - follow-up: CloudTrail S3 data events
  #checkov:skip=CKV2_AWS_62:Nothing consumes object events - writes are recorded in Postgres and the audit chain
  #checkov:skip=CKV2_AWS_61:Object Lock governs retention - a lifecycle rule must never expire legal evidence early
  bucket_prefix       = "${local.name}-evidence-"
  object_lock_enabled = true
  tags                = merge(local.tags, { DataClass = "legal-evidence" })
}

resource "aws_s3_bucket_versioning" "evidence" {
  bucket = aws_s3_bucket.evidence.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_object_lock_configuration" "evidence" {
  bucket = aws_s3_bucket.evidence.id
  rule {
    default_retention {
      mode = var.evidence_lock_mode
      days = var.evidence_retention_days
    }
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "evidence" {
  bucket = aws_s3_bucket.evidence.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.evidence.arn
    }
    bucket_key_enabled = true # cuts KMS request cost by ~99% for many small objects
  }
}

resource "aws_s3_bucket_public_access_block" "evidence" {
  bucket                  = aws_s3_bucket.evidence.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "evidence" {
  bucket = aws_s3_bucket.evidence.id
  rule { object_ownership = "BucketOwnerEnforced" }
}

data "aws_iam_policy_document" "evidence" {
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.evidence.arn, "${aws_s3_bucket.evidence.arn}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
  statement {
    sid       = "DenyWrongKmsKey"
    effect    = "Deny"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.evidence.arn}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "StringNotEqualsIfExists"
      variable = "s3:x-amz-server-side-encryption-aws-kms-key-id"
      values   = [aws_kms_key.evidence.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "evidence" {
  bucket = aws_s3_bucket.evidence.id
  policy = data.aws_iam_policy_document.evidence.json
}

# ── DR replica in ap-south-2 (Hyderabad): still inside India for RBI data localisation ──
resource "aws_s3_bucket" "evidence_dr" {
  #checkov:skip=CKV_AWS_18:No access-log bucket in this stack yet - follow-up: CloudTrail S3 data events
  #checkov:skip=CKV2_AWS_62:Nothing consumes object events - writes are recorded in Postgres and the audit chain
  #checkov:skip=CKV2_AWS_61:Object Lock governs retention - a lifecycle rule must never expire legal evidence early
  #checkov:skip=CKV_AWS_144:This bucket is the cross-region replica
  # Checkov cannot link the count-indexed copy to the versioning, encryption and public-access-block
  # resources below, so it reports them missing on evidence_dr[0]; they exist.
  #checkov:skip=CKV_AWS_21:False positive on evidence_dr[0] - see aws_s3_bucket_versioning.evidence_dr
  #checkov:skip=CKV_AWS_145:False positive on evidence_dr[0] - see aws_s3_bucket_server_side_encryption_configuration.evidence_dr
  #checkov:skip=CKV2_AWS_6:False positive on evidence_dr[0] - see aws_s3_bucket_public_access_block.evidence_dr
  count               = var.enable_dr ? 1 : 0
  provider            = aws.dr
  bucket_prefix       = "${local.name}-evidence-dr-"
  object_lock_enabled = true
  tags                = merge(local.tags, { DataClass = "legal-evidence" })
}

resource "aws_s3_bucket_versioning" "evidence_dr" {
  count    = var.enable_dr ? 1 : 0
  provider = aws.dr
  bucket   = aws_s3_bucket.evidence_dr[0].id
  versioning_configuration { status = "Enabled" }
}

# Replicas arrive encrypted with the DR key (replication rule below); the default makes that hold for
# anything else written here too.
resource "aws_s3_bucket_server_side_encryption_configuration" "evidence_dr" {
  count    = var.enable_dr ? 1 : 0
  provider = aws.dr
  bucket   = aws_s3_bucket.evidence_dr[0].id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.dr[0].arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "evidence_dr" {
  count                   = var.enable_dr ? 1 : 0
  provider                = aws.dr
  bucket                  = aws_s3_bucket.evidence_dr[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

data "aws_iam_policy_document" "replication_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["s3.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "replication" {
  count              = var.enable_dr ? 1 : 0
  name_prefix        = "${local.name}-s3-repl-"
  assume_role_policy = data.aws_iam_policy_document.replication_assume.json
  tags               = local.tags
}

data "aws_iam_policy_document" "replication" {
  count = var.enable_dr ? 1 : 0
  statement {
    actions   = ["s3:GetReplicationConfiguration", "s3:ListBucket"]
    resources = [aws_s3_bucket.evidence.arn]
  }
  statement {
    actions   = ["s3:GetObjectVersionForReplication", "s3:GetObjectVersionAcl", "s3:GetObjectVersionTagging", "s3:GetObjectRetention", "s3:GetObjectLegalHold"]
    resources = ["${aws_s3_bucket.evidence.arn}/*"]
  }
  statement {
    actions   = ["s3:ReplicateObject", "s3:ReplicateDelete", "s3:ReplicateTags", "s3:ObjectOwnerOverrideToBucketOwner"]
    resources = ["${aws_s3_bucket.evidence_dr[0].arn}/*"]
  }
  statement {
    actions   = ["kms:Decrypt"]
    resources = [aws_kms_key.evidence.arn]
  }
  statement {
    actions   = ["kms:Encrypt", "kms:GenerateDataKey"]
    resources = [aws_kms_key.dr[0].arn]
  }
}

resource "aws_iam_role_policy" "replication" {
  count  = var.enable_dr ? 1 : 0
  role   = aws_iam_role.replication[0].id
  policy = data.aws_iam_policy_document.replication[0].json
}

resource "aws_s3_bucket_replication_configuration" "evidence" {
  count      = var.enable_dr ? 1 : 0
  depends_on = [aws_s3_bucket_versioning.evidence, aws_s3_bucket_versioning.evidence_dr]
  role       = aws_iam_role.replication[0].arn
  bucket     = aws_s3_bucket.evidence.id
  rule {
    id     = "evidence-to-dr"
    status = "Enabled"
    filter {}
    delete_marker_replication { status = "Disabled" }
    source_selection_criteria {
      sse_kms_encrypted_objects { status = "Enabled" }
    }
    destination {
      bucket        = aws_s3_bucket.evidence_dr[0].arn
      storage_class = "STANDARD_IA"
      encryption_configuration { replica_kms_key_id = aws_kms_key.dr[0].arn }
    }
  }
}
