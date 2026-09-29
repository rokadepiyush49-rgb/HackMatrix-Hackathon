"""Kestrel-Sim — a seeded, agent-based synthetic co-operative bank.

    from kestrel_sim import generate
    world = generate(seed=42)          # the canonical demo world
    train = generate(seed=7)           # an independent world for model training
"""

from kestrel_sim.baseline import (
    assign_staff_devices,
    build_customers,
    build_externals,
    build_org,
    build_rosters,
    evening_vpn_approvals,
    new_accounts_in_window,
    run_customers,
    run_staff,
)
from kestrel_sim.scenarios import (
    CATALOGUE,
    DEMO_APPROVER_BIAS,
    DEMO_RESERVED,
    DEMO_STAFF,
    inject_demo,
    inject_training,
)
from kestrel_sim.world import World

SIZES = {"tiny": 900, "demo": 3600, "full": 12000}

__all__ = ["generate", "World", "CATALOGUE", "SIZES"]


def generate(seed: int = 42, size: str = "demo", mode: str | None = None) -> World:
    mode = mode or ("demo" if seed == 42 else "train")
    w = World(seed=seed, mode=mode)
    if mode == "demo":
        w.reserve(*DEMO_RESERVED)
        fixed, bias = DEMO_STAFF, DEMO_APPROVER_BIAS
    else:
        fixed, bias = {}, {}

    build_org(w, fixed)
    assign_staff_devices(w)
    shifts = build_rosters(w)
    pools = build_externals(w)
    build_customers(w, SIZES[size], pools, bias)
    new_accounts_in_window(w, shifts)

    (inject_demo if mode == "demo" else inject_training)(w, pools)

    branch_customers: dict[str, list[str]] = {}
    for cid, c in w.customers.items():
        if c.get("_scenario") or c.get("_mule"):
            continue
        branch_customers.setdefault(c["branch_id"], []).append(cid)
    run_staff(w, shifts, branch_customers)
    evening_vpn_approvals(w, shifts)
    run_customers(w, pools)

    for aid, acct in w.accounts.items():
        acct["balance_paise"] = max(0, w.balance.get(aid, 0)) if acct["kind"] != "EXTERNAL" else 0
    return w
