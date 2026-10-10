terraform {
  required_version = ">= 1.10" # S3 backend native locking (use_lockfile) — no DynamoDB lock table
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 5.80", configuration_aliases = [aws.dr] }
    random = { source = "hashicorp/random", version = "~> 3.6" }
  }
}
