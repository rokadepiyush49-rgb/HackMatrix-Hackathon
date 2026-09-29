// Response shapes of the SUTRA API (backend/app/api). Kept in one place so every screen
// reads the same contract.

export type Priority = "P1" | "P2" | "P3" | "WATCH" | "EXPLAINED";
export type Level = "NONE" | "LOW" | "ELEVATED" | "HIGH";
export type Lane = "IAM" | "SOC" | "FRAUD" | "AML" | "HR";

export interface Me {
  id: string;
  display_name: string;
  role: string;
  title: string;
  capabilities: string[];
}

export interface DimLite {
  key: string;
  label: string;
  level: Level;
}

export interface Dim extends DimLite {
  summary: string;
  supporting: string[];
  contradicting: string[];
}

export interface AlertSummary {
  id: string;
  chain_id: string;
  typology: string;
  typology_label: string;
  claim: string;
  summary: string | null;
  priority: Priority;
  state: string;
  lattice_rule: string;
  assignee: string | null;
  created_at: string;
  amount_at_risk: number;
  latency_s: number | null;
  first_t: string;
  last_t: string;
  employee_id: string | null;
  account_id: string | null;
  classifier_p: number | null;
  recoverable: boolean;
  dims: DimLite[];
  entity_refs: string[];
}

export interface AlibiCheck {
  template: string;
  ok: boolean;
  note: string;
  ref?: string;
  similarity?: number;
  at?: string;
}

export interface AlibiCard {
  verdict: "EXPLAINED" | "PARTIAL" | "UNEXPLAINED";
  purpose_ok: boolean;
  timing_ok: boolean;
  reasons_found: number;
  checked: AlibiCheck[];
}

export interface ChainLink {
  id: string;
  seq: number;
  code: string;
  event_type: string;
  event_id: string;
  t: string;
  title: string;
  detail: string;
  lane: Lane;
  amount: number | null;
  evidence_codes: string[];
  alibi: AlibiCard | null;
}

export interface EvidenceItem {
  code: string;
  kind: string;
  summary: string;
  source_system: string;
  source_table: string;
  source_ref: string;
  reliability: "A" | "B" | "C" | "D";
  credibility: number;
  observed_at: string;
  ingested_at: string | null;
  entities: string[];
  facts: Record<string, unknown>;
  supports: string[];
  rebuts: string[];
  sha256: string;
}

export interface Rebuttal {
  hypothesis: string;
  status: "refuted" | "supported" | "open";
  note: string;
  codes: string[];
}

export interface Contribution {
  feature: string;
  label: string;
  value: number;
  contribution: number;
}

export interface Argument {
  claim: string;
  typology: string;
  summary: string;
  grounds: { code: string; text: string }[];
  rebuttals: Rebuttal[];
  warrant: { detectors: { code: string; name: string; version: string; logic: string }[]; text: string };
  backing: string[];
  qualifier: {
    systems: string[];
    n_systems: number;
    model: { name: string; p: number; decision: number; calibrated_on: string } | null;
    text: string;
  };
  missing: string[];
  recommended_actions: string[];
  attribution: { person_level: boolean; note: string };
  contributions: Contribution[];
  latency_s: number | null;
  amount_at_risk: number;
}

export interface EmployeeCard {
  id: string;
  pseudonym: string;
  role: string;
  branch_id: string;
  name: string | null;
  unmasked: boolean;
}

export interface AlertDetail extends AlertSummary {
  dims: Dim[] & DimLite[];
  argument: Argument;
  links: ChainLink[];
  evidence: EvidenceItem[];
  features: Record<string, number>;
  contributions: Contribution[];
  employee: EmployeeCard | null;
  account: { id: string; holder_name: string; status: string; kind: string; balance: number } | null;
  lanes: Lane[];
  headline: { access_to_money_s: number | null; enabling_privilege_lead_s: number | null };
}

