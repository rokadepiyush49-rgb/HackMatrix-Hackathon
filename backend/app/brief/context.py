"""Everything Brief needs about the world, computed once per pipeline run."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from app.loom.frames import Frames
from app.needle.chains import Index


@dataclass
class BriefContext:
    f: Frames
    ix: Index
    signals: list[dict]
    er_links: list[dict]
    clusters: dict[str, str]
    cluster_evidence: list[dict]
    session_rhythm: pd.DataFrame  # M1 per staff session
    session_nav: pd.DataFrame  # M2 per staff session
    mule_scores: pd.DataFrame  # M6 per account
    prior_alerts: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.rhythm_by_session = self.session_rhythm.set_index("id") if len(self.session_rhythm) else self.session_rhythm
        self.nav_by_session = self.session_nav.set_index("session_id") if len(self.session_nav) else self.session_nav
        self.sig_by_entity: dict[str, list[dict]] = {}
        self.sig_by_event: dict[str, list[dict]] = {}
        for s in self.signals:
            for e in s["entity_refs"]:
                self.sig_by_entity.setdefault(e, []).append(s)
            for ev in s["event_refs"]:
                self.sig_by_event.setdefault(ev, []).append(s)

    def signals_for(self, events: set[str], entities: set[str], detectors: set[str] | None = None) -> list[dict]:
        seen, out = set(), []
        for ev in events:
            for s in self.sig_by_event.get(ev, []):
                if id(s) not in seen:
                    seen.add(id(s))
                    out.append(s)
        for e in entities:
            for s in self.sig_by_entity.get(e, []):
                if s["detector"] in {"R8", "G4", "G5"} and id(s) not in seen:
                    seen.add(id(s))
                    out.append(s)
        if detectors:
            out = [s for s in out if s["detector"] in detectors]
        return out
