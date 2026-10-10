# Cost estimate (ap-south-1, on-demand, monthly, USD — indicative)

| Component | Staging | Production | Notes |
|---|---|---|---|
| EKS control plane | 73 | 73 | per cluster |
| Nodes (Graviton m7g, Karpenter) | ~120 | ~450 | prod: 3 AZs, headroom for detection bursts; Savings Plans cut ~30 % |
| RDS PostgreSQL | ~70 (t4g.medium, single-AZ) | ~420 (r7g.large, Multi-AZ) | + storage and PI |
| ElastiCache Valkey | ~25 | ~50 | t4g.small, 1 vs 2 nodes |
| NAT gateways | ~35 (1) | ~105 (3) | VPC endpoints keep image pulls off NAT |
| VPC interface endpoints | ~45 | ~45 | 7 endpoints × 2–3 AZs |
| ALB + WAF | ~30 | ~45 | |
| S3 evidence + replication | < 5 | ~15 | |
| CloudWatch, AMP, X-Ray, KMS, Secrets | ~40 | ~120 | log retention drives most of it |
| **Total** | **~450** | **~1,350** | Budgets alert at 80 % actual and 100 % forecast |

Biggest levers: Compute Savings Plans, Graviton everywhere, shorter log retention in staging,
and stopping staging out of hours (Karpenter scales nodes to zero when the namespace is idle).
