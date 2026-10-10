# Disaster recovery

| Target | Value | How |
|---|---|---|
| **RPO** (data loss) | ≤ 5 minutes | RDS Multi-AZ (synchronous standby) within the region; automated backups with PITR, replicated to ap-south-2 |
| **RTO** (AZ failure) | ≤ 2 minutes, automatic | RDS/Valkey Multi-AZ failover; pods spread across 3 AZs with PDBs; ALB health checks |
| **RTO** (region failure) | ≤ 4 hours | Apply `envs/prod` with the `ap-south-2` provider, restore the latest replicated backup, point Argo CD at the new cluster |
| **Evidence** | 0 loss | Object Lock + versioning in ap-south-1, replicated (still locked) to ap-south-2 |

Both regions are in India, so DR satisfies RBI data localisation ([ADR 011](../adr/011-region-and-residency.md)).

## Drills

- **Quarterly:** restore the production snapshot to a scratch instance; run `pytest backend/tests/test_api.py` against it.
- **Twice a year:** full region failover rehearsal in staging, timed against the RTO above.
- **Every release:** Argo Rollouts canary abort is exercised automatically when analysis fails.
