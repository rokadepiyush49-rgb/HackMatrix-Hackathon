# 004 — The LLM writes language only

**Context.** Opaque AI decisions are exactly what the problem statement forbids.

**Decision.** The LLM never creates, scores, prioritises or closes an alert. It receives
the argument JSON (pseudonymised evidence with IDs) and returns sentences, each tagged
with the evidence IDs it relies on. A verifier drops any sentence whose IDs do not exist
or whose numbers/dates do not appear in the cited evidence. Dropped sentences are logged
and shown. Without an API key — or when disabled — deterministic templates produce the
same structure.

**Consequences.** The demo works offline. Every sentence an investigator reads is
traceable to a source record. LLM output is graded D (never sole grounds).
