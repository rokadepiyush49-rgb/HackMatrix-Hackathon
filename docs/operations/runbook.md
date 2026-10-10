# Runbook

Operational procedures for SUTRA on AWS. Commands assume you are authenticated to the right AWS
account (`aws sts get-caller-identity`) and to the cluster (`aws eks update-kubeconfig --name sutra-<env> --region ap-south-1`).

## 1. First-time setup of an AWS account

```bash
# 1. State bucket (once per account)
terraform -chdir=infra/terraform/bootstrap init && terraform -chdir=infra/terraform/bootstrap apply
# 2. Put the printed bucket name into infra/terraform/envs/<env>/main.tf (backend "s3" → bucket)
# 3. The environment
terraform -chdir=infra/terraform/envs/staging init
terraform -chdir=infra/terraform/envs/staging plan -out tfplan
terraform -chdir=infra/terraform/envs/staging apply tfplan
```

Record the outputs: `github_release_role_arn` goes into the GitHub repository variable
`AWS_RELEASE_ROLE_ARN`; `evidence_bucket` and `evidence_kms_key_arn` go into
`deploy/helm/sutra/values-<env>.yaml` (`config.s3Bucket`, `config.s3KmsKeyId`); `waf_acl_arn` and
the ACM certificate ARN go into `ingress`.

## 2. Create the application database role (once per environment)

Terraform generates the `sutra_app` password into the `sutra/<env>/app` secret; the role itself
is created with the RDS-managed master credentials so the app never runs as the master user.

```bash
MASTER=$(aws secretsmanager get-secret-value --secret-id "$(terraform -chdir=infra/terraform/envs/prod output -raw db_master_secret_arn)" --query SecretString --output text)
APP_URL=$(aws secretsmanager get-secret-value --secret-id sutra/prod/app --query SecretString --output text | jq -r .database_url)
# From a pod in the cluster (the database has no public route):
kubectl -n sutra-prod run psql --rm -it --image=postgres:17-alpine --restart=Never -- \
  psql "host=<db_endpoint> user=sutra_admin dbname=sutra sslmode=require" \
  -c "CREATE ROLE sutra_app LOGIN PASSWORD '<from APP_URL>'; GRANT ALL ON DATABASE sutra TO sutra_app; ALTER SCHEMA public OWNER TO sutra_app;"
```

## 3. Install the platform and the app (GitOps)

```bash
kubectl apply -n argocd -f deploy/argocd/platform.yaml     # LBC, External Secrets, Kyverno, Rollouts, Karpenter
kubectl apply -f deploy/policies/kyverno.yaml              # after Kyverno is healthy
kubectl apply -n argocd -f deploy/argocd/project.yaml
kubectl apply -n argocd -f deploy/argocd/sutra-staging.yaml
kubectl apply -n argocd -f deploy/argocd/sutra-prod.yaml
```

A `ClusterSecretStore` named `aws-secrets-manager` (provider `aws`, service `SecretsManager`,
region `ap-south-1`, auth via Pod Identity) must exist for External Secrets.

## 4. Releasing

| Step | How |
|---|---|
| Staging | Merge to `main` → the release workflow opens "release(staging)" PR → merge → Argo CD syncs |
| Production | Tag `vX.Y.Z` on the commit that passed staging → "release(prod)" PR → merge → release manager presses **Sync** → canary |
| Watch the canary | `kubectl argo rollouts get rollout sutra-api -n sutra-prod --watch` |
| Promote early | `kubectl argo rollouts promote sutra-api -n sutra-prod` |

## 5. Rolling back

- **During a canary:** `kubectl argo rollouts abort sutra-api -n sutra-prod` — traffic returns to stable immediately.
- **After a release:** revert the release PR (`git revert`), merge, sync. Images are immutable and still in ECR (last 50 kept).
- **Database:** migrations are expand-then-contract, so the previous version runs against the new
  schema. For data corruption, restore to a new instance with point-in-time recovery (§7) — never in place.

## 6. Run detection now

```bash
kubectl -n sutra-prod create job --from=cronjob/sutra-detect detect-$(date +%s)
kubectl -n sutra-prod logs -f job/detect-<id>
```

## 7. Incident playbooks

| Symptom | First checks | Likely fix |
|---|---|---|
| Pods not Ready | `kubectl describe pod` → readiness `/health/ready` body says which check fails | DB: security group / RDS status; models: image built without the models stage |
| 5xx spike | CloudWatch Container Insights; search logs by `request_id`; X-Ray trace | Roll back (§5) if it started with a release |
| Pods rejected at admission | `kubectl get events` → Kyverno message | Image not signed by the release workflow, or `:latest` tag — redeploy via the pipeline |
| Secrets missing | `kubectl get externalsecret -n sutra-prod` status | ClusterSecretStore auth (Pod Identity association) or secret name |
| Evidence write fails (AccessDenied) | API logs around `pack.create` | Bucket policy requires the evidence KMS key: set `config.s3KmsKeyId` to the key **ARN** |
| WAF blocking investigators | WAF logs (`aws-waf-logs-sutra-<env>`) → rule name | Tune the managed rule (count mode) or the geo allow-list |
| Detection job slow / OOMKilled | `kubectl top pod`, job events | Raise `detection.resources`; Karpenter supplies a larger node |

## 8. Point-in-time database restore

```bash
aws rds restore-db-instance-to-point-in-time \
  --source-db-instance-identifier sutra-prod \
  --target-db-instance-identifier sutra-prod-restore-$(date +%Y%m%d%H%M) \
  --restore-time 2026-09-21T16:30:00Z --db-subnet-group-name sutra-prod --multi-az
```

Point the `database_url` in Secrets Manager at the restored instance once verified; External
Secrets propagates it within the refresh interval (restart the API pods to pick it up at once).
