# 020 — Context budgets: batch on natural boundaries, never truncate, say what was not reviewed

**Context.** An agent's evidence must fit its model's context window, alongside the system rules, the
task, the schema and the reply. The largest queued case today has 33 evidence items (≈3.5K characters of
summaries), but a mule ring or a long structuring pattern can be ten times that. The brief rules out
silent truncation and case-specific limits.

**Decision.**
- **Budget per call:** `min(SUTRA_COUNCIL_CALL_INPUT_TOKENS, window × SUTRA_COUNCIL_CONTEXT_FRACTION −
  max output tokens)`. The window comes from a table of verified Groq model limits, or from
  `GROQ_CONTEXT_WINDOW` for any other model (32,768 when unknown). The per-call cap (default 6,000) also
  keeps a call under a free-tier tokens-per-minute limit.
- **Token estimate:** a pessimistic bytes-per-token figure, corrected after every call from the provider's
  real prompt-token count. It only ever becomes more pessimistic.
- **Evidence slices:** each agent sees only its slice, chosen by evidence kind. Everything reaches at least
  one agent, and the defence sees all of it.
- **Batching:** items are packed in order into batches that fit, each item whole. The agent sees later
  parts with its own validated claims so far, and may cite anything it has already been shown.
- **Oversized items:** an item too large for any call on its own is listed as unreviewed, never cut.
- **Coverage:** every result carries the counts reviewed and total, and the list of unreviewed IDs. If
  anything was not reviewed, or an agent fell back, the outcome begins "Partial review — n of m evidence
  items reviewed by agents … no conclusion is issued on what was not reviewed".
- **Stopping cleanly:** budgets (calls, tokens, deadline) stop the council between calls. Validated claims
  are kept, and skipped steps are recorded in the trace.

**Consequences.** Validation: `test_large_investigations_are_batched_and_nothing_is_silently_dropped`
(308 evidence items, money agent in several parts, reviewed + unreviewed = total);
`test_an_item_too_large_for_any_call_is_reported_not_truncated`; and
`test_call_budget_stops_cleanly_and_the_outcome_says_partial`. **Not implemented:** resuming a council
from a checkpoint after a process restart. A run interrupted by a restart is marked FAILED and the
council is convened again. Numeric aggregation (totals, scores) is never asked of the model.
