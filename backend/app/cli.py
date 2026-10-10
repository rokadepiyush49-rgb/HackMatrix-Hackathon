"""Command-line entry points:  python -m app.cli {seed|train|detect|demo}"""

from __future__ import annotations

import argparse
import sys
import time

from app.core.config import get_settings


def cmd_seed(args) -> None:
    from app.loom.load import load_world, seed_users, truncate_all
    from kestrel_sim import generate

    s = get_settings()
    seed, size = args.seed or s.sim_seed, args.size or s.sim_size
    t0 = time.perf_counter()
    print(f"▸ Generating Kestrel-Sim world (seed={seed}, size={size}) …")
    world = generate(seed=seed, size=size)
    print(f"  done in {time.perf_counter() - t0:.1f}s · {len(world.labels)} scenario labels")
    print("▸ Loading into Postgres …")
    truncate_all()
    load_world(world)
    seed_users()
    print(f"✓ Seeded in {time.perf_counter() - t0:.1f}s")


def cmd_train(args) -> None:
    from app.ml.train import train_all

    train_all(size=args.size or "demo", evaluate=not getattr(args, "no_eval", False))


def cmd_detect(args) -> None:
    from app.pipeline import run_pipeline

    run_pipeline()


def cmd_demo(args) -> None:
    cmd_seed(args)

    if not (get_settings().artifacts_path / "chain_classifier.joblib").exists() or args.retrain:
        cmd_train(argparse.Namespace(size=args.size, no_eval=False))
    cmd_detect(args)


def _live(kind: str, speed: float = 0.0) -> None:
    """Play the live feed (or reset it) from the terminal — the same code path as the Live Ops page."""
    import json
    from datetime import UTC, datetime

    from app.api import live

    def show(event: str, data: dict) -> None:
        if event == "stage" and data["status"] == "done":
            print(f"  {data['key']:<10} {data['detail'] or '':<72} {data['elapsed']:6.1f}s")
        elif event == "alert" and data["new"]:
            print(f"  ⚑ {data['id']} {data['priority']} {data['typology']} · {data['claim']}")
        elif event in ("done", "failed", "cancelled"):
            print(f"{'✓' if event == 'done' else '✗'} {event}: {json.dumps(data, default=str)}")

    run = live.Run(id=f"CLI-{kind.upper()}", kind=kind, actor="cli", started_at=datetime.now(UTC).isoformat(),
                   listener=show)
    if kind == "feed":
        live.play_feed(run, speed)
    else:
        live.reset_feed(run)


def cmd_live_play(args) -> None:
    _live("feed", args.speed)


def cmd_live_reset(args) -> None:
    _live("reset")


def cmd_bank_check(args) -> None:
    """Run every mock-bank scenario, run SUTRA once, compare each outcome with what it should be, undo."""
    from datetime import UTC, datetime

    from sqlalchemy import text

    from app.api import live
    from app.core.db import engine
    from app.loom import bank_scenarios as bs

    def quiet_run(kind: str, scope: str):
        return live.Run(id=f"CHECK-{kind.upper()}", kind=kind, actor="bank-check", started_at=datetime.now(UTC).isoformat(),
                        scope=scope)

    with engine.connect() as c:
        dirty = c.execute(text("SELECT count(*) FROM feed_event WHERE strand = 'bank'")).scalar()
    if dirty:
        print(f"▸ Undoing {dirty} earlier bank rows first …")
        live.reset_feed(quiet_run("reset", "bank"), "bank")

    print("▸ Running the scenarios in the mock bank (MOCK BANK — TEST ENVIRONMENT — NO REAL MONEY)")
    results = {}
    for key in bs.SCENARIOS:
        with engine.begin() as c:
            out, refs = bs.run(c, key)
        results[key] = (out, refs)
        resp = out["bankResponse"]
        print(f"  {key:<13} bank: {resp['status']:<7} {resp.get('code', ''):<20} rows recorded: {len(refs)}")

    print("▸ SUTRA detection over the bank's records …")
    t = time.perf_counter()
    live.play_feed(quiet_run("feed", "bank"), 0, True, "bank")
    print(f"  done in {time.perf_counter() - t:.1f}s")

    passed = 0
    print("▸ Scenario results")
    with engine.connect() as c:
        for key, (out, refs) in results.items():
            ok, why = bs.verdict(bs.SCENARIOS[key], out, bs.outcome(c, refs))
            passed += ok
            print(f"  {'✓' if ok else '✗'} {bs.SCENARIOS[key].title:<36} {why}")
    print(f"{'✓' if passed == len(results) else '✗'} {passed}/{len(results)} scenarios behaved as expected")

    if not args.keep:
        print("▸ Undoing the bank's records and re-detecting …")
        live.reset_feed(quiet_run("reset", "bank"), "bank")
        from app.loom import bank

        bank.set_clock("20:45")
    if passed != len(results):
        raise SystemExit(1)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="sutra", description="SUTRA command line")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn, helptext in [
        ("seed", cmd_seed, "Generate the synthetic world and load it"),
        ("train", cmd_train, "Train M5, M6 and M7 on worlds 7–10, then evaluate against the rule baselines"),
        ("detect", cmd_detect, "Run signals → chains → alibi → briefs"),
        ("demo", cmd_demo, "seed + train (if needed) + detect"),
    ]:
        sp = sub.add_parser(name, help=helptext)
        sp.add_argument("--seed", type=int)
        sp.add_argument("--size", choices=["tiny", "demo", "full"])
        sp.add_argument("--retrain", action="store_true")
        sp.add_argument("--no-eval", action="store_true", help="train: skip the held-out evaluation")
        sp.set_defaults(fn=fn)
    lp = sub.add_parser("live-play", help="Stream tonight's held-back feed into Loom and detect (demo world)")
    lp.add_argument("--speed", type=float, default=0.0, help="simulated seconds per second; 0 = no pauses")
    lp.set_defaults(fn=cmd_live_play)
    sub.add_parser("live-reset", help="Undo the live feed and re-detect").set_defaults(fn=cmd_live_reset)
    bc = sub.add_parser("bank-check", help="Run every mock-bank scenario through SUTRA and check the outcomes")
    bc.add_argument("--keep", action="store_true", help="leave the scenarios' records in place afterwards")
    bc.set_defaults(fn=cmd_bank_check)
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
