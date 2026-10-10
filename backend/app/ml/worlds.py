"""Synthetic worlds for training and evaluation (docs/adr/017, docs/ml/labeling.md).

Each world is generated, run through the whole pipeline with every learned input switched off, and
reduced to what training and evaluation need: labelled case rows with their rule-baseline outcomes, the
M5 chain dataset and the M6 account dataset, each with cross-validation groups. Building a world takes
about half a minute, so `build_worlds` runs them in parallel processes and returns only these compact
records.

    TRAIN_SEEDS    7, 8, 9, 10   randomised scenario instances; the only data any model is fitted on
    HELDOUT_SEEDS  11            a fifth randomised world, never used for fitting, thresholds or features
                   42            the canonical demo world, with its hand-built twins
                   42 + feed     the demo world after the held-back evening of 22 Sep (later events)
"""

from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from types import SimpleNamespace

import numpy as np
import pandas as pd

from app.ml.cases import HUBS
from app.ml.features import CHAIN_FEATURES, MULE_FEATURES, chain_row

TRAIN_SEEDS = (7, 8, 9, 10)
HELDOUT_SEEDS = (11, 42)
# Day 70 of the 90-day window. Past-only models learn from cases that ended before it; "later events"
# are held-out cases with an event on or after it.
LATER_CUTOFF = pd.Timestamp("2026-09-02", tz="Asia/Kolkata")


@dataclass
class CaseRecord:
    world: str
    key: str
    y: int
    kind: str  # suspicious | lookalike | background
    typology: str
    labels: tuple[str, ...]
    group: str
    first_t: pd.Timestamp
    last_t: pd.Timestamp
    rb1: tuple[str, ...]
    rb2: str | None
    values: dict[str, float]
    provenance: dict[str, list[str]]
    detectors: tuple[str, ...]
    chains: tuple[str, ...]
    late: bool  # touched by an event from the held-back live feed


@dataclass
class WorldData:
    name: str
    seed: int
    accounts: int  # internal accounts, for alerts per 1,000 accounts
    cases: list[CaseRecord]
    chain_X: np.ndarray
    chain_y: np.ndarray
    chain_groups: list[str]
    mule_X: np.ndarray
    mule_y: np.ndarray
    mule_groups: list[str]
    meta: dict = field(default_factory=dict)


def with_live_feed(world) -> tuple[SimpleNamespace, list[dict]]:
    """The demo world as it stands after the 22 Sep evening is ingested, plus ground truth for the feed.

    Applies each held-back row the way `loom.feed.ingest` does — insert the row, move balances, apply the
    master-data change — without touching the original world.
    """
    tables = {t: list(rows) for t, rows in world.tables.items()}
    accounts = {r["id"]: i for i, r in enumerate(tables["account"])}

    def edit(aid: str) -> dict:
        i = accounts[aid]
        tables["account"][i] = row = dict(tables["account"][i])
        return row

    for e in world.live_feed:
        tables.setdefault(e["table"], []).append(e["row"])
        r = e["row"]
        if e["table"] == "txn":
            for aid, sign in ((r["from_account"], -1), (r["to_account"], 1)):
                if aid in accounts and tables["account"][accounts[aid]]["kind"] != "EXTERNAL":
                    row = edit(aid)
                    row["balance_paise"] = row["balance_paise"] + sign * int(r["amount_paise"])
        if e["effect"]:
            row = edit(e["effect"]["account_id"])
            if e["effect"]["field"] == "REGISTERED_MOBILE":
                row["_raw_mobile"] = e["effect"]["new"]
            else:
                row["daily_limit_paise"] = int(e["effect"]["new"])

    meta = world.live_meta
    touched: dict[str, set[str]] = {"attack": set(), "camp": set()}
    for e in world.live_feed:
        if e["strand"] in touched:
            for k in ("account_id", "counterparty_account", "from_account", "to_account", "customer_id", "device_id"):
                v = e["row"].get(k)
                if isinstance(v, str) and v not in HUBS:
                    touched[e["strand"]].add(v)
    attack, camp = touched["attack"], touched["camp"] | set(meta["camp_customers"])
    labels = [
        {"key": "S4-live-22sep", "scenario": "S4", "variant": "suspicious", "typology": "INSIDER_ATO",
         "entities": sorted(attack | {meta["victim_account"], meta["victim_customer"]}), "events": []},
        {"key": "S4-live-camp", "scenario": "S4", "variant": "twin", "typology": "INSIDER_ATO",
         "entities": sorted(camp), "events": []},
    ]
    return SimpleNamespace(tables=tables), labels


