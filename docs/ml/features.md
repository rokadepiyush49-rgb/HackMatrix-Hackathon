# M7 case features

The 32 features M7 learns from, in three families. Code:
[`app/ml/case_features.py`](../../backend/app/ml/case_features.py). Each value comes with its
**provenance**, the records that produced it, so every bar in a score breakdown links back to
transactions, staff accesses, accounts or other cases. Provenance travels with each contribution as
`refs`, in the alert's `argument.case.suspicion` and in `model_prediction` rows for `M7`.

Rules every feature follows:

- **No arrival information.** Nothing reads `ingested_at`, display IDs (`AL-`, `CH-`, `SG-`) or row
  order, so the same events give the same features whatever order they arrived in.
- **No ground truth.** Features read Loom tables and detector outputs only.
- **No learned inputs.** M5 and M6 scores are not features, so M7 does not stack on models trained on
  overlapping data.
- **Missing means missing.** Sequence features that need a chain (latency, grammar, balance moved) are
  `NaN` when a case has none. LightGBM routes missing values natively.

Every feature is computed over the case's internal accounts, its chains and its signals.

## Graph — who is connected to whom

| Feature | Meaning | Provenance |
|---|---|---|
| `g_accounts` | log(1 + internal accounts in the case) | the accounts |
| `g_customers` | log(1 + distinct customers) | customer IDs |
| `g_employees` | staff involved through chains, opening/approval, overrides or attached signals | employee IDs |
| `g_devices` | devices in the case | device IDs |
| `g_external_share` | share of the case's accounts held at other banks | external accounts |
| `g_new_account_share` | share of internal accounts opened inside the 90-day window | the new accounts |
| `g_presenceless_share` | share of new accounts opened with no branch token or biometric eKYC within 24 h | those accounts |
| `g_self_approved_share` | share of accounts whose opener approved their own KYC | those accounts |
| `g_opener_concentration` | share of the case's new accounts opened by its busiest opener (0 below 2 new accounts) | the employee and the accounts |
| `g_shared_identifier` | log(1 + accounts whose customer shares a device or phone with another customer) | those accounts |
| `g_max_fan_in` | log(1 + most distinct senders into one account) | the account |
| `g_max_pass_through` | largest share of ≥ ₹10,000 inflows forwarded within 60 min | the account |
| `g_cash_out` | largest share of an account's outflow withdrawn at ATMs | the account |
| `g_cycle_retention` | largest share of a G1 cycle's first hop that came back (0 without a cycle) | the cycle's transactions |
| `g_linked_cases` | log(1 + other cases that share an employee with this one) | the other case keys |

## Sequence — in what order and how fast

| Feature | Meaning | Provenance |
|---|---|---|
| `s_log_latency` | log(1 + minutes) from the first session to the first payout, fastest takeover chain | the session and payout |
| `s_grammar` | share of the insider hop grammar E0, E1, E2, E3, E4, E5, E5′, E6 the chain reached | the link events |
| `s_hops` | distinct hop codes in the longest chain (0 without a chain) | the chain's root |
| `s_min_hop_gap` | log(1 + seconds) between the two closest consecutive hops of different kinds | the two events |
| `s_span` | log(1 + hours) from the case's first event to its last | the first and last event |
| `s_burstiness` | coefficient of variation of the gaps between events (needs ≥ 3 events) | the events |
| `s_night_share` | share of events between 20:00 and 06:00 | the night events |
| `s_change_to_payee` | 1 when a mobile, password, e-mail, device or limit change is followed by a new payee on the same account within 30 min | the change and the payee |
| `s_balance_moved` | largest share of an account's balance a takeover moved out | the payouts |
| `s_grant_to_use_days` | days from the entitlement grant (E0) to the state change it enabled (E3) | the grant and the change |

## Evidence — what the detectors said

| Feature | Meaning | Provenance |
|---|---|---|
| `e_rule_detectors` | distinct rule detectors (R1–R10) on the case | detector codes |
| `e_graph_detectors` | distinct graph detectors (G1–G5) | detector codes |
| `e_behaviour` | distinct behavioural detectors (M1 rhythm, M2 navigation) | detector codes |
| `e_alibi_unexplained` | share of staff accesses to the case's accounts that Alibi could not explain | the accesses |
| `e_off_roster` | share of those accesses outside any rostered shift | the accesses |
| `e_record_systems` | distinct source systems behind the case's events (payments, staff audit, core banking, digital banking, sessions, account opening, IAM, service desk) | the systems |
| `e_max_strength` | the strongest single signal's strength | the detector and its events |

## The ablation

"M7 without detector features" (`M7-structure`) drops the evidence family and keeps the 25 graph
and sequence features. If M7's lead over the rules came only from re-reading the detectors, this row
would fall to rule level. It doesn't (see [rule_baseline.md](rule_baseline.md)). Structure and timing
carry most of the signal, and detector evidence mainly adds precision.

## What the model leans on

Mean |TreeSHAP| over the training cases, from `ml/reports/fin04_eval.json` after `make train`:

| Family | M7 | M7 without detector features |
|---|---|---|
| Evidence | 47% | — |
| Graph | 27% | 58% |
| Sequence | 26% | 42% |

The largest single feature carries 27% (`e_max_strength`). CI fails if any one feature carries more than
60% (`test_m7_metric_floors_and_no_single_feature_shortcut`).
