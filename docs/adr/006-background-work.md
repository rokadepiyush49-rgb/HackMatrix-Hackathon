# 006 — Background work in the MVP

**Context.** The blueprint's scale architecture uses a job queue (ARQ) and, at 100M
transactions/day, a stream processor. At demo scale the full pipeline runs in seconds.

**Decision.** The detection pipeline runs as a CLI (`python -m app.cli detect`) and can be
re-triggered through the API. Evidence packs are generated synchronously. Live "replay" of
the evening's events is served over Server-Sent Events from the stored, time-ordered
signals at 60× speed and is clearly labelled as a replay. Evidence packs are stored on local
disk (`SUTRA_STORAGE_BACKEND=local`), behind a storage interface that has an S3 backend.

**Consequences.** Fewer moving parts to run on a laptop with no Docker. Moving to ARQ is a
drop-in change at the `app/workers` boundary; nothing in the domain modules changes.