export interface GraphNode {
  id: string;
  kind: "employee" | "account" | "external" | "cash" | "device" | "customer" | "entitlement" | "phone";
  label: string;
  sub?: string;
  role?: string;
  mule_p?: number | null;
  status?: string;
  bank?: string;
  flagged?: boolean;
  root?: boolean;
  chains?: string[];
  expiry?: string | null;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  kind: string;
  t: string | null;
  label?: string;
  amount?: number;
  channel?: string;
  txn?: string;
  chain?: string;
  priority?: Priority;
  employee?: string | null;
  chain_latency_s?: number | null;
  after_root_s?: number | null;
  root_event?: string | null;
  evidence?: string;
  override?: boolean;
  verdict?: string | null;
  count?: number;
}

export interface StatePoint {
  t: string | null;
  value?: string | number;
  by?: string;
  auth?: string;
  payee?: string;
  name?: string;
}

export interface Replay {
  alert_id: string;
  chain_id: string;
  window: { start: string; end: string };
  nodes: GraphNode[];
  edges: GraphEdge[];
  events: { t: string; lane: Lane; title: string; detail: string; code: string; evidence_codes?: string[] }[];
  state: Record<string, { mobile: StatePoint[]; limit: StatePoint[]; password: StatePoint[]; payees: StatePoint[]; balance: StatePoint[] }>;
  deltas: { code: string; t: string; title: string; detail: string; before_payment_s: number; base_rate: string | null }[];
  links: ChainLink[];
}

export interface Overview {
  as_of: string;
  hero: { amount_at_risk: number; active_chains: number; critical: number; in_motion: number };
  kpis: {
    active_chains: number;
    amount_at_risk: number;
    median_access_to_money_s: number | null;
    unexplained_accesses: number;
    partially_explained: number;
    alibi_coverage: number;
    mule_clusters: number;
    controls_bypassed: { expired_entitlements: number; sod_breaches: number; presence_less_openings: number; overrides: number };
  };
  rail: { alert: AlertSummary; links: ChainLink[] } | null;
  alerts: AlertSummary[];
  by_typology: { typology: string; label: string; count: number; amount: number }[];
  money: { nodes: GraphNode[]; edges: GraphEdge[] };
  signals: { id: string; detector: string; family: string; summary: string; t: string; entities: string[]; strength: number }[];
  funnel: Funnel | null;
  scenario_summary: LabSummary | null;
}

export interface Funnel {
  staff_accesses: number;
  explained_by_alibi: number;
  signals: number;
  candidate_chains: number;
  queued: number;
  watch: number;
  suppressed: number;
  by_priority: Record<string, number>;
}

export interface LabSummary {
  passed: number;
  total: number;
  twins_quiet: number;
  twins_total: number;
  suspicious_caught: number;
  suspicious_total: number;
}

export interface CouncilAgent {
  id: string;
  name: string;
  icon: string;
  stance: "PROSECUTION" | "DEFENCE" | "NEUTRAL";
  job: string;
  strength: string;
  position: string;
  claims: string[];
  evidence: string[];
}

export interface CouncilEntry {
  round: number;
  kind: "POSITION" | "CHALLENGE" | "RESPONSE" | "REQUEST" | "RETRIEVAL" | "UPDATE" | "RULING";
  speaker: string;
  text: string;
  target: string | null;
  evidence: string[];
  claim: string | null;
  status: string | null;
}

export interface CouncilClaim {
  id: string;
  owner: string;
  text: string;
  evidence: string[];
  status: "SUPPORTED" | "CONTESTED" | "UNEXPLAINED" | "MISSING" | "CONTRADICTORY";
  interpretation: string;
  counterargument: string | null;
  sources: string[];
  t: string | null;
}

export interface Council {
  alert_id: string;
  typology: string;
  claim: string;
  agents: CouncilAgent[];
  moderator: { id: string; name: string; icon: string; job: string };
  rounds: { n: number; title: string; entries: CouncilEntry[] }[];
  claims: CouncilClaim[];
  requests: { id: string; round: number; by: string; record: string; system: string; reason: string; status: string; result: string; evidence: string[] }[];
  tally: Record<string, number>;
  consensus: { outcome: string; agree: string[]; dissent: { agent: string; reason: string }[]; links_supported: string; human_review: boolean };
  sensitivity: { evidence: string; if: { condition: string; effect: string }[] }[];
  stats: { agents: number; evidence: number; rounds: number; requests: number; entries: number };
  note: string;
}

