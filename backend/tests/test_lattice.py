"""The priority lattice: readable rules over dimension levels — no single score."""

import pytest

from app.brief.builder import Dim, lattice

KEYS = ["transaction", "employee", "access", "network", "temporal", "relationship", "historical"]
RECORDS = {"CBS", "IAM", "HRMS"}


def dims(high: int = 0, elevated: int = 0) -> list[Dim]:
    levels = ["HIGH"] * high + ["ELEVATED"] * elevated
    levels += ["LOW"] * (len(KEYS) - len(levels))
    return [Dim(k, lvl, "") for k, lvl in zip(KEYS, levels, strict=True)]


@pytest.mark.parametrize(
    ("kw", "expected"),
    [
        ({"dims": dims(5), "benign_supported": True}, "EXPLAINED"),
        ({"dims": dims(5), "explained": True}, "EXPLAINED"),
        ({"dims": dims(3)}, "P1"),
        ({"dims": dims(3), "recoverable": False}, "P2"),
        ({"dims": dims(3), "systems": {"CBS", "SUTRA models"}}, "P2"),
        ({"dims": dims(2)}, "P2"),
        ({"dims": dims(1), "p": 0.9}, "P2"),
        ({"dims": dims(1), "p": 0.5}, "P3"),
        ({"dims": dims(0, 2)}, "P3"),
        ({"dims": dims(1), "p": 0.1}, "WATCH"),
        ({"dims": dims(0, 1)}, "WATCH"),
    ],
)
def test_lattice_rules(kw, expected):
    args = {"systems": RECORDS, "explained": False, "recoverable": True, "p": None, "benign_supported": False} | kw
    priority, rule = lattice(args.pop("dims"), **args)
    assert priority == expected
    assert rule, "every priority must carry the rule that produced it"


def test_model_output_alone_cannot_make_p1():
    """Three High dimensions evidenced only by SUTRA's own models are not independent evidence."""
    priority, _ = lattice(dims(4), {"SUTRA models"}, False, True, 0.99, False)
    assert priority != "P1"


def test_rule_names_the_high_dimensions():
    _, rule = lattice(dims(3), RECORDS, False, True, None, False)
    assert "Transaction" in rule and "Access" in rule and "3 independent systems" in rule
