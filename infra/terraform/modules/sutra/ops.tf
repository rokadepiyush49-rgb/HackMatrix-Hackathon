# ── Cost guardrail ───────────────────────────────────────────────────────────
resource "aws_budgets_budget" "monthly" {
  name         = "${local.name}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"
  cost_filter {
    name   = "TagKeyValue"
    values = [format("user:Environment$%s", var.env)] # cost-allocation tag filter
  }
  dynamic "notification" {
    for_each = length(var.budget_alert_emails) > 0 ? [80, 100] : []
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "PERCENTAGE"
      notification_type          = notification.value == 100 ? "FORECASTED" : "ACTUAL"
      subscriber_email_addresses = var.budget_alert_emails
    }
  }
}

# ── Telemetry backends for the OpenTelemetry collector ───────────────────────
resource "aws_prometheus_workspace" "metrics" {
  alias = local.name
  tags  = local.tags
}

module "pod_identity_otel" {
  source  = "terraform-aws-modules/eks-pod-identity/aws"
  version = "~> 2.9"

  name = "${local.name}-otel-collector"
  additional_policy_arns = {
    xray = "arn:aws:iam::aws:policy/AWSXrayWriteOnlyAccess"
    amp  = "arn:aws:iam::aws:policy/AmazonPrometheusRemoteWriteAccess"
  }
  associations = {
    this = { cluster_name = module.eks.cluster_name, namespace = "observability", service_account = "otel-collector" }
  }
  tags = local.tags
}

# ── Alarms that page a human ─────────────────────────────────────────────────
resource "aws_sns_topic" "alerts" {
  name              = "${local.name}-alerts"
  kms_master_key_id = aws_kms_key.data.id
  tags              = local.tags
}

resource "aws_cloudwatch_metric_alarm" "db_cpu" {
  alarm_name          = "${local.name}-db-cpu-high"
  namespace           = "AWS/RDS"
  metric_name         = "CPUUtilization"
  dimensions          = { DBInstanceIdentifier = module.db.db_instance_identifier }
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 3
  threshold           = 80
  comparison_operator = "GreaterThanThreshold"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  tags                = local.tags
}

resource "aws_cloudwatch_metric_alarm" "db_storage" {
  alarm_name          = "${local.name}-db-free-storage-low"
  namespace           = "AWS/RDS"
  metric_name         = "FreeStorageSpace"
  dimensions          = { DBInstanceIdentifier = module.db.db_instance_identifier }
  statistic           = "Minimum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 10737418240 # 10 GiB
  comparison_operator = "LessThanThreshold"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  tags                = local.tags
}

resource "aws_cloudwatch_metric_alarm" "waf_blocked_spike" {
  alarm_name          = "${local.name}-waf-blocked-spike"
  namespace           = "AWS/WAFV2"
  metric_name         = "BlockedRequests"
  dimensions          = { WebACL = aws_wafv2_web_acl.app.name, Region = data.aws_region.current.name, Rule = "ALL" }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 500
  comparison_operator = "GreaterThanThreshold"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  tags                = local.tags
}
