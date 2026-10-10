"""Connected cases, M7, the rule baselines and the FIN-04 evaluation (docs/adr/017).

Case and baseline tests run on the in-memory demo world. Model and report tests need `make train`
and are skipped without it.
"""

from __future__ import annotations

import csv
import json

import numpy as np
import pytest

from app.lab.heldout import METHODS, REPORTS
from app.lab.rule_baseline import RB1_CLAUSES, RB1_VERSION, rb1
from app.ml.case_features import CASE_FEATURES, STRUCTURE_FEATURES, case_rows
from app.ml.cases import build_cases, label_cases


@pytest.fixture(scope="module")
def cases(result):
    return result["cases"]


@pytest.fixture(scope="module")
def canonical(cases):
    return next(c for c in cases if {"A-5520", "A-7731"} <= c.entities)


# ── connected cases ────────────────────────────────────────────────────────


def test_every_chain_belongs_to_exactly_one_case(result, cases):
    owners = {}
    for c in cases:
        for d in c.chains:
            assert (d.kind, d.root_ref) not in owners
            owners[(d.kind, d.root_ref)] = c.key
    assert set(owners) == {(d.kind, d.root_ref) for d in result["drafts"]}


def test_cases_partition_entities_and_never_link_through_staff(cases):
    seen: dict[str, str] = {}
    for c in cases:
        assert not any(e.startswith("EMP-") for e in c.entities), "employees are attributes, never links"
        for e in c.entities:
            assert e not in seen, f"{e} is in {seen[e]} and {c.key}"
            seen[e] = c.key


def test_case_keys_do_not_depend_on_discovery_order(result, frames, cases):
    window = (frames.window_start, frames.window_end)
    shuffled = build_cases(list(reversed(result["signals"])), list(reversed(result["drafts"])), window)
    assert sorted(c.key for c in shuffled) == sorted(c.key for c in cases)
    by_key = {c.key: c for c in shuffled}
    for c in cases:
        assert by_key[c.key].entities == c.entities


def test_takeover_and_its_mule_ring_are_one_connected_case(canonical):
    kinds = {d.kind for d in canonical.chains}
    assert {"INSIDER_ATO", "MULE_FACTORY"} <= kinds, "the 21 Sep takeover pays into the ring: one investigation"
    assert "EMP-0417" in canonical.employees


def test_labels_keep_twins_negative_and_rings_in_one_group(world, cases, canonical):
    lab = label_cases(cases, world.labels, "42")
    assert lab[canonical.key].y == 1 and "S7-suspicious" in lab[canonical.key].labels
    twin_ents = {e for x in world.labels if x["variant"] == "twin" for e in x["entities"] if not e.startswith("EMP-")}
    for c in cases:
        if c.entities & twin_ents and lab[c.key].y == 0:
            assert lab[c.key].kind == "lookalike"
    ring = {e for x in world.labels if x["key"] in ("S4-suspicious", "S7-suspicious")
            for e in x["entities"] if not e.startswith("EMP-")}
    groups = {lab[c.key].group for c in cases if c.entities & ring}
    assert groups == {lab[canonical.key].group}, "one ring must never straddle cross-validation folds"


def test_case_features_carry_provenance(frames, result, canonical):
    row = next(r for r in result["case_rows"] if r.key == canonical.key)
    assert set(row.values) == set(CASE_FEATURES)
    assert set(STRUCTURE_FEATURES) < set(CASE_FEATURES)
    known = set(frames.txn["id"]) | set(frames.access_event["id"]) | set(frames.account["id"]) | \
        set(frames.state_change["id"]) | set(frames.beneficiary["id"]) | set(frames.session["id"]) | \
        set(frames.entitlement["id"]) | set(frames.customer["id"]) | set(frames.device["id"])
    for k in ("g_accounts", "g_presenceless_share", "s_grammar", "s_log_latency", "e_alibi_unexplained"):
        assert row.values[k] > 0, k
        assert row.provenance[k], f"{k} has a value but no supporting records"
        assert set(row.provenance[k]) <= known | set(frames.employee["id"]), k


def test_case_features_are_deterministic(frames, result, cases):
    again = case_rows(cases, frames, result["explanations"], result["mule_frame"])
    for a, b in zip(result["case_rows"], again, strict=True):
        assert a.key == b.key
        np.testing.assert_array_equal([a.values[k] for k in CASE_FEATURES], [b.values[k] for k in CASE_FEATURES])


# ── rule baselines ─────────────────────────────────────────────────────────


def test_rule_baseline_is_documented_and_frozen():
    assert RB1_VERSION == "1.0"
    assert [c.code for c in RB1_CLAUSES] == ["C1", "C2", "C3", "C4", "C5", "C6"]


