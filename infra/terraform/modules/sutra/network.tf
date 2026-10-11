# Three tiers per AZ: public (ALB, NAT), private (EKS nodes/pods), database (RDS, ElastiCache — no route
# to the internet at all). VPC endpoints keep S3/ECR/Secrets Manager traffic off the NAT and the internet.
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.16"

  name = local.name
  cidr = var.vpc_cidr
  azs  = local.azs

  public_subnets   = [for i, _ in local.azs : cidrsubnet(var.vpc_cidr, 8, i)]
  private_subnets  = [for i, _ in local.azs : cidrsubnet(var.vpc_cidr, 4, i + 1)] # /20s: pods take VPC IPs
  database_subnets = [for i, _ in local.azs : cidrsubnet(var.vpc_cidr, 8, i + 100)]

  create_database_subnet_group       = true
  create_database_subnet_route_table = true # no NAT route: data tier cannot reach the internet

  enable_nat_gateway     = true
  single_nat_gateway     = var.single_nat_gateway
  one_nat_gateway_per_az = !var.single_nat_gateway

  enable_dns_hostnames = true
  enable_dns_support   = true

  enable_flow_log                                 = true
  create_flow_log_cloudwatch_log_group            = true
  create_flow_log_cloudwatch_iam_role             = true
  flow_log_cloudwatch_log_group_retention_in_days = 365

  public_subnet_tags  = { "kubernetes.io/role/elb" = 1 }
  private_subnet_tags = { "kubernetes.io/role/internal-elb" = 1, "karpenter.sh/discovery" = local.name }

  tags = local.tags
}

resource "aws_security_group" "endpoints" {
  name_prefix = "${local.name}-vpce-"
  description = "Interface VPC endpoints: HTTPS from inside the VPC only"
  vpc_id      = module.vpc.vpc_id
  ingress {
    description = "HTTPS from VPC"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }
  tags = local.tags
}

module "endpoints" {
  source  = "terraform-aws-modules/vpc/aws//modules/vpc-endpoints"
  version = "~> 5.16"

  vpc_id             = module.vpc.vpc_id
  security_group_ids = [aws_security_group.endpoints.id]

  endpoints = merge(
    { s3 = { service = "s3", service_type = "Gateway", route_table_ids = module.vpc.private_route_table_ids } },
    { for svc in ["ecr.api", "ecr.dkr", "sts", "secretsmanager", "kms", "logs", "eks-auth"] :
    replace(svc, ".", "_") => { service = svc, private_dns_enabled = true, subnet_ids = module.vpc.private_subnets } }
  )
  tags = local.tags
}
