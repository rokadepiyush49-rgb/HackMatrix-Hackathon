"""The Investigation Council with LLM agents (Groq), inside the harness (app.council.harness).

What the agents do, and what stays deterministic:

  Agent        Engine   Sees                                         May ask for                 Writes
  chain        LLM      chain-link evidence, sessions, access         sessions, approvals, telem.  claims C*
  money        LLM      transfers, payees, graph and mule outputs     kyc, invoices, sof           claims M*
  insider      LLM      access, entitlements, rosters, behaviour      roster, sessions, approvals  claims I*
  alibi        hybrid   Alibi's verdicts (deterministic) + records    roster, calls, tickets       claims A*
  control      hybrid   Mend's control simulation + E0/E3 records     approvals, email             claims K*
  defence      LLM      every record and every claim                  calls, tickets, kyc, …       challenges
  prosecution  LLM      validated claims and what they cite           —                            claims P*
  evidence     determ.  grades, systems, gaps, records not ingested   —                            gaps
  moderator    hybrid   final claims; LLM writes the ruling,          —                            ruling; the
                        the outcome, consensus and dissent are                                      outcome is
                        computed (Council._conclude)                                                computed

Rounds: 1 independent positions (in parallel, within the concurrency limit) → 2 record retrieval, the
defence's challenges and the challenged agents' responses → 3 prosecution synthesis and evidence gaps →
4 ruling. Record requests are executed by the harness against Loom (`Council.request`), never by a model.
A response can lower a claim's status freely but can raise it to SUPPORTED only by citing a new A/B
record. Claims naming who acted stay CONTESTED: endpoint telemetry and CCTV are not ingested.

If an agent's calls fail (provider error, budget, validation), that agent's part of the deterministic
council is used instead and the fallback is recorded in the trace. If no agent call succeeds, the
result is the deterministic council, labelled as a fallback. Evidence no agent reviewed is listed, and
the outcome then says the review is partial instead of stating a conclusion.
"""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict

from app.council.engine import AGENTS, MODERATOR, RECORDS, Council
from app.council.harness import (
    PROMPT_VERSION,
    Budgets,
    ClaimOut,
    DefenceOut,
    Harness,
    PositionOut,
    ResponsesOut,
    RulingOut,
    batches,
    compact,
)
from app.council.llm import GroqClient

AGENT = {a["id"]: a for a in AGENTS} | {"moderator": MODERATOR}
PREFIX = {"chain": "C", "money": "M", "insider": "I", "alibi": "A", "control": "K", "defence": "D", "prosecution": "P"}
ALLOWED_RECORDS = {
    "chain": ["sessions", "approvals", "telemetry"],
    "money": ["kyc", "invoices", "sof"],
    "insider": ["roster", "sessions", "approvals", "telemetry", "cctv"],
    "alibi": ["roster", "calls", "tickets"],
    "control": ["approvals", "email"],
    "defence": ["calls", "tickets", "kyc", "simswap", "invoices", "sof", "telemetry", "cctv"],
}
KINDS = {
    "money": {"TXN", "BENEFICIARY", "M6_MULE", "ACCOUNT_OPENING", "G1_CYCLE", "G2_PASS", "G3_FAN", "G4_FACTORY",
              "G5_SHARED", "R1_STRUCTURING", "STRUCTURING"},
    "insider": {"ACCESS", "ENTITLEMENT", "SESSION", "ROSTER", "HR_RECORD", "ASSET", "M1_RHYTHM", "M2_NAVIGATION",
                "ENTITY_MATCH", "ACCOUNT_OPENING", "G4_FACTORY", "M5_CLASSIFIER"},
    "alibi": {"ALIBI", "ROSTER", "HR_RECORD", "ACCESS"},
    "control": {"ENTITLEMENT", "ACCESS", "STATE_CHANGE"},
}
ROUND1 = ("chain", "money", "insider", "alibi", "control")
ATTRIBUTION = ("performed", "carried out", "made the change", "logged in", "personally", "was at the keyboard", "acted")

