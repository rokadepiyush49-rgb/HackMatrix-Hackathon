# ── Container registry ───────────────────────────────────────────────────────
resource "aws_ecr_repository" "app" {
  for_each             = toset(["sutra-api", "sutra-web"])
  name                 = "${each.key}-${var.env}"
  image_tag_mutability = "IMMUTABLE" # a tag, once pushed, always means the same bytes
  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = aws_kms_key.data.arn
  }
  image_scanning_configuration { scan_on_push = true }
  tags = local.tags
}

resource "aws_ecr_lifecycle_policy" "app" {
  for_each   = aws_ecr_repository.app
  repository = each.value.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 50 images (rollback window); signatures/SBOMs share the repo"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 50 }
      action       = { type = "expire" }
    }]
  })
}

# ── GitHub Actions → AWS without stored keys (OIDC federation) ──────────────
# The release workflow gets a 1-hour credential scoped to pushing these two repositories,
# and only when it runs on main of this repository.
resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
  tags           = local.tags
}

data "aws_iam_policy_document" "github_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repository}:ref:refs/heads/main", "repo:${var.github_repository}:environment:${var.env}"]
    }
  }
}

resource "aws_iam_role" "github_release" {
  name                 = "${local.name}-github-release"
  assume_role_policy   = data.aws_iam_policy_document.github_assume.json
  max_session_duration = 3600
  tags                 = local.tags
}

data "aws_iam_policy_document" "github_release" {
  statement {
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }
  statement {
    actions = ["ecr:BatchCheckLayerAvailability", "ecr:BatchGetImage", "ecr:CompleteLayerUpload",
    "ecr:InitiateLayerUpload", "ecr:PutImage", "ecr:UploadLayerPart", "ecr:DescribeImages"]
    resources = [for r in aws_ecr_repository.app : r.arn]
  }
  statement {
    actions   = ["kms:GenerateDataKey", "kms:Decrypt"]
    resources = [aws_kms_key.data.arn]
  }
}

resource "aws_iam_role_policy" "github_release" {
  role   = aws_iam_role.github_release.id
  policy = data.aws_iam_policy_document.github_release.json
}

# ── Workload identities (EKS Pod Identity) ───────────────────────────────────
# Each Kubernetes service account gets exactly the AWS permissions its job needs. No node-wide
# credentials, no long-lived keys in Secrets.
data "aws_iam_policy_document" "app" {
  statement {
    sid       = "WriteOnceEvidence"
    actions   = ["s3:PutObject", "s3:PutObjectRetention", "s3:GetObject", "s3:GetObjectRetention", "s3:GetObjectVersion"]
    resources = ["${aws_s3_bucket.evidence.arn}/packs/*"]
  }
  statement {
    sid       = "EvidenceKey"
    actions   = ["kms:GenerateDataKey", "kms:Decrypt"]
    resources = [aws_kms_key.evidence.arn]
  }
  statement {
    # Claude in Amazon Bedrock (Messages API endpoint, bedrock-mantle). Only used when the Helm value
    # config.llmEnabled is true — see ADR 015 for why prod ships with it off. Narrow `resources` to the
    # Claude model ARNs once the account's model access is approved.
    sid       = "InvokeClaude"
    actions   = ["bedrock-mantle:CreateInference"]
    resources = ["*"]
  }
}

module "pod_identity_app" {
  source  = "terraform-aws-modules/eks-pod-identity/aws"
  version = "~> 2.9"

  name                    = "${local.name}-app"
  attach_custom_policy    = true
  source_policy_documents = [data.aws_iam_policy_document.app.json]

  associations = {
    api  = { cluster_name = module.eks.cluster_name, namespace = "sutra-${var.env}", service_account = "sutra-api" }
    jobs = { cluster_name = module.eks.cluster_name, namespace = "sutra-${var.env}", service_account = "sutra-jobs" }
  }
  tags = local.tags
}

module "pod_identity_lb_controller" {
  source  = "terraform-aws-modules/eks-pod-identity/aws"
  version = "~> 2.9"

  name                            = "${local.name}-aws-lbc"
  attach_aws_lb_controller_policy = true
  associations = {
    this = { cluster_name = module.eks.cluster_name, namespace = "kube-system", service_account = "aws-load-balancer-controller" }
  }
  tags = local.tags
}

module "pod_identity_external_secrets" {
  source  = "terraform-aws-modules/eks-pod-identity/aws"
  version = "~> 2.9"

  name                                  = "${local.name}-external-secrets"
  attach_external_secrets_policy        = true
  external_secrets_secrets_manager_arns = [aws_secretsmanager_secret.app.arn]
  external_secrets_kms_key_arns         = [aws_kms_key.data.arn]
  external_secrets_create_permission    = false
  associations = {
    this = { cluster_name = module.eks.cluster_name, namespace = "external-secrets", service_account = "external-secrets" }
  }
  tags = local.tags
}
