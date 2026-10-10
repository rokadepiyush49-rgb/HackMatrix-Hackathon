# staging environment. Apply from this directory:  terraform init && terraform plan -out tfplan
terraform {
  required_version = ">= 1.10"
  backend "s3" {
    bucket       = "sutra-tfstate-REPLACE_WITH_ACCOUNT_ID" # created by ../../bootstrap
    key          = "staging/terraform.tfstate"
    region       = "ap-south-1"
    encrypt      = true
    use_lockfile = true # S3-native state locking (Terraform >= 1.10)
  }
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 5.80" }
    random = { source = "hashicorp/random", version = "~> 3.6" }
  }
}

# Mumbai: RBI's storage-of-payment-data directive requires payment data to stay in India.
provider "aws" {
  region = "ap-south-1"
  default_tags { tags = { Project = "sutra", Environment = "staging" } }
}

# Hyderabad: the second Indian region, for disaster recovery that still satisfies localisation.
provider "aws" {
  alias  = "dr"
  region = "ap-south-2"
  default_tags { tags = { Project = "sutra", Environment = "staging" } }
}

module "sutra" {
  source    = "../../modules/sutra"
  providers = { aws = aws, aws.dr = aws.dr }

  env                     = "staging"
  single_nat_gateway      = true
  db_instance_class       = "db.t4g.medium"
  db_multi_az             = false
  evidence_lock_mode      = "GOVERNANCE"
  evidence_retention_days = 1
  enable_dr               = false
  monthly_budget_usd      = 600
  admin_cidrs             = var.admin_cidrs
  budget_alert_emails     = var.budget_alert_emails
}

variable "admin_cidrs" {
  type    = list(string)
  default = []
}

variable "budget_alert_emails" {
  type    = list(string)
  default = []
}

output "sutra" {
  value = module.sutra
}