TASKS = {
    "chain": "Reconstruct the chain from privilege to access to account change to payment, hop by hop, using the "
             "chain links and records. Say which hops records support, which are missing and how long each took.",
    "money": "Follow the money: payouts, new payees, onward transfers, loops and cash-out. Say what the transfers "
             "show and what a legitimate purpose would need to look like.",
    "insider": "Look for privilege misuse and behavioural deviation by staff: overrides, expired entitlements, "
               "off-roster sessions, unusual navigation, relationships to receiving accounts. Model outputs are "
               "MODEL claims and never stand alone.",
    "alibi": "Look for legitimate reasons behind each staff action: tickets, customer requests, portfolio, queue items, "
             "rosters. Alibi's verdicts are computed by SUTRA; interpret them, do not overrule them.",
    "control": "Identify which control failure enabled the chain and what the control simulation says would have "
               "broken it. Do not invent controls the simulation did not test.",
}


def _slices(case: dict) -> dict[str, list[str]]:
    """Which evidence each round-1 agent and the defence review. Every item reaches at least one agent."""
    ev = case["evidence"]
    linked = {c for lk in case["links"] for c in lk["evidence_codes"]}
    out = {"chain": [e["code"] for e in ev if e["code"] in linked or e["kind"] in ("ACCESS", "STATE_CHANGE", "SESSION",
                                                                                   "ENTITLEMENT", "BENEFICIARY")]}
    for agent, kinds in KINDS.items():
        out[agent] = [e["code"] for e in ev if e["kind"] in kinds or (agent == "alibi" and e.get("rebuts"))]
    out["control"] = list(dict.fromkeys(out["control"] + [c for lk in case["links"] if lk["code"] in ("E0", "E3")
                                                         for c in lk["evidence_codes"]]))
    covered = set().union(*out.values())
    out["chain"] += [e["code"] for e in ev if e["code"] not in covered]  # nothing goes unassigned
    out["defence"] = [e["code"] for e in ev]
    return {k: list(dict.fromkeys(v)) for k, v in out.items()}


def _case_brief(case: dict) -> dict:
    return {"alert": case["id"], "typology": case["argument"]["typology"], "claim_under_review": case["argument"]["claim"],
            "chain": [{k: lk[k] for k in ("code", "t", "title", "detail", "evidence_codes")} for lk in case["links"]]}


