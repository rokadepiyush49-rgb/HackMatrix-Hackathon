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

    train_all(seed=args.seed or 7, size=args.size or "demo")


def cmd_detect(args) -> None:
    from app.pipeline import run_pipeline

    run_pipeline()


def cmd_demo(args) -> None:
    cmd_seed(args)

    if not (get_settings().artifacts_path / "chain_classifier.joblib").exists() or args.retrain:
        cmd_train(argparse.Namespace(seed=7, size=args.size))
    cmd_detect(args)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="sutra", description="SUTRA command line")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn, helptext in [
        ("seed", cmd_seed, "Generate the synthetic world and load it"),
        ("train", cmd_train, "Train models on an independent synthetic world"),
        ("detect", cmd_detect, "Run signals → chains → alibi → briefs"),
        ("demo", cmd_demo, "seed + train (if needed) + detect"),
    ]:
        sp = sub.add_parser(name, help=helptext)
        sp.add_argument("--seed", type=int)
        sp.add_argument("--size", choices=["tiny", "demo", "full"])
        sp.add_argument("--retrain", action="store_true")
        sp.set_defaults(fn=fn)
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
