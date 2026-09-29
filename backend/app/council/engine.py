"""SUTRA Investigation Council — specialist agents that debate a case over its evidence.

Principles
- Agents reason only over structured case data (links, graded evidence, Alibi checks,
  rebuttals, control simulation). They never invent records or score the case.
- The protocol is a debate, not an average: independent positions → cross-examination →
  evidence requests (retrieved from Loom, or reported as not ingested) → rebuttal →
  consensus *and* dissent → what would change the conclusion.
- Every claim ends with an evidence status: SUPPORTED · CONTESTED · UNEXPLAINED · MISSING ·
  CONTRADICTORY. There is no confidence score.
- Deterministic by default (reproducible, offline). The outcome always goes to human review.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

AGENTS = [
    {"id": "chain", "name": "Chain Analyst", "icon": "link", "stance": "PROSECUTION",
     "job": "Reconstructs privilege → access → change → payment → mule → cash-out"},
    {"id": "money", "name": "Money Trail Agent", "icon": "coins", "stance": "PROSECUTION",
     "job": "Follows flows, new payees, fan-in/fan-out and cash-out"},
    {"id": "insider", "name": "Insider Risk Agent", "icon": "user", "stance": "PROSECUTION",
     "job": "Looks for privilege misuse and behavioural deviation"},
    {"id": "alibi", "name": "Alibi Agent", "icon": "receipt", "stance": "NEUTRAL",
     "job": "Searches for legitimate reasons behind each action"},
    {"id": "defence", "name": "Defence Agent", "icon": "scale", "stance": "DEFENCE",
     "job": "Tries to disprove the suspicious interpretation"},
    {"id": "prosecution", "name": "Prosecution Agent", "icon": "gavel", "stance": "PROSECUTION",
     "job": "Builds the strongest evidence-supported narrative"},
    {"id": "control", "name": "Control Agent", "icon": "shield", "stance": "NEUTRAL",
     "job": "Identifies the control failure that enabled the chain"},
    {"id": "evidence", "name": "Evidence Agent", "icon": "clipboard", "stance": "NEUTRAL",
     "job": "Checks evidence quality, contradictions and missing records"},
]
MODERATOR = {"id": "moderator", "name": "Council Moderator", "icon": "landmark", "stance": "NEUTRAL",
             "job": "Runs the rounds, rules on challenges, records consensus and dissent"}

# records an agent may request, and whether Loom holds them
RECORDS = {
    "roster": ("HR shift roster", "HRMS", True),
    "sessions": ("Staff session / VPN logs", "VPN gateway", True),
    "calls": ("Customer call-centre records", "Service desk", True),
    "tickets": ("Service tickets for the customer", "Service desk", True),
    "kyc": ("Recipient account-opening and KYC records", "CBS", True),
    "approvals": ("Approval trail for the entitlement request", "IAM", True),
    "telemetry": ("Workstation / endpoint telemetry", "EDR", False),
    "cctv": ("Branch CCTV", "Physical security", False),
    "email": ("Email approval metadata for the request", "Mail gateway", False),
    "simswap": ("Telecom SIM-swap confirmation", "DoT FRI feed", False),
    "invoices": ("Invoices supporting the transfers", "Customer documents", False),
    "sof": ("Source-of-funds declaration", "Customer documents", False),
}


@dataclass
class Claim:
    id: str
    owner: str
    text: str
    evidence: list[str]
    status: str = "SUPPORTED"
    interpretation: str = ""
    counterargument: str | None = None
    sources: list[str] = field(default_factory=list)
    t: str | None = None


@dataclass
class Entry:
    round: int
    kind: str  # POSITION | CHALLENGE | RESPONSE | REQUEST | RETRIEVAL | UPDATE | RULING
    speaker: str
    text: str
    target: str | None = None
    evidence: list[str] = field(default_factory=list)
    claim: str | None = None
    status: str | None = None


class Council:
    def __init__(self, case: dict, mend: dict | None, lookups: dict):
        self.case = case
        self.arg = case["argument"]
        self.ev = {e["code"]: e for e in case["evidence"]}
        self.links = case["links"]
        self.dims = {d["key"]: d for d in case["dims"]}
        self.mend = mend
        self.look = lookups  # retrieval results pre-computed from Loom
        self.claims: list[Claim] = []
        self.entries: list[Entry] = []
        self.requests: list[dict] = []
        self.positions: dict[str, dict] = {}

    # helpers ----------------------------------------------------------------
    def codes(self, *kinds: str, rebut: bool | None = None) -> list[str]:
        out = []
        for e in self.case["evidence"]:
            if e["kind"] in kinds and (rebut is None or bool(e["rebuts"]) == rebut):
                out.append(e["code"])
        return out

    def link(self, code: str) -> dict | None:
        return next((lk for lk in self.links if lk["code"] == code), None)

    def link_codes(self, *codes: str) -> list[str]:
        out = []
        for lk in self.links:
            if lk["code"] in codes:
                out += lk["evidence_codes"]
        return list(dict.fromkeys(out))

    def claim(self, owner: str, cid: str, text: str, evidence: list[str], interpretation: str = "",
              status: str = "SUPPORTED", t: str | None = None) -> Claim:
        evidence = [c for c in evidence if c in self.ev]
        sources = sorted({self.ev[c]["source_system"] for c in evidence})
        if not evidence and status == "SUPPORTED":
            status = "MISSING"
        c = Claim(cid, owner, text, evidence, status, interpretation, None, sources, t)
        self.claims.append(c)
        return c

    def say(self, *args, **kw) -> None:
        self.entries.append(Entry(*args, **kw))

    def find_claim(self, cid: str) -> Claim | None:
        return next((c for c in self.claims if c.id == cid), None)

    def request(self, rnd: int, agent: str, key: str, reason: str) -> dict:
        label, system, ingested = RECORDS[key]
        result = self.look.get(key)
        if not ingested:
            status, text, ev = "NOT_INGESTED", f"{label} is not connected to SUTRA — it must be collected manually.", []
        elif result and result.get("found"):
            status, text, ev = "RETRIEVED", result["text"], result.get("evidence", [])
        else:
            status, text, ev = "NOT_FOUND", (result or {}).get("text", f"No {label.lower()} found for this case."), \
                (result or {}).get("evidence", [])
        req = {"id": f"RQ-{len(self.requests) + 1}", "round": rnd, "by": agent, "record": label, "system": system,
               "reason": reason, "status": status, "result": text, "evidence": [c for c in ev if c in self.ev]}
        self.requests.append(req)
        self.say(rnd, "REQUEST", agent, f"I cannot settle this without the {label.lower()}. {reason}", evidence=[])
        self.say(rnd, "RETRIEVAL", "moderator", f"{req['id']} · {label} ({system}): {text}", target=agent,
                 evidence=req["evidence"], status=status)
        return req

    # debate -----------------------------------------------------------------
    def run(self) -> dict:
        t = self.arg["typology"]
        {"INSIDER_ATO": self._insider, "EXTERNAL_ATO": self._external, "MULE_FACTORY": self._mule,
         "CIRCULAR_FLOW": self._network, "STRUCTURING": self._network}.get(t, self._network)()
        return self._conclude()

    def _insider(self) -> None:
        f = self.case.get("features") or {}
        e0, e1, e2, e3, e4, e5 = (self.link(c) for c in ("E0", "E1", "E2", "E3", "E4", "E5"))
        lat = self.case.get("latency_s") or 0
        lead = (self.case.get("headline") or {}).get("enabling_privilege_lead_s")

        # Round 1 — independent positions
        if e0:
            self.claim("chain", "C1", f"A temporary override entitlement ({e0['detail'].split(';')[0]}) was still active "
                       f"{int(lead // 86400) if lead else '?'} days later, after its intended expiry.",
                       self.link_codes("E0"), "The enabling privilege precedes the chain.", t=e0["t"])
        self.claim("chain", "C2", f"The chain ran from staff access to money in {lat / 60:.0f} minutes: "
                   + " → ".join(lk["title"] for lk in self.links if lk["code"] in ("E1", "E2", "E3", "E4", "E5")) + ".",
                   self.link_codes("E1", "E3", "E5"), "Time-ordered; each hop within the window.")
        self.say(1, "POSITION", "chain", "Privilege-to-payment chain reconstructed. "
                 + (f"The override was granted {lead / 86400:.0f} days before the transfer and never revoked. " if lead else "")
                 + f"Access to money: {lat / 60:.0f} min.", evidence=self.link_codes("E0", "E3", "E5")[:4], claim="C2")

        pay = self.link_codes("E5")
        self.claim("money", "M1", f"{e5['title'] if e5 else 'Money'} went to {int(f.get('n_new_payees', 0))} payees "
                   "added after the staff-side change.", self.link_codes("E4", "E5"),
                   "New payees + near-limit transfers minutes after a contact change.", t=e5["t"] if e5 else None)
        fwd = self.link_codes("E5′", "E6")
        if fwd:
            self.claim("money", "M2", f"{f.get('pass_through', 0):.0%} of the payout moved on within the chain"
                       + ("; money looped back to an earlier account." if f.get("loop") else "."), fwd,
                       "Layering pattern.")
        self.say(1, "POSITION", "money", f"{e5['detail'] if e5 else ''}. Recipients forwarded the funds and cashed out.",
                 evidence=(pay + fwd)[:4], claim="M1")

        beh = self.codes("M1_RHYTHM", "M2_NAVIGATION")
        emp_dim = self.dims.get("employee", {})
        self.claim("insider", "I1", f"Behaviour deviates from the employee's own pattern: {emp_dim.get('summary', '')}.",
                   beh, "Model-derived (C-grade); corroborated by the session record.",
                   status="SUPPORTED" if beh else "MISSING")
        rel = self.codes("ACCOUNT_OPENING", "ENTITY_MATCH", "G4_FACTORY")
        if rel:
            self.claim("insider", "I2", f"Relationship: {self.dims.get('relationship', {}).get('summary', '')}.", rel,
                       "Recipients were opened and KYC-approved by the same employee.")
        self.say(1, "POSITION", "insider", "Out-of-pattern session, override used, and the receiving accounts trace back "
                 "to the same employee's approvals.", evidence=(beh + rel)[:4], claim="I1")

        alibi = self.codes("ALIBI")
        card = (e2 or e3 or {}).get("alibi") or {}
        found = card.get("reasons_found", 0)
        self.claim("alibi", "A1", f"No legitimate reason was found for the access ({found} of 5: ticket, portfolio, "
                   "queue, customer interaction, roster).", alibi + self.codes("ROSTER"),
                   "Absence of explanation, not proof of intent.", status="UNEXPLAINED")
        self.say(1, "POSITION", "alibi", f"I searched all five explanation templates for the access: {found} of 5 found. "
                 "I will keep looking before anyone treats that as intent.", evidence=alibi[:2], claim="A1")

        rebut = self.codes("HR_RECORD", "ASSET", rebut=True)
        self.say(1, "POSITION", "defence", "An unexplained access is not a crime. I will test: a customer request, "
                 "authorised extended duty, and someone else using the employee's credentials.", evidence=rebut[:2])
        self.claim("prosecution", "P0", self.arg["claim"] + ".", self.link_codes("E3", "E5", "E5′")[:6],
                   "Every hop of the chain rests on a system-of-record entry.")
        self.say(1, "POSITION", "prosecution", self.arg["claim"] + ".", evidence=self.link_codes("E3", "E5")[:3],
                 claim="P0")
        if self.mend and self.mend.get("recommended"):
            rec = self.mend["recommended"]
            self.claim("control", "K1", f"Control failure: {rec['name'].lower()} was not in force; it would have broken "
                       f"the chain {rec['lead_time_s'] / 86400:.0f} days before the transfer." if rec.get("lead_time_s")
                       else f"Control failure: {rec['name'].lower()}.", self.link_codes("E0") or self.link_codes("E3"),
                       rec["why"])
            self.say(1, "POSITION", "control", f"The enabling failure is at {self.mend['result'].get('broken_at', {}) and 'E0' or 'E3'}: "
                     f"{rec['name']}. It affects {rec['legit_ops_affected']} legitimate operations.",
                     evidence=self.link_codes("E0")[:2], claim="K1")
        sys = self.arg["qualifier"]["systems"]
        self.say(1, "POSITION", "evidence", f"{len(self.ev)} evidence items from {len(sys)} independent systems "
                 f"({', '.join(sys)}). Model outputs are graded C and never stand alone.", evidence=[])

        # Round 2 — cross-examination
        self.say(2, "CHALLENGE", "defence", "You claim the privilege enabled the payout. Show the records connecting the "
                 "override to the account change and the transfer.", target="chain", claim="C1")
        conn = self.link_codes("E0")[:1] + self.link_codes("E3")[:1] + self.link_codes("E5")[:1]
        self.say(2, "RESPONSE", "chain", "Entitlement grant → change made with the override flag → transfers to payees added "
                 "after that change. Connection: supported by records.", target="defence", evidence=conn, claim="C1",
                 status="SUPPORTED")
        self.say(2, "CHALLENGE", "alibi", "The after-hours login alone is insufficient. Was the employee on camp duty or "
                 "overtime?", target="insider", claim="I1")
        roster = self.request(2, "alibi", "roster", "Check every duty type, including camps and overtime.")
        ros_ok = roster["status"] == "RETRIEVED" and self.look["roster"].get("on_duty")
        self.say(2, "UPDATE", "alibi", "Roster confirms duty cover — timing is explained." if ros_ok else
                 "No rostered duty at the time. The timing stays unexplained.", evidence=roster["evidence"],
                 status="CONTESTED" if ros_ok else "UNEXPLAINED")
        self.say(2, "CHALLENGE", "defence", "Did the customer ask for the mobile change by phone or at a branch?",
                 target="prosecution")
        calls = self.request(2, "defence", "calls", "Any call, ticket, token or eKYC for the customer in the prior 7 days.")
        self.say(2, "UPDATE", "defence", "A customer request exists — that weakens the takeover reading." if calls["status"] == "RETRIEVED"
                 else "No customer request on record. I withdraw that explanation.",
                 evidence=calls["evidence"], status="CONTESTED" if calls["status"] == "RETRIEVED" else "REFUTED")
        self.say(2, "CHALLENGE", "defence", "Could the transfers have a legitimate purpose — family or business?",
                 target="money", claim="M1")
        kyc = self.request(2, "money", "kyc", "Who opened the receiving accounts, and were customers present?")
        self.say(2, "RESPONSE", "money", "The receiving accounts were opened and approved by the same employee without the "
                 "customer present; no business relationship with the victim exists." if kyc["status"] == "RETRIEVED"
                 else "Receiving-account KYC could not be tied back — purpose remains open.", target="defence",
                 evidence=kyc["evidence"], claim="M1", status="SUPPORTED" if kyc["status"] == "RETRIEVED" else "CONTESTED")

        # Round 3 — attribution and gaps
        own = self.codes("ASSET")
        self.say(3, "CHALLENGE", "defence", "Even if the chain is real, you have not shown that the employee — rather "
                 "than someone using the employee's credentials — performed it.", target="prosecution")
        self.request(3, "evidence", "telemetry", "Needed to tell the employee apart from someone on their device.")
        self.request(3, "evidence", "cctv", "Would place (or not place) the employee physically.")
        self.claim("prosecution", "P1", "The actions were performed by the employee in person.", own,
                   "Session came from the employee's own issued device.", status="CONTESTED")
        self.find_claim("P1").counterargument = ("Credential compromise is not ruled out; endpoint telemetry is "
                                                 "not ingested.")
        self.say(3, "RESPONSE", "prosecution", "The session used the employee's own laptop. I accept that this does not "
                 "prove who was at the keyboard.", target="defence", evidence=own, claim="P1", status="CONTESTED")
        self.say(3, "RULING", "moderator", "Chain and money flow: supported by records. Attribution to the person: "
                 "contested pending telemetry. Recorded as dissent, not dropped.", evidence=[])
        self.sensitivity = [
            {"evidence": "Workstation / endpoint telemetry", "if": [
                {"condition": "Session originated on LAP-221 with the employee's interactive login", "effect": "Attribution strengthens — person-level finding becomes possible"},
                {"condition": "Remote-access tooling or another user on the device", "effect": "Credential-compromise hypothesis gains — attribution weakens; chain stands"}]},
            {"evidence": "Email approval metadata for the override request", "if": [
                {"condition": "Request raised by the employee after the camp ended", "effect": "Intent to retain privilege — strengthens insider reading"},
                {"condition": "Revocation job failure logged by IT", "effect": "Control failure is systemic, not personal"}]},
            {"evidence": "Branch CCTV", "if": [
                {"condition": "Employee absent from branch and home IP matches", "effect": "Consistent with remote session; no change"},
                {"condition": "Someone else seen at the employee's desk", "effect": "Weakens attribution"}]},
        ]

    def _external(self) -> None:
        f = self.case.get("features") or {}
        self.claim("chain", "C1", "New-device login → password reset → new payees → payouts, all within "
                   f"{(self.case.get('latency_s') or 0) / 60:.0f} minutes.", self.link_codes("E1", "E2", "E4", "E5"))
        self.say(1, "POSITION", "chain", "Customer-side takeover chain; no staff action involved.",
                 evidence=self.link_codes("E1", "E5")[:3], claim="C1")
        self.claim("money", "M1", f"Transfers hugged the per-transaction limit and went to {int(f.get('n_new_payees', 0))} new payees.",
                   self.link_codes("E5"))
        self.say(1, "POSITION", "money", "Near-limit transfers to payees created minutes earlier.",
                 evidence=self.link_codes("E5")[:3], claim="M1")
        self.say(1, "POSITION", "insider", "No employee appears in this chain. I have nothing to add.", evidence=[])
        self.say(1, "POSITION", "defence", "A new phone or travel could explain the device and location.", evidence=[])
        self.say(2, "CHALLENGE", "defence", "Was the SIM swapped, or did the customer simply change phones?", target="chain")
        self.request(2, "evidence", "simswap", "Telecom confirmation would settle the takeover path.")
        self.claim("prosecution", "P1", "The customer did not authorise these payees.", self.link_codes("E4"),
                   status="CONTESTED")
        self.find_claim("P1").counterargument = "Customer not yet contacted; SIM-swap unconfirmed."
        self.say(3, "RULING", "moderator", "Takeover pattern supported; customer authorisation contested until contacted.")
        self.sensitivity = [{"evidence": "Telecom SIM-swap confirmation", "if": [
            {"condition": "SIM re-issued shortly before 02:14", "effect": "Takeover confirmed"},
            {"condition": "No SIM change", "effect": "Consider malware or credential phishing instead"}]}]

    def _mule(self) -> None:
        emp = self.dims.get("employee", {})
        self.claim("insider", "I1", emp.get("summary", ""), self.codes("G4_FACTORY"))
        self.claim("chain", "C1", self.dims.get("access", {}).get("summary", ""), self.codes("ACCOUNT_OPENING"))
        self.claim("money", "M1", self.dims.get("network", {}).get("summary", ""), self.codes("G4_FACTORY", "M6_MULE"))
        for a in ("insider", "chain", "money"):
            c = next(x for x in self.claims if x.owner == a)
            self.say(1, "POSITION", a, c.text, evidence=c.evidence[:3], claim=c.id)
        self.say(2, "CHALLENGE", "defence", "Could this be an account-opening drive with families sharing phones?", target="insider")
        self.request(2, "alibi", "kyc", "Were customers present at opening?")
        self.claim("defence", "D1", "Three accounts share one phone — a household is possible.", self.codes("G4_FACTORY"),
                   status="CONTESTED")
        self.say(3, "RULING", "moderator", "Factory pattern supported; household sharing for three accounts remains open.")
        self.sensitivity = [{"evidence": "In-person KYC re-verification", "if": [
            {"condition": "Customers cannot be produced", "effect": "Mule factory confirmed"},
            {"condition": "Customers verified and related", "effect": "Downgrade the phone-sharing link"}]}]

    def _network(self) -> None:
        for d in self.case["dims"]:
            if d["level"] in ("HIGH", "ELEVATED") and d["supporting"]:
                self.claim("money", f"M{len(self.claims) + 1}", d["summary"], d["supporting"])
        for c in self.claims:
            self.say(1, "POSITION", c.owner, c.text, evidence=c.evidence[:3], claim=c.id)
        for r in self.arg["rebuttals"]:
            st = {"supported": "CONTESTED", "refuted": "REFUTED", "open": "CONTESTED"}[r["status"]]
            self.say(2, "CHALLENGE", "defence", f"{r['hypothesis']}?", target="money")
            self.say(2, "RESPONSE", "money", r["note"], target="defence", evidence=r["codes"], status=st)
        key = "invoices" if self.arg["typology"] == "CIRCULAR_FLOW" else "sof"
        self.request(3, "evidence", key, "Needed to test the business explanation.")
        self.say(3, "RULING", "moderator", "Pattern recorded; business explanation stays open until documents arrive.")
        self.sensitivity = [{"evidence": RECORDS[key][0], "if": [
            {"condition": "Documents match the flows", "effect": "Explained — close as benign"},
            {"condition": "Documents missing or inconsistent", "effect": "Escalate with an STR"}]}]

    # conclusion -------------------------------------------------------------
    def _conclude(self) -> dict:
        tally = {s: 0 for s in ("SUPPORTED", "CONTESTED", "UNEXPLAINED", "MISSING", "CONTRADICTORY")}
        for c in self.claims:
            tally[c.status] = tally.get(c.status, 0) + 1
        missing = [r for r in self.requests if r["status"] == "NOT_INGESTED"]
        tally["MISSING"] += len(missing)
        # agent final positions
        by_owner: dict[str, list[Claim]] = {}
        for c in self.claims:
            by_owner.setdefault(c.owner, []).append(c)
        agents = []
        dissent = []
        for a in AGENTS:
            cl = by_owner.get(a["id"], [])
            sup = sum(1 for c in cl if c.status in ("SUPPORTED", "UNEXPLAINED"))
            con = sum(1 for c in cl if c.status in ("CONTESTED", "CONTRADICTORY"))
            if a["id"] == "evidence":
                strength = "Gaps found" if missing else "Complete"
                position = f"{len(missing)} record type(s) not ingested" if missing else "Evidence complete"
            elif a["id"] == "defence":
                strength = "Moderate" if any(c.status == "CONTESTED" for c in self.claims) else "Weak"
                position = "Attribution not proven" if any(c.id == "P1" and c.status == "CONTESTED" for c in self.claims) \
                    else "Benign explanations refuted"
                if strength != "Weak":
                    dissent.append({"agent": a["id"], "reason": next((c.counterargument for c in self.claims if c.counterargument),
                                                                     "An explanation remains open")})
            elif a["id"] == "alibi":
                strength = "Mixed" if any(e.status == "CONTESTED" for e in self.entries if e.speaker == "alibi") else "Strong"
                position = "No legitimate reason found" if strength == "Strong" else "Partial explanation found"
                if strength == "Mixed":
                    dissent.append({"agent": "alibi", "reason": "A legitimate explanation covers part of the chain"})
            elif not cl:
                strength, position = ("Abstains", "Nothing in scope")
            else:
                strength = "Strong" if sup and not con else "Moderate" if sup else "Weak"
                position = cl[0].text[:90]
            agents.append({**a, "strength": strength, "position": position,
                           "claims": [c.id for c in cl],
                           "evidence": list(dict.fromkeys(x for c in cl for x in c.evidence))[:8]})
        agree = [a["id"] for a in agents if a["id"] not in {d["agent"] for d in dissent} and a["strength"] != "Abstains"]
        chain_ok = all(c.status in ("SUPPORTED", "UNEXPLAINED") for c in self.claims if c.owner in ("chain", "money"))
        outcome = ("Chain supported by records; attribution to a person contested" if chain_ok and dissent else
                   "Chain supported by records" if chain_ok else "Chain partly supported; key links contested")
        links_total = len([lk for lk in self.links])
        links_supported = len([lk for lk in self.links if lk["evidence_codes"]])
        self.say(4, "RULING", "moderator", f"Outcome: {outcome}. Sent to human review with "
                 f"{len(dissent)} dissenting view(s) and {len(missing)} evidence gap(s).")
        return {
            "alert_id": self.case["id"], "typology": self.arg["typology"], "claim": self.arg["claim"],
            "agents": agents, "moderator": MODERATOR,
            "rounds": [{"n": n, "title": t, "entries": [asdict(e) for e in self.entries if e.round == n]}
                       for n, t in ((1, "Independent investigation"), (2, "Cross-examination & evidence requests"),
                                    (3, "Attribution & gaps"), (4, "Ruling"))],
            "claims": [asdict(c) for c in self.claims],
            "requests": self.requests,
            "tally": tally,
            "consensus": {"outcome": outcome, "agree": agree, "dissent": dissent,
                          "links_supported": f"{links_supported}/{links_total}", "human_review": True},
            "sensitivity": getattr(self, "sensitivity", []),
            "stats": {"agents": len(AGENTS), "evidence": len(self.ev), "rounds": 4,
                      "requests": len(self.requests), "entries": len(self.entries)},
            "note": "Deterministic council over Loom evidence; no agent invents records or scores the case.",
        }
