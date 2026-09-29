"""Detector registry: every signal names the detector and version that produced it."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Detector:
    code: str
    name: str
    family: str  # RULE | ML | GRAPH | LLM
    version: str
    logic: str
    params: dict = field(default_factory=dict)
    owner: str = "detection@sutra"


DETECTORS: dict[str, Detector] = {d.code: d for d in [
    Detector("R1", "Cash structuring", "RULE", "1.0",
             "≥3 cash deposits just under the PAN-quoting threshold within 72 h across ≥2 accounts "
             "or branches of one resolved person",
             {"band_min": 45_000, "band_max": 49_999, "window_h": 72, "min_count": 3}),
    Detector("R2", "Limit-hugging transfers", "RULE", "1.0",
             "≥2 outgoing transfers at ≥95% of the per-transaction limit in force, within 30 min",
             {"ratio": 0.95, "window_min": 30, "min_count": 2}),
    Detector("R3", "Dormant reactivation", "RULE", "1.0",
             "Debit from an account inoperative for ≥24 months",
             {"inactive_months": 24}),
    Detector("R4", "Contact change → new payee → payout", "RULE", "1.0",
             "Mobile/password change, then a new payee and a payment to it within 24 h",
             {"window_h": 24}),
    Detector("R5", "Off-roster sensitive access", "RULE", "1.0",
             "Sensitive access outside any rostered shift (30 min grace)", {"grace_min": 30}),
    Detector("R6", "Access without a purpose", "RULE", "1.0",
             "No ticket, portfolio, queue or customer interaction explains the access", {}),
    Detector("R7", "Override use", "RULE", "1.0", "State change performed with an override flag", {}),
    Detector("R8", "Segregation-of-duties breach", "RULE", "1.0",
             "Toxic entitlement combination held, or KYC approved by the account's own opener",
             {"toxic": ["KYC_APPROVE", "CARD_ISSUE", "MOBILE_UPDATE_OVERRIDE"]}),
    Detector("R9", "Expired entitlement used", "RULE", "1.0",
             "Action authorised by an entitlement past its intended expiry", {}),
    Detector("R10", "Account opened without customer present", "RULE", "1.0",
             "No branch token or biometric eKYC around the opening", {"window_h": 24}),
    Detector("M1", "Access-rhythm surprise", "ML", "1.0",
             "Personal hour-of-week session rate, shrunk toward peers (empirical Bayes)",
             {"shrinkage_k": 20, "threshold": 0.004}),
    Detector("M2", "Unusual navigation", "ML", "1.0",
             "Role-conditioned first-order Markov likelihood of the session's action sequence",
             {"percentile": 0.5}),
    Detector("M5", "Chain classifier", "ML", "1.0",
             "Standardised logistic regression + Platt calibration, exact contributions", {}),
    Detector("M6", "Mule-likeness", "ML", "1.0", "LightGBM with native TreeSHAP contributions", {}),
    Detector("G1", "Temporal cycles", "GRAPH", "1.0",
             "Time-respecting simple cycles (2SCENT-style enumeration)",
             {"max_len": 6, "window_h": 72, "min_retention": 0.7, "min_amount": 50_000}),
    Detector("G2", "Rapid pass-through", "GRAPH", "1.0",
             "≥90% of an inflow leaves the account within 60 min",
             {"ratio": 0.9, "window_min": 60, "min_inflow": 20_000}),
    Detector("G3", "Fan-in / fan-out", "GRAPH", "1.0",
             "Many distinct counterparties within 48 h", {"k": 12, "window_h": 48}),
    Detector("G4", "Mule factory", "GRAPH", "1.0",
             "Account-opening burst by one employee + shared identifiers + presence-less openings",
             {"burst_p": 0.01, "min_shared": 3}),
    Detector("G5", "Shared-identifier bridge", "GRAPH", "1.0",
             "Device or phone shared across unrelated customers, or employee↔customer match",
             {"min_customers": 3}),
    Detector("ER", "Entity resolution", "ML", "1.0",
             "Blocking (phone/pincode) + fuzzy name/address + field-agreement scoring", {"threshold": 0.75}),
    Detector("NEEDLE", "Privilege-to-payment chain assembly", "GRAPH", "1.0",
             "Time-respecting hop grammar ACCESS→CHANGE→SESSION→PAYEE→TXN→TXN*, Δt ≤ 72 h per hop",
             {"hop_window_h": 72}),
    Detector("ALIBI", "Explanation-based access auditing", "ML", "1.0",
             "Purpose: ticket (semantic) · portfolio · queue · interaction; timing: roster",
             {"ticket_similarity": 0.22}),
]}
