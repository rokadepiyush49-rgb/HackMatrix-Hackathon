"""Account Aggregator, end to end: consent → approval → fetch → normalise → store → evidence.

A consent names one customer, a date range and a purpose. Nothing is fetched until it is ACTIVE.
Fetched statements are stored idempotently — a row is keyed by FIP, masked account and txnId, and
re-fetching the same statement changes nothing (NEW / DUPLICATE / CONFLICT, as for the live feed).
Revoking a consent deletes everything fetched under it; statements also expire after
`SUTRA_AA_DATA_LIFE_DAYS`. Every step is in the hash-chained audit log.

How it reaches an investigation: the Council's "source-of-funds" record (and any case on that customer)
becomes answerable. Consented statement rows are summarised into evidence items labelled with their data
source (SYNTHETIC_DEMO, SANDBOX or LIVE), so an agent can cite them and the verifier can check them.
They are not fed to M1–M7: those models were fitted on the bank's own records, and another bank's
statement is a different population they were never validated on.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.integrations.aa.normalize import normalise
from app.integrations.aa.providers import AAError, SyntheticAAProvider, provider

SOURCE_LABEL = {"SYNTHETIC_DEMO": "synthetic demo data", "SANDBOX": "AA sandbox mock data", "LIVE": "live AA data"}


def _now() -> datetime:
    return datetime.now(UTC)


def create(db: Session, customer_id: str, months: int, purpose: str, actor: str, alert_id: str | None = None) -> dict:
    conn = db.connection()
    from app.core.config import get_settings

    if conn.execute(text("SELECT 1 FROM customer WHERE id = :c"), {"c": customer_id}).first() is None:
        raise AAError("not_found", f"customer {customer_id} not found")
    p = provider(conn)
    date_to = date.today()
    date_from = date_to - timedelta(days=30 * months)
    handle = p.create_consent(customer_id, date_from, date_to, purpose)
    cid = f"AAC-{uuid_like(handle['id'])}"
    conn.execute(text("""
        INSERT INTO aa_consent (id, customer_id, alert_id, provider, data_source, provider_consent_id, status, purpose,
                                date_from, date_to, created_by, created_at, redirect_url, summary, rejected)
        VALUES (:id, :c, :a, :p, :ds, :pid, :st, :purpose, :f, :t, :by, :now, :url, '{}'::jsonb, '[]'::jsonb)"""),
                 {"id": cid, "c": customer_id, "a": alert_id, "p": p.name, "ds": p.data_source, "pid": handle["id"],
                  "st": handle["status"], "purpose": purpose, "f": date_from, "t": date_to, "by": actor, "now": _now(),
                  "url": handle.get("url")})
    _audit(db, actor, "aa.consent.create", cid, {"customer_id": customer_id, "provider": p.name,
                                                   "data_source": p.data_source, "months": months})
    return get(db, cid) | {"data_life_days": get_settings().aa_data_life_days}


def uuid_like(provider_id: str) -> str:
    return hashlib.sha256(provider_id.encode()).hexdigest()[:12].upper()


def get(db: Session, consent_id: str) -> dict:
    conn = db.connection()
    r = conn.execute(text("SELECT * FROM aa_consent WHERE id = :i"), {"i": consent_id}).mappings().first()
    if r is None:
        raise AAError("not_found", f"consent {consent_id} not found")
    n = conn.execute(text("SELECT count(*) FROM aa_fi_txn WHERE consent_id = :i"), {"i": consent_id}).scalar()
    return {k: (v.isoformat() if isinstance(v, datetime | date) else v) for k, v in dict(r).items()} | {"rows": n}


def approve_synthetic(db: Session, consent_id: str, actor: str) -> dict:
    """Demo only: stands in for the customer approving the consent in their AA app."""
    conn = db.connection()
    c = get(db, consent_id)
    if c["provider"] != "synthetic":
        raise AAError("unsupported", "real consents are approved by the customer in their AA app, not in SUTRA")
    if c["status"] != "PENDING":
        raise AAError("conflict", f"consent is {c['status']}")
    conn.execute(text("UPDATE aa_consent SET status = 'ACTIVE', approved_at = :now WHERE id = :i"),
                 {"now": _now(), "i": consent_id})
    _audit(db, actor, "aa.consent.approve_synthetic", consent_id, {"note": "demo stand-in for the customer's approval"})
    return get(db, consent_id)


def refresh(db: Session, consent_id: str) -> dict:
    conn = db.connection()
    c = get(db, consent_id)
    if c["provider"] == "synthetic" or c["status"] in ("REVOKED", "EXPIRED"):
        return c
    st = provider(conn).consent_status(c["provider_consent_id"])
    status = {"APPROVED": "ACTIVE"}.get(st, st)
    if status != c["status"]:
        conn.execute(text("UPDATE aa_consent SET status = :s, approved_at = COALESCE(approved_at, :now) WHERE id = :i"),
                     {"s": status, "now": _now(), "i": consent_id})
    return get(db, consent_id)


def fetch(db: Session, consent_id: str, actor: str) -> dict:
    conn = db.connection()
    from app.core.config import get_settings

    c = refresh(db, consent_id)
    if c["status"] != "ACTIVE":
        raise AAError("conflict", f"consent is {c['status']} — data can be fetched only under an ACTIVE consent")
    p = provider(conn)
    df, dt = date.fromisoformat(c["date_from"]), date.fromisoformat(c["date_to"])
    payload = (p.fetch(c["provider_consent_id"], df, dt, c["customer_id"]) if isinstance(p, SyntheticAAProvider)
               else p.fetch(c["provider_consent_id"], df, dt))
    rows, summaries, rejected = normalise(payload)
    counts = {"NEW": 0, "DUPLICATE": 0, "CONFLICT": 0}
    now = _now()
    for r in rows:
        prev = conn.execute(text("SELECT content_sha256 FROM aa_fi_txn WHERE id = :i"), {"i": r.id}).scalar()
        if prev is not None:
            counts["DUPLICATE" if prev == r.content_sha256 else "CONFLICT"] += 1
            continue
        conn.execute(text("""
            INSERT INTO aa_fi_txn (id, consent_id, customer_id, fip_id, masked_account, txn_id, txn_type, mode,
                                   amount_paise, balance_paise, occurred_at, value_date, narration, reference,
                                   data_source, content_sha256, fetched_at)
            VALUES (:id, :cid, :cust, :fip, :acct, :txn, :typ, :mode, :amt, :bal, :t, :vd, :narr, :ref, :ds, :sha, :now)"""),
                     {"id": r.id, "cid": consent_id, "cust": c["customer_id"], "fip": r.fip_id, "acct": r.masked_account,
                      "txn": r.txn_id, "typ": r.txn_type, "mode": r.mode, "amt": r.amount_paise, "bal": r.balance_paise,
                      "t": r.occurred_at, "vd": r.value_date, "narr": r.narration, "ref": r.reference,
                      "ds": p.data_source, "sha": r.content_sha256, "now": now})
        counts["NEW"] += 1
    expires = now + timedelta(days=get_settings().aa_data_life_days)
    conn.execute(text("UPDATE aa_consent SET fetched_at = :now, data_expires_at = :exp, summary = CAST(:s AS jsonb), "
                      "rejected = CAST(:r AS jsonb) WHERE id = :i"),
                 {"now": now, "exp": expires, "s": json.dumps({"accounts": summaries}), "r": json.dumps(rejected),
                  "i": consent_id})
    _audit(db, actor, "aa.fetch", consent_id, {"data_source": p.data_source, **counts, "rejected": len(rejected)})
    return {"consent": get(db, consent_id), "outcomes": counts, "rejected": rejected, "accounts": summaries,
            "data_source": p.data_source}


def revoke(db: Session, consent_id: str, actor: str) -> dict:
    conn = db.connection()
    c = get(db, consent_id)
    purged = conn.execute(text("DELETE FROM aa_fi_txn WHERE consent_id = :i"), {"i": consent_id}).rowcount
    conn.execute(text("UPDATE aa_consent SET status = 'REVOKED', revoked_at = :now WHERE id = :i"),
                 {"now": _now(), "i": consent_id})
    _audit(db, actor, "aa.consent.revoke", consent_id, {"purged_rows": purged, "provider": c["provider"]})
    return get(db, consent_id) | {"purged_rows": purged}


def purge_expired(db: Session) -> int:
    conn = db.connection()
    n = conn.execute(text("DELETE FROM aa_fi_txn WHERE consent_id IN (SELECT id FROM aa_consent "
                          "WHERE data_expires_at < :now)"), {"now": _now()}).rowcount
    conn.execute(text("UPDATE aa_consent SET status = 'EXPIRED' WHERE data_expires_at < :now AND status = 'ACTIVE'"),
                 {"now": _now()})
    return n


def evidence_for(db: Session, customer_ids: list[str], case_window: tuple | None = None) -> tuple[list[dict], dict]:
    """Evidence items and the source-of-funds retrieval for the council, from consented statements.

    Returns ([], {}) when no Account Aggregator data exists for these customers."""
    conn = db.connection()
    purge_expired(db)
    if not customer_ids:
        return [], {}
    consents = conn.execute(text("SELECT id, customer_id, status, data_source, provider FROM aa_consent "
                                 "WHERE customer_id = ANY(:c) ORDER BY created_at DESC"), {"c": customer_ids}).mappings().all()
    if not consents:
        return [], {"connected": True, "found": False, "evidence": [],
                    "text": "Account Aggregator is connected, but no consented statement exists for "
                            f"{', '.join(customer_ids[:3])} — request consent from the customer."}
    active = [c for c in consents if c["status"] == "ACTIVE"]
    rows = conn.execute(text("SELECT * FROM aa_fi_txn WHERE consent_id = ANY(:i) ORDER BY occurred_at"),
                        {"i": [c["id"] for c in active]}).mappings().all()
    if not rows:
        st = consents[0]["status"]
        why = {"REVOKED": "was revoked; its statement was deleted", "EXPIRED": "expired; its statement was deleted",
               "REJECTED": "was rejected by the customer"}.get(st, f"is {st}; no statement fetched yet")
        return [], {"connected": True, "found": False, "evidence": [],
                    "text": f"Consent {consents[0]['id']} {why}."}
    items = _evidence_items(db, rows, active)
    label = SOURCE_LABEL.get(rows[0]["data_source"], rows[0]["data_source"])
    return items, {"connected": True, "found": True, "evidence": [e["code"] for e in items],
                   "text": f"Consented statement via Account Aggregator ({label}): {items[0]['summary']}"}


def _rupees(paise: int) -> str:
    r = paise / 100
    return f"₹{r / 1e5:.2f} L" if r >= 1e5 else f"₹{r:,.0f}"


def _evidence_items(db: Session, rows, consents) -> list[dict]:
    conn = db.connection()
    src = rows[0]["data_source"]
    tag = f"[{SOURCE_LABEL.get(src, src)}]"
    fip = rows[0]["fip_id"]
    credits = [r for r in rows if r["txn_type"] == "CREDIT"]
    debits = [r for r in rows if r["txn_type"] == "DEBIT"]
    cash = [r for r in debits if r["mode"] in ("CASH", "ATM")]
    cust = rows[0]["customer_id"]
    deposits = conn.execute(text("""
        SELECT t.id, t.occurred_at, t.amount_paise FROM txn t JOIN account a ON a.id = t.to_account
        WHERE a.customer_id = :c AND t.kind = 'CASH_DEPOSIT' ORDER BY t.occurred_at"""), {"c": cust}).all()
    matched = []
    for d in deposits:
        near = [w for w in cash if timedelta(0) <= d.occurred_at - w["occurred_at"] <= timedelta(hours=6)]
        if near and abs(sum(w["amount_paise"] for w in near) - d.amount_paise) <= 0.1 * d.amount_paise:
            matched.append((d, near))
    top = sorted(credits, key=lambda r: -r["amount_paise"])[:1]
    first, last = rows[0]["occurred_at"], rows[-1]["occurred_at"]
    common = {"source_table": "aa_fi_txn", "reliability": "B", "credibility": 2,
              "ingested_at": rows[-1]["fetched_at"].isoformat(), "supports": [], "rebuts": [],
              "facts": {"data_source": src, "fip": fip, "consents": [c["id"] for c in consents]}}

    def item(code: str, summary: str, ref: str, t, facts: dict) -> dict:
        body = json.dumps({"code": code, "summary": summary, "facts": facts}, sort_keys=True, default=str)
        return {"code": code, "kind": "AA_STATEMENT", "summary": summary,
                "source_system": f"Account Aggregator · {fip}", "source_ref": ref, "observed_at": t.isoformat(),
                "entities": [cust], **common, "facts": {**common["facts"], **facts},
                "sha256": hashlib.sha256(body.encode()).hexdigest()}

    out = [item("AA-1", f"{tag} {len(rows)} transactions {first:%d %b %Y}–{last:%d %b %Y} on {rows[0]['masked_account']}: "
                        f"{len(credits)} credits {_rupees(sum(r['amount_paise'] for r in credits))}, "
                        f"{len(debits)} debits {_rupees(sum(r['amount_paise'] for r in debits))}",
                rows[0]["masked_account"], last, {"credits": len(credits), "debits": len(debits)})]
    if top:
        t = top[0]
        out.append(item("AA-2", f"{tag} Largest credit {_rupees(t['amount_paise'])} on {t['occurred_at']:%d %b %Y}: "
                                f"{t['narration']}", t["txn_id"], t["occurred_at"], {"mode": t["mode"]}))
    if matched:
        total = sum(d.amount_paise for d, _ in matched)
        out.append(item("AA-3", f"{tag} {len(matched)} of {len(deposits)} Kestrel cash deposits ({_rupees(total)}) were "
                                f"preceded within 6 h by cash withdrawals of a similar amount from {rows[0]['masked_account']}",
                        ",".join(d.id for d, _ in matched[:20]), matched[-1][0].occurred_at,
                        {"deposits": [d.id for d, _ in matched[:20]]}))
    elif deposits:
        out.append(item("AA-3", f"{tag} None of {len(deposits)} Kestrel cash deposits is matched by a cash withdrawal "
                                f"from {rows[0]['masked_account']} in the 6 h before it", rows[0]["masked_account"], last,
                        {"deposits": len(deposits)}))
    return out


def _audit(db: Session, actor: str, action: str, target: str, payload: dict) -> None:
    from app.core import audit

    audit.append(db, actor, action, target, payload)
