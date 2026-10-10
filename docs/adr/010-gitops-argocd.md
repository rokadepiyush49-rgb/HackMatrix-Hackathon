# 010 — GitOps with Argo CD; progressive delivery with Argo Rollouts

**Context.** In a regulated environment every production change needs an author, a reviewer and a
record. Push-based deploys (CI running `helm upgrade`) give CI cluster-admin credentials and let
manual hot-fixes drift silently from what is in Git.

**Decision.**
- Argo CD in the cluster pulls `deploy/helm/sutra` from `main`. **Staging** syncs automatically
  with self-heal; **prod** syncs only when a release manager approves (AppProject role).
- The release workflow never touches the cluster: it opens a PR that pins new image digests in
  `values-<env>.yaml`. Merging that PR *is* the deployment.
- Prod runs the API as an Argo Rollouts **canary** (10% → 50% → 100% with pauses); aborting
  returns all traffic to the stable ReplicaSet in seconds.
- Platform add-ons (load balancer controller, External Secrets, Kyverno, Rollouts, Karpenter) are
  installed by an Argo CD ApplicationSet with pinned chart versions.

**Consequences.** Git history is the change log auditors ask for. Rollback is `git revert` of the
release PR. CI holds no cluster credentials.
