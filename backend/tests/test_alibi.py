"""Alibi: the ordinary explanation is looked for before anything is called suspicious."""

from app.alibi.engine import explain


def _access_ids(frames, label) -> set[str]:
    return set(frames.access_event[frames.access_event["id"].isin(label["events"])]["id"])


def test_most_accesses_are_explained(result):
    ex = result["explanations"]
    assert (ex["verdict"] == "EXPLAINED").mean() > 0.95
    assert set(ex["verdict"].unique()) <= {"EXPLAINED", "PARTIAL", "UNEXPLAINED"}


def test_every_access_checks_all_five_templates(result):
    sample = result["explanations"].head(200)
    for checked in sample["checked"]:
        assert [c["template"] for c in checked] == ["TICKET", "PORTFOLIO", "QUEUE", "INTERACTION", "ROSTER"]


def test_insider_access_has_no_alibi(frames, labels):
    ids = _access_ids(frames, labels["S4-suspicious"])
    assert ids
    ex = explain(frames, only_access_ids=ids)
    changes = ex[ex["access_event_id"].isin(ids)]
    assert (changes["verdict"] == "UNEXPLAINED").any()
    worst = changes[changes["verdict"] == "UNEXPLAINED"].iloc[0]
    assert not any(c["ok"] for c in worst["checked"])


def test_pension_camp_twin_is_explained(frames, labels):
    ids = _access_ids(frames, labels["S4-twin"])
    ex = explain(frames, only_access_ids=ids)
    row = ex.iloc[0]
    assert row["verdict"] == "EXPLAINED"
    ok = {c["template"] for c in row["checked"] if c["ok"]}
    assert {"TICKET", "INTERACTION", "ROSTER"} <= ok


def test_removing_the_alibi_flips_the_twin(frames, labels):
    """Counterfactual used by the Twin Lab: delete the ticket, eKYC and camp roster."""
    lab = labels["S4-twin"]
    ids = _access_ids(frames, lab)
    wi = frames.work_item[frames.work_item["id"].isin(lab["events"]) & frames.work_item["kind"].isin(["TICKET", "EKYC"])]
    acc = frames.access_event[frames.access_event["id"].isin(ids)]
    emp = acc["employee_id"].iloc[0]
    day = acc["occurred_at"].iloc[0].normalize()
    ros = frames.roster[(frames.roster["employee_id"] == emp) & (frames.roster["duty_type"] == "CAMP")
                        & (frames.roster["shift_start"] >= day)]
    assert len(wi) and len(ros)
    after = explain(frames, exclude_work_items=set(wi["id"]), exclude_rosters=set(ros["id"]), only_access_ids=ids)
    assert (after["verdict"] == "UNEXPLAINED").all()
