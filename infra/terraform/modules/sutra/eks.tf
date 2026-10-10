# EKS (Kubernetes) rather than ECS: SUTRA is several cooperating workloads (API, BFF, migrations,
# scheduled detection) that need network policies, admission control (Kyverno), canaries (Argo
# Rollouts) and GitOps (Argo CD) — all Kubernetes-native and portable to any bank's on-prem cluster.
module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 21.26"

  cluster_name    = local.name
  cluster_version = var.cluster_version

  vpc_id                   = module.vpc.vpc_id
  subnet_ids               = module.vpc.private_subnets
  control_plane_subnet_ids = module.vpc.private_subnets

  cluster_endpoint_private_access      = true
  cluster_endpoint_public_access       = length(var.admin_cidrs) > 0
  cluster_endpoint_public_access_cidrs = var.admin_cidrs

  authentication_mode                      = "API" # access entries, not the aws-auth ConfigMap
  enable_cluster_creator_admin_permissions = true

  # Kubernetes Secrets are envelope-encrypted with a KMS key the module creates.
  cluster_encryption_config = { resources = ["secrets"] }
  cluster_enabled_log_types = ["api", "audit", "authenticator", "controllerManager", "scheduler"]

  cluster_addons = {
    coredns                = {}
    kube-proxy             = {}
    eks-pod-identity-agent = { before_compute = true }
    vpc-cni = {
      before_compute = true
      # Native NetworkPolicy enforcement in the VPC CNI (eBPF) — no Calico needed.
      configuration_values = jsonencode({ enableNetworkPolicy = "true" })
    }
    aws-ebs-csi-driver                = {}
    amazon-cloudwatch-observability   = {} # Container Insights, logs to CloudWatch
  }

  # A small fixed pool for cluster add-ons; Karpenter provisions application capacity on demand.
  eks_managed_node_groups = {
    system = {
      ami_type       = "AL2023_ARM_64_STANDARD"
      instance_types = var.system_node_instance_types
      min_size       = 2
      max_size       = 4
      desired_size   = 2
      labels         = { "sutra.io/pool" = "system" }
      metadata_options = {
        http_tokens                 = "required" # IMDSv2 only
        http_put_response_hop_limit = 1          # pods cannot reach node credentials
      }
    }
  }

  node_security_group_tags = { "karpenter.sh/discovery" = local.name }
  tags                     = local.tags
}

module "karpenter" {
  source  = "terraform-aws-modules/eks/aws//modules/karpenter"
  version = "~> 21.26"

  cluster_name                    = module.eks.cluster_name
  enable_v1_permissions           = true
  enable_pod_identity             = true
  create_pod_identity_association = true
  node_iam_role_additional_policies = {
    AmazonSSMManagedInstanceCore = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
  }
  tags = local.tags
}
