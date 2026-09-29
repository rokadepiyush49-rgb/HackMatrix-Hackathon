"""Ask SUTRA — evidence-grounded answers, never free-form accusation.

Two engines produce the same structure (sentences, each citing evidence codes):
  • Claude (when ANTHROPIC_API_KEY is set) with JSON-schema structured output;
  • a deterministic engine that composes sentences straight from the argument.
Both pass through the same cite-or-drop verifier: a sentence survives only if every
evidence code exists and every figure, time and ID it states appears in what it cites.
The LLM never creates, scores or closes an alert (docs/adr/004).
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field

from app.core.config import get_settings

SYSTEM = """You are SUTRA's investigation assistant for a bank's fraud and vigilance team.
You answer ONLY from the case evidence supplied as JSON. Rules:
- Every sentence must cite one or more evidence codes (e.g. "EV-104") that support it.
- Copy figures, times and IDs exactly as they appear in the cited evidence.
- If the evidence does not answer the question, say so in one sentence citing the closest items.
- Describe what records show. Never state that a named person committed a crime; attribution
  stays open until forensics confirm who used the credentials.
- Plain, specific English. No preamble."""

SCHEMA = {
    "type": "object",
    "properties": {
        "sentences": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["text", "evidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["sentences"],
    "additionalProperties": False,
}

SUGGESTED = {
    "INSIDER_ATO": ["What happened before the payment?", "Who else is connected to this employee?",
                    "What argues against this?", "What would have stopped this?", "Draft the STR grounds"],
    "EXTERNAL_ATO": ["What happened before the payment?", "What argues against this?", "Draft the STR grounds"],
    "MULE_FACTORY": ["Who opened these accounts?", "Which accounts share devices?", "What argues against this?"],
    "CIRCULAR_FLOW": ["How did the money move?", "What argues against this?", "Draft the STR grounds"],
    "STRUCTURING": ["How were the deposits split?", "What argues against this?", "Draft the STR grounds"],
}


@dataclass
class Sentence:
    text: str
    evidence: list[str]
    reason: str | None = None


@dataclass
class Answer:
    mode: str
    model: str | None
    question: str
    sentences: list[Sentence]
    dropped: list[Sentence] = field(default_factory=list)
    confidence: str = "LOW"
    suggested: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


# ── verifier ───────────────────────────────────────────────────────────────

_FIGURES = [
    re.compile(r"₹\s?[\d,]+(?:\.\d+)?\s?(?:L|lakh|Cr)?"),
    re.compile(r"\b\d{1,2}:\d{2}\b"),
    re.compile(r"\b(?:EMP|A|C|X|D|S|SR|REQ|LAP|EV)-[\w]+\b"),
]


def _norm(s: str) -> str:
    return re.sub(r"[\s,]", "", s).replace("lakh", "L").rstrip(".")


def _rupee_variants(tok: str) -> set[str]:
    t = _norm(tok)
    out = {t}
    m = re.match(r"₹([\d.]+)L$", t)
    if m:
        v = float(m.group(1))
        out |= {f"₹{v:.2f}L", f"₹{v:g}L", f"₹{v * 1e5:,.0f}".replace(",", "")}
    return out


def verify(sentences: list[Sentence], evidence: dict[str, dict], extra_text: str = "") -> tuple[list[Sentence], list[Sentence]]:
    kept, dropped = [], []
    for s in sentences:
        codes = [c for c in s.evidence if c]
        missing = [c for c in codes if c not in evidence]
        if not codes:
            s.reason = "no evidence cited"
            dropped.append(s)
            continue
        if missing:
            s.reason = f"cites unknown evidence {', '.join(missing)}"
            dropped.append(s)
            continue
        cited = " ".join(f"{evidence[c]['summary']} {json.dumps(evidence[c].get('facts', {}), default=str)} "
                         f"{' '.join(evidence[c].get('entities', []))}" for c in codes) + " " + extra_text
        haystack = _norm(cited)
        bad = []
        for rx in _FIGURES:
            for tok in rx.findall(s.text):
                if tok.startswith("EV-"):
                    if tok not in codes:
                        bad.append(tok)
                    continue
                variants = _rupee_variants(tok) if tok.startswith("₹") else {_norm(tok)}
                if not any(v in haystack for v in variants):
                    bad.append(tok)
        if bad:
            s.reason = f"states {', '.join(dict.fromkeys(bad))} not found in the cited evidence"
            dropped.append(s)
        else:
            kept.append(s)
    return kept, dropped


def _confidence(kept: list[Sentence], evidence: dict[str, dict]) -> str:
    cited = {c for s in kept for c in s.evidence}
    record = [evidence[c] for c in cited if evidence[c]["reliability"] in ("A", "B")]
    systems = {e["source_system"] for e in record}
    if len(record) >= 2 and len(systems) >= 2:
        return "HIGH"
    if record:
        return "MEDIUM"
    return "LOW"


# ── deterministic engine ───────────────────────────────────────────────────


def _link_codes(ctx: dict, *codes: str) -> list[str]:
    out = []
    for lk in ctx["links"]:
        if lk["code"] in codes:
            out += lk["evidence_codes"]
    return list(dict.fromkeys(out))


def _codes_of(ctx: dict, *kinds: str) -> list[str]:
    return [e["code"] for e in ctx["evidence"] if e["kind"] in kinds]


def _deterministic(ctx: dict, question: str) -> list[Sentence]:
    q = question.lower()
    arg, links = ctx["argument"], ctx["links"]
    ev = {e["code"]: e for e in ctx["evidence"]}
    out: list[Sentence] = []

    def from_evidence(codes: list[str], limit: int = 6) -> None:
        for c in codes[:limit]:
            if c in ev:
                out.append(Sentence(ev[c]["summary"].rstrip(".") + ".", [c]))

    if any(k in q for k in ("before", "what happened", "sequence", "timeline", "how did the money")):
        for lk in links:
            if lk["evidence_codes"]:
                primary = next((c for c in lk["evidence_codes"] if ev.get(c, {}).get("reliability") in ("A", "B")),
                               lk["evidence_codes"][0])
                out.append(Sentence(f"{lk['t'][11:16]} — {lk['title']}: {ev[primary]['summary'].rstrip('.')}.", [primary]))
    elif any(k in q for k in ("who else", "connected", "network", "opened these", "share devices", "approve")):
        from_evidence(_codes_of(ctx, "ACCOUNT_OPENING", "ENTITY_MATCH", "G4_FACTORY", "M6_MULE"), 8)
    elif any(k in q for k in ("against", "defence", "defense", "innocent", "legitimate", "benign")):
        for r in arg["rebuttals"]:
            codes = [c for c in r["codes"] if c in ev] or [e["code"] for e in ctx["evidence"] if e["rebuts"]][:1]
            if codes:
                out.append(Sentence(f"{r['hypothesis']} — {r['status']}: {r['note']}.", codes))
        from_evidence([e["code"] for e in ctx["evidence"] if e["rebuts"]], 3)
    elif any(k in q for k in ("stop", "prevent", "control")):
        mend = ctx.get("mend")
        if mend and mend.get("recommended"):
            rec = mend["recommended"]
            codes = _link_codes(ctx, "E0") or _link_codes(ctx, "E3") or _link_codes(ctx, "E5")
            out.append(Sentence(f"{rec['name']}: {rec['why'].lower()} — it breaks the chain with "
                                f"{rec['legit_ops_affected']} legitimate operations affected in the last 90 days.", codes[:2]))
        from_evidence(_link_codes(ctx, "E0", "E3"), 3)
    else:  # why / summary
        for d in [d for d in ctx["dims"] if d["level"] == "HIGH"]:
            codes = [c for c in d["supporting"] if c in ev][:3]
            if codes:
                out.append(Sentence(f"{d['label']} is High: {d['summary']}.", codes))
        rebut = [e["code"] for e in ctx["evidence"] if e["rebuts"]]
        if rebut:
            out.append(Sentence(f"Against the claim: {ev[rebut[0]]['summary'].rstrip('.')}.", [rebut[0]]))
    return out


# ── Claude engine ──────────────────────────────────────────────────────────


def _claude(ctx: dict, question: str) -> tuple[list[Sentence], str] | None:
    s = get_settings()
    if not s.llm_enabled or not s.anthropic_api_key:
        return None
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=s.anthropic_api_key, max_retries=2, timeout=90.0)
        payload = {
            "claim": ctx["argument"]["claim"],
            "chain": [{k: lk[k] for k in ("code", "t", "title", "detail", "evidence_codes")} for lk in ctx["links"]],
            "dimensions": [{k: d[k] for k in ("label", "level", "summary", "supporting", "contradicting")} for d in ctx["dims"]],
            "defence": ctx["argument"]["rebuttals"],
            "missing_evidence": ctx["argument"]["missing"],
            "evidence": [{k: e[k] for k in ("code", "summary", "source_system", "reliability", "credibility")}
                         for e in ctx["evidence"]],
        }
        resp = client.beta.messages.create(
            model=s.llm_model,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
            system=SYSTEM,
            messages=[{"role": "user", "content": f"CASE EVIDENCE (JSON):\n{json.dumps(payload, default=str)}\n\n"
                                                  f"QUESTION: {question}"}],
        )
        if resp.stop_reason == "refusal":
            return None
        text = next((b.text for b in resp.content if b.type == "text"), "")
        data = json.loads(text)
        return [Sentence(x["text"], list(x["evidence"])) for x in data.get("sentences", [])], resp.model
    except Exception:  # network, auth, rate limit, malformed output → deterministic engine
        return None


def ask(ctx: dict, question: str) -> Answer:
    evidence = {e["code"]: e for e in ctx["evidence"]}
    extra = " ".join(f"{lk['t']} {lk['title']} {lk['detail']}" for lk in ctx["links"])
    got = _claude(ctx, question)
    mode, model = ("llm", got[1]) if got else ("deterministic", None)
    sentences = got[0] if got else _deterministic(ctx, question)
    kept, dropped = verify(sentences, evidence, extra)
    if not kept:
        kept = [Sentence("The case evidence does not answer this directly; see the chain and the defence column.",
                         [ctx["evidence"][0]["code"]] if ctx["evidence"] else [])]
    return Answer(mode, model, question, kept, dropped, _confidence(kept, evidence),
                  SUGGESTED.get(ctx["argument"]["typology"], []))


def str_draft(ctx: dict) -> dict:
    """FIU-IND style 'grounds of suspicion', every line cited."""
    arg = ctx["argument"]
    ev = {e["code"]: e for e in ctx["evidence"]}
    sections = []
    subj = [e for e in ctx["evidence"] if e["kind"] in ("ACCESS", "STATE_CHANGE", "ENTITLEMENT")][:3]
    sections.append({"title": "1. Subject accounts and parties",
                     "sentences": [asdict(Sentence(e["summary"], [e["code"]])) for e in subj]})
    seq = ask(ctx, "What happened before the payment?")
    sections.append({"title": "2. Sequence of events", "sentences": [asdict(s) for s in seq.sentences]})
    why = ask(ctx, "Why was this flagged?")
    sections.append({"title": "3. Grounds of suspicion", "sentences": [asdict(s) for s in why.sentences]})
    defence = [r for r in arg["rebuttals"]]
    sections.append({"title": "4. Explanations considered", "sentences": [
        asdict(Sentence(f"{r['hypothesis']}: {r['status']} — {r['note']}", r["codes"])) for r in defence]})
    sections.append({"title": "5. Evidence attached", "sentences": [
        asdict(Sentence(f"{c} · {ev[c]['source_system']} · grade {ev[c]['reliability']}{ev[c]['credibility']} · sha256 {ev[c]['sha256'][:12]}…", [c]))
        for c in list(ev)[:12]]})
    return {"title": f"Draft STR — {arg['claim']}", "sections": sections,
            "note": "Draft for the Principal Officer's review. Attribution to a person is not asserted.",
            "mode": seq.mode, "dropped": [asdict(s) for s in seq.dropped + why.dropped]}
