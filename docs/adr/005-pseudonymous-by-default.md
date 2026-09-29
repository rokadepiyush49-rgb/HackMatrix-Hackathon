# 005 — Staff pseudonymous by default

**Context.** Insider-risk monitoring can become surveillance. Premature naming harms
honest employees and can prejudice an investigation.

**Decision.** Employees appear as role + branch + pseudonymous ID (e.g. `EMP-0417`).
Revealing a name requires an unmask request with a reason, approved by a second person,
and expires. Every unmask is written to the hash-chained audit log.

**Consequences.** Investigations proceed on evidence rather than identity; audit can show
who learned whose name, when and why.
