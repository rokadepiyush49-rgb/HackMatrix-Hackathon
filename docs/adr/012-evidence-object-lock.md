# 012 — Evidence packs in S3 Object Lock (WORM)

**Context.** An evidence pack may end up before an adjudicating authority. "The database row says
the hash was X" is weak if the same administrator could change both the file and the row.

**Decision.** Packs (PDF, JSON, CSV) are written through `app.core.storage` to S3 with Object Lock
in **COMPLIANCE** mode and a per-object retention of 1,825 days (PMLA Rule 10's five years). Until
then nobody — not an admin, not the AWS root user — can overwrite or delete them. SHA-256 per file
and per evidence item is stored in Postgres; `/packs/{id}/verify` recomputes and compares.
Encryption uses a dedicated KMS key; the bucket policy denies non-TLS access and any other key.

**Consequences.** Mistakes can't be deleted, only superseded by a new pack — which is the point.
Staging uses GOVERNANCE mode with 1-day retention so test buckets can be removed. The app refuses
to start in prod unless storage is S3 in COMPLIANCE mode.
