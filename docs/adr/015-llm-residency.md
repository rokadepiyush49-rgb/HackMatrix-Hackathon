# 015 — LLM narration is off in production until inference can stay in India

**Context.** Ask SUTRA and the STR draft send case evidence — transaction amounts, times,
pseudonymous IDs, evidence summaries — to Claude. RBI's payment-data localisation directive
([ADR 011](011-region-and-residency.md)) requires payment data to be stored in India, and a bank's
risk team will treat processing location as part of that. Claude in Amazon Bedrock is reachable
from ap-south-1 (Mumbai) and ap-south-2 (Hyderabad), but only through the **global** endpoint,
which routes requests to whichever region has capacity. There is no India-only (regional or
in-region) option today.

**Decision.**
- Production ships with `config.llmEnabled: false`. The deterministic engine answers every
  question from the evidence book; the cite-or-drop verifier applies exactly the same.
- Staging (synthetic data only) runs Claude so the narration can be evaluated.
- The engine supports both providers (`anthropic`, `bedrock`); switching a bank's prod on is a
  values change once its compliance team accepts the routing, or once an India-resident
  inference option exists. The IAM permission (`bedrock-mantle:CreateInference`) is already
  scoped to the API/jobs service account only.
- Whatever the setting, the LLM never creates, scores or closes an alert ([ADR 004](004-llm-boundary.md)).

**Consequences.** Production answers are plainer but fully cited and reproducible. Turning the
LLM on is a reviewed, one-line GitOps change with an audit trail — not a code change.
