# 019 — Investigation Council agents on Groq, inside a harness that decides what counts

**Context.** The Investigation Council (`council/engine.py`) was a scripted debate. Every position,
challenge and ruling was a Python template chosen by typology, and some lines hard-coded facts from the
demo world (a laptop ID, a login time). It never called a model. The brief asks for real LLM agents
through Groq, without wrapping the script in a prompt and without letting a model decide what is true.
ADR 004 still holds: the LLM writes language only.

**Options.** (a) One LLM call that writes the whole debate — rejected: no independent positions, no way
to enforce per-agent evidence or tools. (b) A general agent framework (LangGraph, CrewAI) — rejected for
now: another dependency, and none of them enforce evidence grounding; the controls would still be ours.
(c) Agents as narrow LLM calls on a shared blackboard (the existing `Council` object), with every rule
enforced in code — chosen.

**Decision.**
- **LLM agents:** chain, money, insider, defence, prosecution. **Hybrid:** alibi (interprets Alibi's
  deterministic verdicts), control (interprets Mend's simulation), moderator (writes the ruling text).
  **Deterministic:** the evidence agent (grades, systems, gaps), record retrieval, claim bookkeeping, and
  the outcome, consensus and dissent (`Council._conclude`).
- **Rounds:** 1 independent positions (in parallel) → 2 record retrieval, the defence's challenges and the
  challenged agents' responses → 3 prosecution synthesis and evidence gaps → 4 ruling.
- **Harness** (`council/harness.py`), enforced outside the model:
  - Typed outputs with extra fields refused, and strict JSON-schema decoding. Evidence IDs and record
    names are enums, so an agent cannot emit an ID it was not shown.
  - Every claim is checked: an unknown or unauthorised ID drops it. Figures, times, IDs and scores in the
    text must appear in the cited records (the cite-or-drop verifier). Statements that a person committed
    a crime are dropped.
  - Status rules: SUPPORTED needs an A/B-graded record; model-only or hypothesis claims become CONTESTED.
    A response can raise a status only with a new A/B record. Claims about who acted stay CONTESTED,
    because endpoint telemetry and CCTV are not ingested.
  - Agents can only *ask* for records on their allowlist; the harness retrieves them.
  - Budgets on calls, tokens and wall-clock per investigation. Identical calls are served from cache, and
    a third repeat is refused (loop detection). One repair attempt on invalid output.
  - Case records go in a separate JSON block labelled as untrusted data; the rules live only in the
    system message.
- **Groq client** (`council/llm.py`): standard library only. Bounded retries for 429 (honouring
  `retry-after`), 5xx, timeouts and network errors, never past the deadline. Errors are classified.
  The key never appears in logs, errors, traces or responses.
- **Model:** `openai/gpt-oss-120b` (Groq production model, 131,072-token window, strict structured
  outputs; checked on console.groq.com on 10 Oct 2026), with `reasoning_effort=low` and
  `include_reasoning=false`. Configurable via `GROQ_MODEL`.
- **Fallback:** an agent whose calls fail is replaced by its deterministic part, recorded in the trace.
  If no call succeeds, the result is the deterministic council, labelled as a fallback. Without a key,
  the council is deterministic, as before.
- **Persistence:** runs are saved in `council_run` with engine, model, prompt version, usage, coverage
  and trace. A run is marked stale when the case has been revised since (ADR 018).

**Consequences.** Every agent claim on screen is labelled by kind (record, model output, inference,
hypothesis) and by engine, and the harness trace lists every dropped or downgraded claim with its reason.
Validation: `backend/tests/test_council_agents.py` (20 tests against a scripted Groq fake) covers
fabricated IDs, unsupported figures, accusations, model-only claims, prompt injection, rate limits, auth
failure, budget exhaustion, batching and key non-leakage. **Not verified against live Groq: no API key
was available in this environment.** The listed free-tier limit for `gpt-oss-120b` is 8K tokens per minute,
so a full council (≈10 calls) takes minutes on that tier. Use a paid tier for a live demo, or convene
the council before the session (runs are saved).