export interface MendControl {
  id: string;
  name: string;
  description: string;
  breaks_at: string;
  effort: "Low" | "Medium" | "High";
  kinds: string[];
  applicable: boolean;
  breaks: boolean;
  hit: { link: string; at: string; why: string } | null;
  lead_time_s: number | null;
  prevented: number;
  friction: { legit_ops_affected?: number; share_of_sensitive_ops?: number; extra_approvals_per_day?: number; customer_delay?: string };
}

export interface Mend {
  chain_id: string;
  amount_at_risk: number;
  controls: MendControl[];
  selected: string[];
  result: { breaks: boolean; broken_at: { link: string; at: string; why: string } | null; prevented: number; lead_time_s: number | null; legit_ops_affected: number; extra_approvals_per_day: number };
  recommended: { id: string; name: string; lead_time_s: number | null; legit_ops_affected: number; why: string } | null;
  note: string;
}

export interface AskAnswer {
  mode: "llm" | "deterministic";
  model: string | null;
  question: string;
  sentences: { text: string; evidence: string[]; reason: string | null }[];
  dropped: { text: string; evidence: string[]; reason: string | null }[];
  confidence: "HIGH" | "MEDIUM" | "LOW";
  suggested: string[];
}

export interface CaseFile {
  id: string;
  alert_id: string;
  title: string;
  state: string;
  priority: Priority;
  assignee: string | null;
  assignee_name: string | null;
  reviewer: string | null;
  reviewer_name: string | null;
  sla_due_at: string | null;
  decision: string | null;
  decision_reason: string | null;
  subject_response: string | null;
  opened_at: string;
  closed_at: string | null;
  alert: AlertSummary;
}

export interface AuditEntry {
  id: number;
  at: string;
  actor: string;
  actor_name: string;
  action: string;
  target?: string | null;
  payload: Record<string, unknown>;
  hash: string;
  prev_hash?: string;
}

// ── Scenario Lab & registry ─────────────────────────────────────────────────

export interface LabScenario {
  key: string;
  title: string;
  passed: boolean;
  matched: { kind: string; priority: Priority }[];
  outcome: string;
  variant: "suspicious" | "twin";
  expected: { kind?: string; alert: boolean; priority_in?: Priority[]; note?: string };
  scenario: string;
  description: string;
  differing_fact: string | null;
  entities: string[];
}

export interface ModelMeta {
  features: string[];
  metrics: Record<string, number | string>;
  version: string;
  train_seed: number;
  n_train: number;
  trained_at: string;
}

export interface LabReport {
  note: string;
  funnel: Funnel;
  summary: LabSummary;
  detectors: { code: string; signals: number; elsewhere: number; on_scenario_entities: number }[];
  scenarios: LabScenario[];
  controls_friction: Record<string, MendControl["friction"]>;
  models: Record<string, ModelMeta>;
  run_id: string;
  run_at: string;
}

export interface FlipResult {
  key: string;
  removed: { id: string; kind: string; ref: string; text: string }[];
  before: { access_id: string; verdict: string; checked: AlibiCheck[] }[];
  after: { access_id: string; verdict: string; checked: AlibiCheck[] }[];
  alert: { priority: Priority; claim: string; lattice_rule: string; classifier_p: number | null; dims: Dim[]; links: { code: string; t: string; title: string; detail: string }[] } | null;
  note: string;
}

export interface Detector {
  code: string;
  name: string;
  family: string;
  version: string;
  logic: string;
  params: Record<string, unknown>;
  owner: string;
  signals: number;
}

export interface Registry {
  detectors: Detector[];
  models: Record<string, ModelMeta>;
  agents: (CouncilAgent | Council["moderator"])[];
  llm: { role: string; verifier: string };
}
