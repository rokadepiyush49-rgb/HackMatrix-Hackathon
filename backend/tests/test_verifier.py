"""Cite-or-drop: a sentence survives only if its evidence codes exist and back every figure."""

from app.copilot.engine import Sentence, verify

EVIDENCE = {
    "EV-101": {"summary": "IMPS ₹4,90,000 from A-5520 to A-7731 at 22:34", "facts": {"channel": "IMPS"},
               "entities": ["A-5520", "A-7731"]},
    "EV-103": {"summary": "MOBILE_UPDATE_OVERRIDE granted to EMP-0417 via REQ-3391", "facts": {},
               "entities": ["EMP-0417"]},
}


def run(*sentences: Sentence):
    return verify(list(sentences), EVIDENCE)


def test_grounded_sentence_is_kept():
    kept, dropped = run(Sentence("₹4.90 L left A-5520 for A-7731 at 22:34.", ["EV-101"]))
    assert len(kept) == 1 and not dropped


def test_uncited_sentence_is_dropped():
    _, dropped = run(Sentence("The employee was clearly acting alone.", []))
    assert dropped[0].reason == "no evidence cited"


def test_unknown_evidence_code_is_dropped():
    _, dropped = run(Sentence("A transfer happened.", ["EV-999"]))
    assert "unknown evidence" in dropped[0].reason


def test_invented_amount_is_dropped():
    _, dropped = run(Sentence("₹9.99 L left A-5520.", ["EV-101"]))
    assert "₹9.99 L" in dropped[0].reason


def test_invented_entity_is_dropped():
    _, dropped = run(Sentence("Money also went to A-9999.", ["EV-101"]))
    assert "A-9999" in dropped[0].reason


def test_invented_time_is_dropped():
    _, dropped = run(Sentence("The transfer ran at 23:59.", ["EV-101"]))
    assert "23:59" in dropped[0].reason


def test_citing_a_code_in_text_but_not_in_evidence_list_is_dropped():
    _, dropped = run(Sentence("See EV-103 for the override.", ["EV-101"]))
    assert "EV-103" in dropped[0].reason


def test_figures_must_come_from_the_cited_items_not_any_item():
    """EMP-0417 is in EV-103, but the sentence only cites EV-101."""
    _, dropped = run(Sentence("EMP-0417 sent money to A-7731.", ["EV-101"]))
    assert dropped and "EMP-0417" in dropped[0].reason
