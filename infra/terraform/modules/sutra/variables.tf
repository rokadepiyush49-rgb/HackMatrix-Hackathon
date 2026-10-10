variable "env" {
  description = "staging | prod"
  type        = string
  validation {
    condition     = contains(["staging", "prod"], var.env)
    error_message = "env must be staging or prod."
  }
}

variable "vpc_cidr" {
  description = "Must match networkPolicy.vpcCidr in the Helm values"
  type        = string
  default     = "10.40.0.0/16"
}

variable "az_count" {
  type    = number
  default = 3
}

variable "single_nat_gateway" {
  description = "One NAT for the whole VPC (cheap, staging) vs one per AZ (resilient, prod)"
  type        = bool
}

variable "cluster_version" {
  type    = string
  default = "1.31"
}

variable "admin_cidrs" {
  description = "Networks allowed to reach the EKS public endpoint (office/VPN egress). Empty = private only."
  type        = list(string)
  default     = []
}

variable "system_node_instance_types" {
  description = "Graviton (arm64): ~20% cheaper per vCPU than x86 for this workload; images are multi-arch"
  type        = list(string)
  default     = ["m7g.large"]
}

variable "db_instance_class" {
  type = string
}

variable "db_multi_az" {
  type = bool
}

variable "cache_node_type" {
  type    = string
  default = "cache.t4g.small"
}

variable "evidence_lock_mode" {
  description = "COMPLIANCE in prod (irreversible), GOVERNANCE in staging"
  type        = string
}

variable "evidence_retention_days" {
  type = number
}

variable "enable_dr" {
  description = "Replicate evidence and DB backups to the DR region (ap-south-2)"
  type        = bool
  default     = false
}

variable "github_repository" {
  description = "owner/repo allowed to push images through GitHub OIDC"
  type        = string
  default     = "rokadepiyush49-rgb/HackMatrix-Hackathon"
}

variable "monthly_budget_usd" {
  type = number
}

variable "budget_alert_emails" {
  type    = list(string)
  default = []
}

variable "allowed_countries" {
  description = "WAF geo allow-list for the investigator app (bank staff are in India). Empty = no geo rule."
  type        = list(string)
  default     = ["IN"]
}