def test_rb1_fires_on_the_canonical_case_and_stays_quiet_on_background(world, cases, canonical):
    assert {"C1", "C3"} <= set(rb1(canonical))
    lab = label_cases(cases, world.labels, "42")
    background = [c for c in cases if lab[c.key].kind == "background"]
    assert sum(bool(rb1(c)) for c in background) / len(background) < 0.1


# ── grouped cross-validation ───────────────────────────────────────────────


def test_grouped_folds_never_split_a_group():
    from app.ml.train import grouped_folds

    groups = [f"g{i // 3}" for i in range(300)]
    y = np.array([int(int(g[1:]) % 7 == 0) for g in groups])
    folds = grouped_folds(y, groups, 5)
    g = np.array(groups)
    assert len(folds) == 5
    for tr, te in folds:
        assert not set(g[tr]) & set(g[te])
        assert y[te].sum() > 0
    covered = np.concatenate([te for _, te in folds])
    assert sorted(covered) == list(range(300))


# ── M7 (needs `make train`) ────────────────────────────────────────────────


@pytest.fixture(scope="module")
def m7():
    from app.ml.models import _load

    art = _load("case_prioritiser")
    if art is None:
        pytest.skip("M7 not trained — run `make train`")
    return art


def test_m7_trained_only_on_training_worlds_with_grouped_cv(m7):
    assert not {11, 42} & set(m7["train_seeds"])
    assert "GroupKFold" in m7["cv"]
    assert m7["metrics"]["positives"] >= 60, "too few positive cases for stable grouped metrics"
    assert m7["metrics"]["lookalikes"] >= 200, "look-alikes must be in the training negatives"


def test_m7_metric_floors_and_no_single_feature_shortcut(m7):
    m = m7["metrics"]
    assert m["pr_auc_oof"] >= 0.8 and m["brier_oof"] <= 0.05
    assert m["top_feature_share"] < 0.6, f"M7 leans on {m['top_feature']} ({m['top_feature_share']:.0%})"
    assert 0 < m7["threshold"] <= 0.99


def test_m7_treeshap_is_additive_and_scores_are_deterministic(m7, result):
    from app.ml.case_features import matrix
    from app.ml.models import score_cases

    rows = result["case_rows"]
    X = matrix(rows, m7["features"])
    booster = m7["model"].booster_
    np.testing.assert_allclose(booster.predict(X, pred_contrib=True).sum(axis=1), booster.predict(X, raw_score=True),
                               rtol=1e-6, atol=1e-6)
    a, b = score_cases(rows), score_cases(rows)
    assert {k: v.p for k, v in a.items()} == {k: v.p for k, v in b.items()}
    assert all(0.01 <= s.p <= 0.99 for s in a.values()), "a model score is never shown as certainty"


def test_m7_puts_the_canonical_case_at_the_top_and_explains_it(m7, result, canonical):
    scores = result["case_scores"]
    assert scores, "pipeline did not score cases although M7 is trained"
    top = max(scores, key=lambda k: (scores[k].p, scores[k].raw))
    assert scores[canonical.key].alert
    assert scores[canonical.key].p >= scores[top].p - 1e-9
    assert any(c["refs"] for c in scores[canonical.key].contributions[:5])


# ── the evaluation report (needs `make train`) ─────────────────────────────


@pytest.fixture(scope="module")
def report():
    path = REPORTS / "fin04_eval.json"
    if not path.exists():
        pytest.skip("no evaluation report — run `make train`")
    return json.loads(path.read_text())


def test_report_has_every_method_on_every_test_set_with_lookalikes(report):
    assert [s["key"] for s in report["test_sets"]] == ["cv", "heldout", "later"]
    assert not set(report["train_worlds"]) & set(report["heldout_worlds"])
    for s in report["test_sets"]:
        assert [r["method"] for r in s["rows"]] == METHODS, s["key"]
        assert s["lookalikes"] > 0 and s["positives"] > 0, s["key"]
        for r in s["rows"]:
            for k in ("precision", "recall", "f1", "pr_auc", "lookalike_fp_rate"):
                assert set(r[k]) == {"value", "lo", "hi"}
        assert s["by_typology"] and s["lookalikes_by_type"]
    assert "winner" not in json.dumps(report).lower(), "the report states measurements, not verdicts"
    assert "synthetic" in report["note"].lower()


def test_heldout_predictions_cover_every_case(report):
    with (REPORTS / "heldout_predictions.csv").open() as fh:
        rows = list(csv.DictReader(fh))
    for s in report["test_sets"]:
        assert sum(r["test_set"] == s["key"] for r in rows) == s["cases"]
    assert {"case_key", "label", "rb1_alert", "rb2_priority", "m7_score", "top_features", "supporting_refs"} <= set(rows[0])