class AgenticCouncil:
    def __init__(self, case: dict, mend: dict | None, lookups: dict, client: GroqClient,
                 budgets: Budgets | None = None, cancel: threading.Event | None = None, concurrency: int = 2):
        self.case, self.mend, self.lookups = case, mend, lookups
        self.ev = {e["code"]: e for e in case["evidence"]}
        extra = " ".join(f"{lk['t']} {lk['title']} {lk['detail']}" for lk in case["links"])
        self.h = Harness(client, self.ev, case["id"], budgets, cancel, extra)
        self.client = client
        self.concurrency = concurrency
        self.board = Council(case, mend, lookups)  # the blackboard: claims, entries, retrievals, conclusion
        self.slices = _slices(case)
        self.engine_of: dict[str, str] = {}  # agent → "llm" | "deterministic"
        self.fallbacks: list[dict] = []
        self.claim_kind: dict[str, str] = {}
        self.llm_entries: set[int] = set()
        self._n = {k: 0 for k in PREFIX}
        self._lock = threading.Lock()

    # helpers ----------------------------------------------------------------
    def _next_id(self, agent: str) -> str:
        with self._lock:
            self._n[agent] += 1
            return f"{PREFIX[agent]}{self._n[agent]}"

    def _say(self, *args, llm: bool = True, **kw) -> None:
        with self._lock:
            self.board.say(*args, **kw)
            if llm:
                self.llm_entries.add(len(self.board.entries) - 1)

    def _records(self, codes: list[str]) -> list[dict]:
        return [compact(self.ev[c]) for c in codes if c in self.ev]

    def _overhead(self, agent: str, task: str, base: dict, out, codes: list[str], records: list[str]) -> int:
        from app.council.harness import SYSTEM_RULES, strict_schema

        a = AGENT[agent]
        text = SYSTEM_RULES.format(name=a["name"], job=a["job"]) + task + json.dumps(base, default=str) + \
            json.dumps(strict_schema(out, codes, records))
        return self.h.est.tokens(text) + 200

    # round 1 ----------------------------------------------------------------
    def _position(self, agent: str) -> dict:
        a = AGENT[agent]
        codes = self.slices[agent]
        base = {"case": _case_brief(self.case)}
        if agent == "alibi":
            base["alibi_verdicts"] = [{"link": lk["code"], **{k: (lk.get("alibi") or {}).get(k) for k in
                                                              ("verdict", "reasons_found", "checked")}}
                                      for lk in self.case["links"] if lk.get("alibi")]
        if agent == "control" and self.mend:
            rec = self.mend.get("recommended") or {}
            base["control_simulation"] = {k: rec.get(k) for k in ("name", "why", "breaks_at", "lead_time_s",
                                                                  "legit_ops_affected")}
        task = TASKS[agent]
        records = ALLOWED_RECORDS[agent]
        items = self._records(codes)
        budget = self.h.evidence_budget(self._overhead(agent, task, base, PositionOut, codes, records))
        groups, too_big = batches(items, budget, self.h.est)
        claims: list[tuple[ClaimOut, str]] = []
        positions, requests, uncertainties, steps = [], [], [], []
        seen: list[str] = []  # records this agent has been shown so far; later parts may cite them too
        for i, group in enumerate(groups, start=1):
            data = {**base, "records": group}
            t = task
            if len(groups) > 1:
                t += (f" Records arrive in {len(groups)} parts; this is part {i}. "
                      + ("Your claims so far are listed under prior_claims: add claims only for what these records "
                         "add, and do not repeat earlier claims." if claims else ""))
                if claims:
                    data["prior_claims"] = [{"text": c.text, "evidence": c.evidence, "status": c.status} for c, _ in claims]
            seen = list(dict.fromkeys(seen + [x["id"] for x in group]))
            allowed = set(seen)
            parsed, step = self.h.call(agent=a, rnd=1, purpose="position", task=t, data=data, out=PositionOut,
                                       codes=seen, records=records,
                                       batch=f"{i}/{len(groups)}" if len(groups) > 1 else None)
            steps.append(step)
            if parsed is None:
                if step.status == "SKIPPED" and claims:
                    break  # a budget stop after partial progress keeps what was validated
                continue
            for c in parsed.claims:
                kept, _note = self.h.ground_claim(c, allowed, step)
                if kept:
                    claims.append((kept, step.batch or "1/1"))
            pos = self.h.ground_text(parsed.position, parsed.position_evidence, allowed, step, "position")
            if pos:
                positions.append((pos, [c for c in parsed.position_evidence if c in allowed]))
            requests += [r for r in parsed.requests if r.record in records]
            uncertainties += parsed.uncertainties
        reviewed = sorted({c for s in steps if s.status in ("OK", "REPAIRED", "CACHED") for c in s.evidence_sent})
        ok = any(s.status in ("OK", "REPAIRED", "CACHED") for s in steps)
        return {"agent": agent, "ok": ok, "claims": claims, "positions": positions, "requests": requests,
                "uncertainties": uncertainties, "reviewed": reviewed, "assigned": codes,
                "unreviewable": [x["id"] for x in too_big], "steps": steps}

    def _apply_position(self, res: dict) -> None:
        agent = res["agent"]
        for c, _batch in res["claims"]:
            cid = self._next_id(agent)
            with self._lock:
                self.board.claim(agent, cid, c.text, c.evidence, c.interpretation, c.status)
                self.claim_kind[cid] = c.kind
        if res["positions"]:
            text, ev = res["positions"][-1]
            first = next((c.id for c in self.board.claims if c.owner == agent), None)
            self._say(1, "POSITION", agent, text, evidence=ev[:4], claim=first)
        for u in res["uncertainties"][:2]:
            self._say(1, "UPDATE", agent, f"Open question: {u}", llm=True)

    def _fallback(self, agent: str, det: Council, reason: str, rounds: tuple[int, ...] = (1,)) -> None:
        """Use the deterministic council's part for this agent; say so in the trace."""
        self.engine_of[agent] = "deterministic"
        self.fallbacks.append({"agent": agent, "reason": reason})
        with self._lock:
            have = {c.id for c in self.board.claims}
            for c in det.claims:
                if c.owner == agent and c.id not in have:
                    self.board.claims.append(c)
                    self.claim_kind.setdefault(c.id, "OBSERVED" if c.status == "SUPPORTED" else "INFERRED")
            for e in det.entries:
                if e.speaker == agent and e.round in rounds and e.kind in ("POSITION", "UPDATE"):
                    self.board.entries.append(e)

    # round 2 ----------------------------------------------------------------
    def _retrievals(self, requests: list[tuple[str, str, str]]) -> None:
        seen: set[str] = set()
        for agent, key, reason in requests:
            if key in seen or key not in RECORDS or len(seen) >= 5:
                continue
            seen.add(key)
            with self._lock:
                self.board.request(2, agent, key, reason or "Requested by the agent.")

    def _claims_view(self, owners: tuple[str, ...] | None = None) -> list[dict]:
        return [{"id": c.id, "owner": c.owner, "text": c.text, "status": c.status, "kind": self.claim_kind.get(c.id),
                 "evidence": c.evidence} for c in self.board.claims if owners is None or c.owner in owners]

    def _retrieval_view(self) -> list[dict]:
        return [{"id": r["id"], "record": r["record"], "status": r["status"], "result": r["result"],
                 "evidence": r["evidence"]} for r in self.board.requests]

    def _defence(self) -> list[dict]:
        a = AGENT["defence"]
        claims = self._claims_view(ROUND1)
        if not claims:
            return []
        cited = list(dict.fromkeys(c for cl in claims for c in cl["evidence"]))
        rebut = [e["code"] for e in self.case["evidence"] if e.get("rebuts")]
        codes = list(dict.fromkeys(cited + rebut + self.slices["defence"]))
        base = {"case": _case_brief(self.case), "claims": claims, "retrievals": self._retrieval_view(),
                "defence_hypotheses_already_tested": self.case["argument"].get("rebuttals", [])}
        task = ("Try to disprove the suspicious reading. Challenge up to four claims, strongest first: name the claim "
                "ID, the benign hypothesis that would explain it, and the record that would settle it.")
        records = ALLOWED_RECORDS["defence"]
        budget = self.h.evidence_budget(self._overhead("defence", task, base, DefenceOut, codes, records))
        groups, _ = batches(self._records(codes), budget, self.h.est)
        parsed, step = self.h.call(agent=a, rnd=2, purpose="challenges", task=task,
                                   data={**base, "records": groups[0] if groups else []}, out=DefenceOut,
                                   codes=[x["id"] for x in (groups[0] if groups else [])] or cited, records=records)
        if parsed is None:
            return []
        allowed = set(codes)
        ids = {c.id for c in self.board.claims}
        pos = self.h.ground_text(parsed.position, parsed.position_evidence, allowed, step, "position")
        if pos:
            self._say(2, "POSITION", "defence", pos, evidence=[c for c in parsed.position_evidence if c in allowed][:4])
        out = []
        for ch in parsed.challenges:
            if ch.target_claim not in ids:
                step.dropped.append({"text": ch.challenge[:160], "reason": f"targets unknown claim {ch.target_claim}"})
                continue
            text = self.h.ground_text(ch.challenge, ch.evidence, allowed, step, "challenge")
            hyp = self.h.ground_text(ch.benign_hypothesis, [], allowed, step, "hypothesis")
            if not text:
                continue
            owner = next(c.owner for c in self.board.claims if c.id == ch.target_claim)
            self._say(2, "CHALLENGE", "defence", text + (f" Benign reading: {hyp}" if hyp else ""), target=owner,
                      claim=ch.target_claim, evidence=[c for c in ch.evidence if c in allowed][:4])
            if ch.record in records:
                with self._lock:
                    self.board.request(2, "defence", ch.record, f"To test: {hyp or ch.challenge[:120]}")
            out.append({"claim": ch.target_claim, "owner": owner, "challenge": text, "hypothesis": hyp})
        return out

    def _respond(self, owner: str, challenges: list[dict]) -> bool:
        a = AGENT[owner]
        mine = self._claims_view((owner,))
        retrieved = [c for r in self.board.requests for c in r["evidence"]]
        codes = list(dict.fromkeys(self.slices.get(owner, []) + retrieved))
        base = {"case": _case_brief(self.case), "your_claims": mine, "challenges": challenges,
                "retrievals": self._retrieval_view()}
        task = ("Answer each challenge to your claims. Keep, lower or (only with a new A/B-graded record) raise each "
                "claim's status, citing the records that justify it.")
        budget = self.h.evidence_budget(self._overhead(owner, task, base, ResponsesOut, codes, []))
        groups, _ = batches(self._records(codes), budget, self.h.est)
        parsed, step = self.h.call(agent=a, rnd=2, purpose="responses", task=task,
                                   data={**base, "records": groups[0] if groups else []}, out=ResponsesOut,
                                   codes=[x["id"] for x in (groups[0] if groups else [])], records=[])
        if parsed is None:
            return False
        allowed = set(codes)
        by_id = {c.id: c for c in self.board.claims if c.owner == owner}
        for r in parsed.responses:
            claim = by_id.get(r.claim)
            if claim is None:
                step.dropped.append({"text": r.response[:160], "reason": f"answers a claim it does not own ({r.claim})"})
                continue
            text = self.h.ground_text(r.response, r.evidence, allowed, step, "response")
            if not text:
                continue
            new = r.status
            if new == "SUPPORTED" and claim.status != "SUPPORTED":
                fresh = [c for c in r.evidence if c not in claim.evidence and self.ev[c]["reliability"] in ("A", "B")]
                if not fresh:
                    step.adjusted.append({"text": r.response[:160], "from": "SUPPORTED", "to": claim.status,
                                          "reason": "raising a claim to SUPPORTED needs a new A/B-graded record"})
                    new = claim.status
            if new != claim.status and new in ("CONTESTED", "CONTRADICTORY"):
                claim.counterargument = next((c["challenge"] for c in challenges if c["claim"] == claim.id), None)
            claim.status = new
            self._say(2, "RESPONSE", owner, text, target="defence", claim=claim.id,
                      evidence=[c for c in r.evidence if c in allowed][:4], status=new)
        return True

    # round 3 ----------------------------------------------------------------
    def _prosecution(self) -> bool:
        a = AGENT["prosecution"]
        claims = self._claims_view()
        cited = list(dict.fromkeys(c for cl in claims for c in cl["evidence"]))
        retrieved = [c for r in self.board.requests for c in r["evidence"]]
        codes = list(dict.fromkeys(cited + retrieved))
        base = {"case": _case_brief(self.case), "claims": claims, "retrievals": self._retrieval_view()}
        task = ("Build the strongest narrative the validated claims support, in at most four claims. Then add one claim "
                "on attribution: do the records show who performed the actions, or only whose credentials were used?")
        budget = self.h.evidence_budget(self._overhead("prosecution", task, base, PositionOut, codes, []))
        groups, _ = batches(self._records(codes), budget, self.h.est)
        parsed, step = self.h.call(agent=a, rnd=3, purpose="synthesis", task=task,
                                   data={**base, "records": groups[0] if groups else []}, out=PositionOut,
                                   codes=[x["id"] for x in (groups[0] if groups else [])], records=[])
        if parsed is None:
            return False
        allowed = set(codes)
        for c in parsed.claims:
            kept, _ = self.h.ground_claim(c, allowed, step)
            if not kept:
                continue
            status = kept.status
            if status == "SUPPORTED" and any(w in kept.text.lower() for w in ATTRIBUTION):
                status = "CONTESTED"
                step.adjusted.append({"text": kept.text[:160], "from": "SUPPORTED", "to": "CONTESTED",
                                      "reason": "who acted cannot be settled: endpoint telemetry and CCTV are not ingested"})
            cid = self._next_id("prosecution")
            with self._lock:
                cl = self.board.claim("prosecution", cid, kept.text, kept.evidence, kept.interpretation, status)
                self.claim_kind[cid] = kept.kind
            if status == "CONTESTED" and not cl.counterargument:
                cl.counterargument = "Credential use by someone else is not ruled out; endpoint telemetry is not ingested."
        pos = self.h.ground_text(parsed.position, parsed.position_evidence, allowed, step, "position")
        if pos:
            self._say(3, "POSITION", "prosecution", pos, evidence=[c for c in parsed.position_evidence if c in allowed][:4],
                      claim=next((c.id for c in self.board.claims if c.owner == "prosecution"), None))
        return True

    def _evidence_position(self) -> None:
        sys = self.case["argument"].get("qualifier", {}).get("systems", [])
        self._say(1, "POSITION", "evidence", f"{len(self.ev)} evidence items from {len(sys)} independent systems "
                  f"({', '.join(sys)}). Model outputs are graded C and never stand alone.", llm=False)
        self.engine_of["evidence"] = "deterministic"

    def _evidence_gaps(self) -> None:
        for key in ("telemetry", "cctv") if self.case["argument"]["typology"] == "INSIDER_ATO" else ():
            if not any(r["record"] == RECORDS[key][0] for r in self.board.requests):
                with self._lock:
                    self.board.request(3, "evidence", key, "Needed to tell the employee apart from someone using "
                                                           "their credentials.")
        gaps = [r for r in self.board.requests if r["status"] in ("NOT_INGESTED", "NOT_FOUND")]
        missing = [c for c in self.board.claims if c.status == "MISSING"]
        if gaps or missing:
            parts = [f"{r['record']} ({'not connected' if r['status'] == 'NOT_INGESTED' else 'none found'})" for r in gaps]
            parts += [f"{c.id} has no supporting record" for c in missing]
            self._say(3, "UPDATE", "evidence", "Gaps: " + "; ".join(parts[:8]) + ".", llm=False)

    # round 4 ----------------------------------------------------------------
    def _ruling(self, coverage: dict) -> list[dict] | None:
        a = AGENT["moderator"]
        claims = self._claims_view()
        codes = list(dict.fromkeys(c for cl in claims for c in cl["evidence"]))
        base = {"case": _case_brief(self.case), "claims": claims, "retrievals": self._retrieval_view(),
                "coverage": {k: coverage[k] for k in ("evidence_total", "reviewed", "unreviewed")}}
        task = ("Write the council's ruling in three to five sentences: what records support, what is contested and "
                "why, and what remains unknown. Then list up to three records that would change the conclusion, each "
                "with what each outcome would mean. You do not decide the case: it goes to human review.")
        records = list(RECORDS)
        parsed, step = self.h.call(agent=a, rnd=4, purpose="ruling", task=task,
                                   data={**base, "records": self._records(codes[:40])}, out=RulingOut,
                                   codes=codes[:40], records=records)
        if parsed is None:
            return None
        text = self.h.ground_text(parsed.ruling, parsed.ruling_evidence, set(codes), step, "ruling")
        if text:
            self._say(4, "RULING", "moderator", text, evidence=[c for c in parsed.ruling_evidence if c in codes][:6])
        sens = []
        for s in parsed.what_would_change:
            if s.record not in RECORDS:
                continue
            sens.append({"evidence": RECORDS[s.record][0], "if": [{"condition": o.condition, "effect": o.effect}
                                                                  for o in s.outcomes][:3]})
        return sens or None

    # run --------------------------------------------------------------------
    def run(self) -> dict:
        det = Council(self.case, self.mend, self.lookups)
        det_result = det.run()
        # round 1 — independent positions
        with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
            results = list(pool.map(self._position, ROUND1))
        first_fail = next((s for r in results for s in r["steps"] if s.status == "FAILED"), None)
        if not any(r["ok"] for r in results):
            reason = (first_fail.error if first_fail else
                      next((s.error for r in results for s in r["steps"] if s.error), "no agent produced a usable output"))
            return self._as_fallback(det_result, reason)
        for r in results:
            if r["ok"] and r["claims"]:
                self.engine_of[r["agent"]] = "llm"
                self._apply_position(r)
            else:
                why = next((s.error or "; ".join(s.validation_errors[:2]) or s.status for s in r["steps"]), "no claims")
                if r["ok"] and not r["claims"]:
                    why = "every claim failed the evidence checks"
                self._fallback(r["agent"], det, why)
        self._evidence_position()
        # round 2 — retrieval, challenges, responses
        reqs = [(r["agent"], q.record, q.reason) for r in results if r["ok"] for q in r["requests"]]
        self._retrievals(reqs)
        challenges = self._defence()
        self.engine_of["defence"] = "llm" if challenges else "deterministic"
        if not challenges:
            self.fallbacks.append({"agent": "defence", "reason": "no usable challenges — the challenge round is incomplete"})
        by_owner: dict[str, list[dict]] = {}
        for c in challenges:
            by_owner.setdefault(c["owner"], []).append(c)
        for owner, chs in by_owner.items():
            if self.engine_of.get(owner) == "llm" and not self._respond(owner, chs):
                self.fallbacks.append({"agent": owner, "reason": "could not answer the defence's challenges"})
        # round 3 — synthesis and gaps
        if self._prosecution():
            self.engine_of["prosecution"] = "llm"
        else:
            self._fallback("prosecution", det, "synthesis call failed", rounds=(1, 3))
        self._evidence_gaps()
        coverage = self._coverage(results)
        # round 4 — ruling (text by the moderator agent; outcome computed)
        sens = self._ruling(coverage)
        self.engine_of["moderator"] = "llm" if sens is not None else "deterministic"
        self.board.sensitivity = sens or getattr(det, "sensitivity", [])
        result = self.board._conclude()
        return self._finish(result, coverage)

    def _coverage(self, results: list[dict]) -> dict:
        reviewed = sorted({c for s in self.h.steps if s.status in ("OK", "REPAIRED", "CACHED") for c in s.evidence_sent})
        total = sorted(self.ev)
        unreviewable = sorted({c for r in results for c in r["unreviewable"]})
        unreviewed = [c for c in total if c not in reviewed]
        return {"evidence_total": len(total), "reviewed": len(reviewed), "unreviewed": unreviewed,
                "too_large_for_one_call": unreviewable,
                "by_agent": {r["agent"]: {"assigned": len(r["assigned"]), "reviewed": len(r["reviewed"])} for r in results},
                "partial": bool(unreviewed) or any(f["agent"] in ROUND1 for f in self.fallbacks)}

    def _trace(self) -> dict:
        return {"investigation": self.case["id"], "model": self.client.model, "prompt_version": PROMPT_VERSION,
                "steps": [s.public() for s in self.h.steps], "usage": self.h.usage(), "fallbacks": self.fallbacks,
                "engines": self.engine_of,
                "dropped": sum(len(s.dropped) for s in self.h.steps), "adjusted": sum(len(s.adjusted) for s in self.h.steps)}

    def _finish(self, result: dict, coverage: dict) -> dict:
        kinds = self.claim_kind
        for c in result["claims"]:
            c["kind"] = kinds.get(c["id"], "INFERRED")
            c["engine"] = self.engine_of.get(c["owner"], "deterministic")
        result["rounds"] = [{"n": n, "title": t, "entries": [{**asdict(e), "engine": "llm" if i in self.llm_entries
                                                              else "deterministic"}
                                                             for i, e in enumerate(self.board.entries) if e.round == n]}
                            for n, t in ((1, "Independent investigation"), (2, "Cross-examination & evidence requests"),
                                         (3, "Attribution & gaps"), (4, "Ruling"))]
        contested_attribution = any(c["owner"] == "prosecution" and c["status"] == "CONTESTED" for c in result["claims"])
        for a in result["agents"]:
            if a["id"] == "defence" and a["strength"] != "Weak":
                a["position"] = "Attribution not proven" if contested_attribution else "An explanation remains open"
            a["engine"] = self.engine_of.get(a["id"], "deterministic")
        result["moderator"] = {**result["moderator"], "engine": self.engine_of.get("moderator", "deterministic")}
        if coverage["partial"]:
            missing = len(coverage["unreviewed"])
            cons = result["consensus"]
            cons["outcome"] = (f"Partial review — {coverage['reviewed']} of {coverage['evidence_total']} evidence items "
                               f"reviewed by agents" + (f", {missing} not reviewed" if missing else "")
                               + "; no conclusion is issued on what was not reviewed. " + cons["outcome"])
            cons["partial"] = True
        result["engine"] = "llm" if all(v == "llm" for k, v in self.engine_of.items() if k in ROUND1) else "hybrid"
        result["model"] = self.client.model
        result["prompt_version"] = PROMPT_VERSION
        result["coverage"] = coverage
        result["trace"] = self._trace()
        result["stats"]["llm_calls"] = self.h.calls
        result["stats"]["tokens"] = self.h.tokens
        result["note"] = (f"Agents on Groq ({self.client.model}) argued over Loom evidence inside SUTRA's harness: every "
                          "claim cites records the harness checked, record requests are answered from Loom, and the "
                          "outcome, consensus and dissent are computed, not written by a model. Nothing here scores "
                          "the case; it goes to human review.")
        return result

    def _as_fallback(self, det_result: dict, reason: str) -> dict:
        det_result["engine"] = "deterministic"
        det_result["fallback_reason"] = reason
        det_result["model"] = self.client.model
        det_result["prompt_version"] = PROMPT_VERSION
        det_result["coverage"] = {"evidence_total": len(self.ev), "reviewed": 0, "unreviewed": sorted(self.ev),
                                  "partial": True}
        det_result["trace"] = self._trace()
        det_result["note"] = ("The LLM agents could not run (" + reason + "), so this is SUTRA's deterministic "
                              "council. No agent invents records or scores the case.")
        return det_result


def run_council(case: dict, mend: dict | None, lookups: dict, engine: str = "auto",
                cancel: threading.Event | None = None, client: GroqClient | None = None) -> dict:
    """Run the council with the configured engine. Deterministic when no Groq key is set or when asked."""
    from app.core.config import get_settings
    from app.council.llm import LLMError, client_from_settings

    s = get_settings()
    t0 = time.monotonic()
    reason = ""
    if engine == "deterministic" or (engine == "auto" and s.council_engine == "deterministic"):
        client, reason = None, "the deterministic council was requested"
    elif client is None:
        try:
            client = client_from_settings()
            reason = "" if client else ("GROQ_API_KEY is not set" if not s.groq_api_key else "LLM agents are switched off")
        except LLMError as e:
            client, reason = None, str(e)
    if client is None:
        out = Council(case, mend, lookups).run()
        out["engine"] = "deterministic"
        if engine == "llm":
            out["fallback_reason"] = reason
        out["stats"]["seconds"] = round(time.monotonic() - t0, 2)
        return out
    out = AgenticCouncil(case, mend, lookups, client, Budgets.from_settings(), cancel, s.council_concurrency).run()
    out["stats"]["seconds"] = round(time.monotonic() - t0, 2)
    return out
