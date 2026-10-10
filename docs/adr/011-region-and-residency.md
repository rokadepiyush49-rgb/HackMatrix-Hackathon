# 011 — Mumbai primary, Hyderabad DR: data stays in India

**Context.** RBI's directive on *Storage of Payment System Data* (2018) requires payment data to be
stored only in India. SUTRA processes transactions, so its database, evidence and backups fall
under it — including disaster-recovery copies.

**Decision.** Primary region **ap-south-1 (Mumbai)**. DR region **ap-south-2 (Hyderabad)**:
RDS automated-backup replication and S3 cross-region replication of the evidence vault (with its
own KMS key and Object Lock). No data store, backup or log bucket is created outside India.
LLM narration is **off by default in production**: Claude in Amazon Bedrock offers only *global* routing
from ap-south-1/ap-south-2 today, so inference could run outside India — see [ADR 015](015-llm-residency.md).

**Consequences.** Some newer instance types and services arrive later in these regions. RPO is
minutes (backup replication), RTO is the time to apply Terraform in ap-south-2 and restore — see
`docs/operations/disaster-recovery.md`.