def build_world(seed: int, size: str = "demo", feed: bool = False) -> WorldData:
    from app.lab.rule_baseline import rb1, rb2
    from app.loom.frames import frames_from_world
    from app.ml.cases import label_cases
    from app.pipeline import compute
    from kestrel_sim import generate

    world = generate(seed=seed, size=size)
    labels = list(world.labels)
    src = world
    if feed:
        src, extra = with_live_feed(world)
        labels += extra
    name = f"{seed}+feed" if feed else str(seed)
    f = frames_from_world(src)
    res = compute(f, log=False, models=False)
    cases, rows = res["cases"], res["case_rows"]
    lab = label_cases(cases, labels, name)
    priority_of = {(b.draft.kind, b.draft.root_ref): b.priority for b in res["briefs"]}
    feed_ids = {e["row"]["id"] for e in world.live_feed} if feed else set()
    records = []
    for c, r in zip(cases, rows, strict=True):
        L = lab[c.key]
        records.append(CaseRecord(name, c.key, L.y, L.kind, L.typology, L.labels, L.group, c.first_t, c.last_t,
                                  tuple(rb1(c)), rb2(c, priority_of), r.values, r.provenance,
                                  tuple(sorted(c.detectors)), tuple(f"{d.kind}:{d.root_ref}" for d in c.chains),
                                  bool(feed_ids & set(c.events))))

    group_of_chain = {(d.kind, d.root_ref): lab[c.key].group for c in cases for d in c.chains}
    group_of_entity = {e: lab[c.key].group for c in cases for e in c.entities}

    # M5: insider and external takeover chains; positive when the account belongs to a suspicious instance.
    pos_accts = {e for x in labels if x["variant"] == "suspicious" and x["scenario"] in ("S4", "S6")
                 for e in x["entities"]}
    drafts = [d for d in res["drafts"] if d.kind in ("INSIDER_ATO", "EXTERNAL_ATO")]
    chain_X = np.array([[chain_row(d.features)[k] for k in CHAIN_FEATURES] for d in drafts]).reshape(-1, len(CHAIN_FEATURES))
    chain_y = np.array([int(d.account_id in pos_accts) for d in drafts], dtype=int)
    chain_groups = [group_of_chain.get((d.kind, d.root_ref), f"{name}:{d.kind}:{d.root_ref}") for d in drafts]

    # M6: every internal account; positive when it is a mule in a suspicious ring.
    mf = res["mule_frame"]
    mules = {e for x in labels if x["scenario"] == "S7" and x["variant"] == "suspicious"
             for e in x["entities"] if e.startswith("A-")}
    mule_y = mf.index.isin(mules).astype(int)
    mule_groups = [group_of_entity.get(a, f"{name}:{a}") for a in mf.index]

    return WorldData(name, seed, int(len(mf)), records, chain_X, chain_y, chain_groups,
                     mf[MULE_FEATURES].to_numpy(), mule_y, mule_groups,
                     {"labels": len(labels), "chains": len(res["drafts"]), "signals": len(res["signals"])})


def _job(args: tuple[int, str, bool]) -> WorldData:
    return build_world(*args)


def build_worlds(jobs: list[tuple[int, str, bool]], log=print) -> list[WorldData]:
    """Build several worlds in parallel processes (each needs ~1.5 GB and ~30 s)."""
    workers = max(1, min(len(jobs), (os.cpu_count() or 2) - 2, 4))
    log(f"▸ Building {len(jobs)} synthetic worlds on {workers} processes …")
    if workers == 1:
        out = [_job(j) for j in jobs]
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            out = list(pool.map(_job, jobs))
    for w in out:
        pos = sum(c.y for c in w.cases)
        la = sum(c.kind == "lookalike" for c in w.cases)
        log(f"  world {w.name:<8} {len(w.cases):>4} cases ({pos} suspicious, {la} look-alike) · "
            f"{w.chain_y.sum()}/{len(w.chain_y)} M5 chains · {w.mule_y.sum()}/{len(w.mule_y)} M6 mules")
    return out
