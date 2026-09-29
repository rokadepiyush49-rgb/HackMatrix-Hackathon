"""Evidence packs: a legal-grade export with a hash manifest that detects tampering.

Sections: 01 Executive summary · 02 Chain timeline · 03 Access records · 04 Privilege history
· 05 Transaction trail · 06 Alibi analysis · 07 Prosecution · 08 Defence · 09 Missing evidence
· 10 Control recommendation · 11 Audit history
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.cases import activity
from app.api.common import alert_full, iso
from app.api.workbench import _mend
from app.copilot.engine import str_draft
from app.core import audit
from app.core.config import get_settings
from app.core.db import get_db
from app.core.security import CurrentUser, Principal, require
from app.loom.models import Case, Evidence, EvidencePack
from app.ml.models import model_meta
from app.needle.registry import DETECTORS

router = APIRouter(tags=["evidence packs"])
SECTIONS = ["Executive summary", "Chain timeline", "Access records", "Privilege history", "Transaction trail",
            "Alibi analysis", "Prosecution argument", "Defence argument", "Missing evidence",
            "Control recommendation", "Audit history"]


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _bundle(db: Session, case: Case, p: Principal) -> dict:
    d = alert_full(db, case.alert_id)
    mend = _mend(db, d, [])
    arg = d["argument"]
    ev = d["evidence"]
    return {
        "pack_version": "1.0", "generated_at": datetime.now(UTC).isoformat(), "generated_by": p.id,
        "case": {"id": case.id, "state": case.state, "priority": case.priority, "assignee": case.assignee,
                 "opened_at": iso(case.opened_at)},
        "sections": {
            "01_executive_summary": {"claim": arg["claim"], "summary": arg["summary"], "priority": d["priority"],
                                     "lattice_rule": d["lattice_rule"], "amount_at_risk": d["amount_at_risk"],
                                     "access_to_money_s": d["latency_s"], "attribution": arg["attribution"]},
            "02_chain_timeline": d["links"],
            "03_access_records": [e for e in ev if e["kind"] in ("ACCESS", "SESSION", "STATE_CHANGE")],
            "04_privilege_history": [e for e in ev if e["kind"] in ("ENTITLEMENT", "ROSTER", "HR_RECORD", "ASSET")],
            "05_transaction_trail": [e for e in ev if e["kind"] in ("TXN", "BENEFICIARY")],
            "06_alibi_analysis": [e for e in ev if e["kind"] == "ALIBI"],
            "07_prosecution": {"grounds": arg["grounds"], "dimensions": d["dims"], "warrant": arg["warrant"],
                               "backing": arg["backing"], "qualifier": arg["qualifier"]},
            "08_defence": {"rebuttals": arg["rebuttals"], "counter_evidence": [e for e in ev if e["rebuts"]]},
            "09_missing_evidence": arg["missing"],
            "10_control_recommendation": mend.get("recommended") if mend else None,
            "11_audit_history": activity(case.id, p, db),
        },
        "str_draft": str_draft({**d, "mend": mend}),
        "provenance": {"detectors": {c: DETECTORS[c].version for c in DETECTORS}, "models": model_meta(),
                       "as_of_snapshot": f"SNAP-{d['last_t'][:10].replace('-', '')}",
                       "data_note": "Synthetic Kestrel-Sim data (seed 42)."},
        "manifest": [{"code": e["code"], "source": f"{e['source_system']}:{e['source_table']}:{e['source_ref']}",
                      "grade": f"{e['reliability']}{e['credibility']}", "sha256": e["sha256"]} for e in ev],
    }


def _pdf(bundle: dict, path: Path) -> None:
    ss = getSampleStyleSheet()
    ink = colors.HexColor("#111827")
    h = ParagraphStyle("h", parent=ss["Heading2"], textColor=ink, fontSize=12, spaceBefore=10, spaceAfter=4)
    body = ParagraphStyle("b", parent=ss["BodyText"], fontSize=8.5, leading=11)
    mono = ParagraphStyle("m", parent=body, fontName="Courier", fontSize=7.5, leading=9.5)
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=14 * mm,
                            bottomMargin=14 * mm, title=f"SUTRA evidence pack {bundle['case']['id']}")
    s = bundle["sections"]
    story = [Paragraph(f"<b>SUTRA · Evidence pack · {bundle['case']['id']}</b>", ss["Title"]),
             Paragraph(f"Generated {bundle['generated_at'][:19]}Z by {bundle['generated_by']} · "
                       f"{bundle['provenance']['data_note']}", body), Spacer(1, 6)]

    def section(i: int, title: str) -> None:
        story.append(Paragraph(f"{i:02d} · {title}", h))

    ex = s["01_executive_summary"]
    section(1, SECTIONS[0])
    story += [Paragraph(f"<b>{ex['claim']}</b>", body), Paragraph(ex["summary"] or "", body),
              Paragraph(f"Priority {ex['priority']} — {ex['lattice_rule']}", body),
              Paragraph(f"Attribution: {ex['attribution']['note']}", body)]
    section(2, SECTIONS[1])
    rows = [["Code", "Time", "Lane", "Event", "Evidence"]] + [
        [lk["code"], lk["t"][5:19].replace("T", " "), lk["lane"], Paragraph(f"{lk['title']} — {lk['detail']}", body),
         ", ".join(lk["evidence_codes"][:4])] for lk in s["02_chain_timeline"]]
    t = Table(rows, colWidths=[12 * mm, 26 * mm, 14 * mm, 90 * mm, 34 * mm], repeatRows=1)
    t.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 7.5), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E5E7EB")),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"), ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D1D5DB"))]))
    story.append(t)
    for i, key, title in ((3, "03_access_records", SECTIONS[2]), (4, "04_privilege_history", SECTIONS[3]),
                          (5, "05_transaction_trail", SECTIONS[4]), (6, "06_alibi_analysis", SECTIONS[5])):
        section(i, title)
        for e in s[key]:
            story.append(Paragraph(f"<b>{e['code']}</b> [{e['reliability']}{e['credibility']}] {e['summary']}", body))
    section(7, SECTIONS[6])
    for d in s["07_prosecution"]["dimensions"]:
        story.append(Paragraph(f"<b>{d['label']}: {d['level']}</b> — {d['summary']} "
                               f"(supports: {', '.join(d['supporting'][:5]) or '—'})", body))
    story.append(Paragraph(f"Warrant: {s['07_prosecution']['warrant']['text']}", body))
    section(8, SECTIONS[7])
    for r in s["08_defence"]["rebuttals"]:
        story.append(Paragraph(f"<b>{r['hypothesis']}</b> — {r['status']}: {r['note']}", body))
    section(9, SECTIONS[8])
    for m in s["09_missing_evidence"]:
        story.append(Paragraph(f"○ {m}", body))
    section(10, SECTIONS[9])
    rec = s["10_control_recommendation"]
    story.append(Paragraph(f"{rec['name']} — {rec['why']}" if rec else "No control applies.", body))
    section(11, SECTIONS[10])
    for a in s["11_audit_history"]:
        story.append(Paragraph(f"{a['at'][:19]} · {a['actor_name']} · {a['action']} · #{a['hash']}", mono))
    story.append(Paragraph("Manifest (SHA-256 per evidence item)", h))
    for m in bundle["manifest"]:
        story.append(Paragraph(f"{m['code']} {m['grade']} {m['sha256']}  {m['source']}", mono))
    doc.build(story)


@router.post("/cases/{case_id}/packs")
def create_pack(case_id: str, db: Annotated[Session, Depends(get_db)],
                p: Annotated[Principal, Depends(require("packs:create"))]) -> dict:
    case = db.get(Case, case_id)
    if case is None:
        raise HTTPException(404, "Case not found")
    bundle = _bundle(db, case, p)
    pid = f"PACK-{datetime.now(UTC):%Y%m%d%H%M%S}"
    root = get_settings().storage_path / pid
    root.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(bundle, indent=2, default=str).encode()
    (root / "pack.json").write_bytes(raw)
    _pdf(bundle, root / "pack.pdf")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["code", "kind", "source_system", "source_ref", "grade", "observed_at", "summary", "sha256"])
    for e in bundle["sections"]["03_access_records"] + bundle["sections"]["04_privilege_history"] + \
            bundle["sections"]["05_transaction_trail"] + bundle["sections"]["06_alibi_analysis"]:
        w.writerow([e["code"], e["kind"], e["source_system"], e["source_ref"], f"{e['reliability']}{e['credibility']}",
                    e["observed_at"], e["summary"], e["sha256"]])
    (root / "evidence.csv").write_text(buf.getvalue())
    files = {n: _sha((root / n).read_bytes()) for n in ("pack.json", "pack.pdf", "evidence.csv")}
    manifest = {"files": files, "items": bundle["manifest"], "sections": SECTIONS,
                "bundle_sha256": _sha(json.dumps(files, sort_keys=True).encode())}
    pack = EvidencePack(id=pid, case_id=case_id, manifest=manifest, sha256=manifest["bundle_sha256"],
                        storage_key=str(root), created_by=p.id, created_at=datetime.now(UTC))
    db.add(pack)
    audit.append(db, p.id, "pack.create", case_id, {"pack": pid, "sha256": pack.sha256})
    db.commit()
    return {"id": pid, "sha256": pack.sha256, "manifest": manifest, "sections": SECTIONS,
            "str_draft": bundle["str_draft"]}


@router.get("/packs/{pack_id}")
def get_pack(pack_id: str, p: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> dict:
    k = db.get(EvidencePack, pack_id)
    if k is None:
        raise HTTPException(404, "Pack not found")
    bundle = json.loads((Path(k.storage_key) / "pack.json").read_text())
    return {"id": k.id, "case_id": k.case_id, "sha256": k.sha256, "manifest": k.manifest, "locked": k.locked,
            "created_by": k.created_by, "created_at": iso(k.created_at), "bundle": bundle}


@router.get("/packs/{pack_id}/download")
def download(pack_id: str, p: CurrentUser, db: Annotated[Session, Depends(get_db)], format: str = "pdf"):
    k = db.get(EvidencePack, pack_id)
    if k is None:
        raise HTTPException(404, "Pack not found")
    name = {"pdf": "pack.pdf", "json": "pack.json", "csv": "evidence.csv"}.get(format)
    if name is None:
        raise HTTPException(422, "format must be pdf, json or csv")
    audit.append(db, p.id, "pack.download", k.case_id, {"pack": pack_id, "format": format})
    db.commit()
    media = {"pdf": "application/pdf", "json": "application/json", "csv": "text/csv"}[format]
    return FileResponse(Path(k.storage_key) / name, media_type=media, filename=f"{k.case_id}-{pack_id}.{format}")


@router.get("/packs/{pack_id}/verify")
def verify(pack_id: str, p: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> dict:
    k = db.get(EvidencePack, pack_id)
    if k is None:
        raise HTTPException(404, "Pack not found")
    root = Path(k.storage_key)
    files = {n: {"expected": h, "actual": _sha((root / n).read_bytes()) if (root / n).exists() else None}
             for n, h in k.manifest["files"].items()}
    case = db.get(Case, k.case_id)
    live = {e.code: e.sha256 for e in db.execute(select(Evidence).where(Evidence.alert_id == case.alert_id)).scalars()}
    items = [{"code": m["code"], "ok": live.get(m["code"]) == m["sha256"]} for m in k.manifest["items"]]
    ok = all(v["expected"] == v["actual"] for v in files.values()) and all(i["ok"] for i in items)
    return {"ok": ok, "files": files, "items": items, "bundle_sha256": k.sha256}
