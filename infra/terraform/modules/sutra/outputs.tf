output "cluster_name" { value = module.eks.cluster_name }
output "vpc_cidr" { value = var.vpc_cidr }
output "ecr_repositories" { value = { for k, r in aws_ecr_repository.app : k => r.repository_url } }
output "github_release_role_arn" { value = aws_iam_role.github_release.arn }
output "evidence_bucket" { value = aws_s3_bucket.evidence.bucket }
output "evidence_kms_key_arn" { value = aws_kms_key.evidence.arn }
output "app_secret_name" { value = aws_secretsmanager_secret.app.name }
output "waf_acl_arn" { value = aws_wafv2_web_acl.app.arn }
output "db_endpoint" { value = module.db.db_instance_address }
output "db_master_secret_arn" { value = module.db.db_instance_master_user_secret_arn }
output "prometheus_workspace_endpoint" { value = aws_prometheus_workspace.metrics.prometheus_endpoint }
output "alerts_topic_arn" { value = aws_sns_topic.alerts.arn }
