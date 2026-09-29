"""The twin test: every suspicious scenario is caught, every legitimate twin stays quiet."""

QUEUED = {"P1", "P2", "P3"}


def test_every_scenario_check_passes(evaluation):
    failing = [(s["key"], s["outcome"]) for s in evaluation["scenarios"] if not s["passed"]]
    assert not failing, f"scenario checks failed: {failing}"
    assert evaluation["summary"]["passed"] == evaluation["summary"]["total"] >= 14


def test_suspicious_scenarios_reach_the_queue_with_the_right_typology(evaluation):
    suspicious = [s for s in evaluation["scenarios"] if s["variant"] == "suspicious"]
    assert len(suspicious) >= 6
    for s in suspicious:
        allowed = set(s["expected"].get("priority_in", QUEUED))
        assert any(m["priority"] in allowed for m in s["matched"]), s["key"]


def test_legitimate_twins_never_page_an_investigator(evaluation):
    for s in (x for x in evaluation["scenarios"] if x["variant"] == "twin"):
        loud = [m for m in s["matched"] if m["priority"] in ("P1", "P2")]
        assert not loud, f"{s['key']} raised {loud}"
        assert s["outcome"].startswith(("quiet", "no P1/P2")), s["outcome"]


def test_precision_funnel_is_narrow(evaluation):
    f = evaluation["funnel"]
    assert f["explained_by_alibi"] / f["staff_accesses"] > 0.95
    assert f["signals"] > 10 * f["queued"], "signals must not map one-to-one onto alerts"
    assert f["candidate_chains"] >= f["queued"] > 0
    assert f["queued"] <= 10


def test_canonical_insider_chain(result):
    """The demo story: expired override → after-hours change → ₹14.7 L out in under an hour."""
    brief = next(b for b in result["briefs"] if b.typology == "INSIDER_ATO" and b.priority == "P1")
    d = brief.draft
    assert d.employee_id == "EMP-0417"
    assert d.account_id == "A-5520"
    codes = [lk.code for lk in d.links]
    for hop in ("E0", "E1", "E2", "E3", "E5"):
        assert hop in codes, f"missing hop {hop}"
    assert codes.index("E0") < codes.index("E3") < codes.index("E5")
    assert 40 * 60 <= d.features["latency_min"] * 60 <= 55 * 60
    assert d.features["expired_entitlement"] == 1
    assert brief.classifier is not None and brief.classifier["p"] >= 0.8


def test_links_are_time_ordered(result):
    for b in result["briefs"]:
        times = [lk.t for lk in b.draft.links if lk.code != "E0"]
        assert times == sorted(times), b.draft.root_ref


def test_every_alert_claim_is_argued(result):
    for b in result["briefs"]:
        if b.priority not in QUEUED:
            continue
        assert b.argument["grounds"], b.draft.root_ref
        assert b.rebuttals, "every queued alert must test at least one innocent explanation"
        assert all(d.level in {"NONE", "LOW", "ELEVATED", "HIGH"} for d in b.dims)
        codes = {e.code for e in b.evidence}
        for g in b.argument["grounds"]:
            assert g["code"] in codes, f"{b.draft.root_ref} cites evidence it does not hold"
