# Labeling assumptions

How SUTRA turns the simulator's ground truth into labels for M5, M6 and M7, and for the FIN-04
evaluation against the rule baselines. Code: [`app/ml/cases.py`](../../backend/app/ml/cases.py)
(`label_cases`) and [`app/ml/worlds.py`](../../backend/app/ml/worlds.py).

Every label is **synthetic**. Kestrel-Sim knows which rows it injected for a scenario, so labels are
exact here. A bank has no such oracle: its labels come from closed investigations, and they arrive late,
incomplete and biased towards what was already being looked for. Nothing below is a claim about real
data.

## Where labels come from

Each scenario instance the simulator injects writes one label row: scenario, variant (`suspicious` or
`twin`), typology, and the entities and events it touched
([`scenarios.yaml`](../../data/scenarios/scenarios.yaml) is the human-readable contract).

| World | Seeds | Suspicious instances | Legitimate look-alikes |
|---|---|---|---|
| Training (randomised) | 7, 8, 9, 10 | 12 insider takeovers, each paying into its own 4–9-account mule ring; 5 external takeovers; 3 circular flows; 3 structuring cases | 6 pension-camp twins, 5 new-phone twins, 3 monthly loan loops, 60 Video-KYC openings, 25 single-officer openings, 30 households sharing a phone or device |
| Held-out (randomised) | 11 | as training | as training |
| Demo (hand-built story) | 42 | the 21 Sep insider takeover + its 11-account mule ring + the staff relationship, 1 circular flow, 1 structuring case, 1 external takeover | one twin per scenario: pension camp, declared relative, monthly loan, kirana takings, new phone, college fees, salary-day and festival stress |
| Demo + live feed | 42 + 22 Sep | as demo, plus a second insider takeover that pays into the same ring | as demo, plus a legitimate pension camp |

The S9 look-alikes (Video-KYC, single-officer, households) existed in training worlds before this
work but carried no label. They are now labelled `S9 twin` with a `lookalike` type, so false positives on
them can be counted. Writing the labels draws no random numbers, so every generated row is unchanged.

The live feed's two strands have no simulator label. `with_live_feed` writes them from the feed itself:
the attack strand's accounts, customers and devices are `S4-live-22sep` (suspicious), and the camp's
customers are `S4-live-camp` (twin).

## The unit: a connected case

M7 and the rule baselines are scored per **connected case**, not per signal or per chain. A case is a
connected component over Needle chains and the signals of 13 seeding detectors (R1–R4, R7–R10, G1–G5),
joined when they share an account, customer, resolved person, device or external counterparty.

- **Employees never join cases.** One officer touches hundreds of accounts in a quarter. Linking through
  staff would merge every customer they served. An employee shared by two cases becomes a link between
  them (`g_linked_cases`), not a merge.
- **Hubs are cut.** The cash and ATM sinks, and any entity in more than 40 nodes, do not join cases.
- **Behavioural signals attach, never seed.** R5, R6, M1 and M2 describe a person or session, so they
  attach to the cases whose accounts or chain sessions they touch.

## Case labels

A case's label comes from the labelled instances whose entities it shares. Matching uses accounts,
customers and devices only, never employees: an insider also does ordinary work, and that work is not
part of the scheme.

| Label | Rule | y |
|---|---|---|
| `suspicious` | shares an entity with at least one suspicious instance | 1 |
| `lookalike` | shares an entity with a twin or look-alike instance, and with no suspicious one | 0 |
| `background` | shares no labelled entity | 0 |

Consequences, accepted deliberately:

- **A ring can appear as several cases.** When a mule ring's accounts never connect to the takeover
  (no shared payee, no G4 burst), each fragment is its own suspicious case. It counts once per case,
  which is how an investigator would meet it in the queue. Typology `MULE_FACTORY` on its own marks
  these fragments.
- **A case can merge two rings.** Two insiders whose rings share accounts form one case labelled with
  both instances. That case is one investigation.
- **Background is not proof of innocence.** It means "no injected scheme here". The baseline simulator
  produces unusual but legitimate behaviour (night logins, salary-day fan-out, limit raises), and that
  is the point: those cases are true negatives that look odd.

## Cross-validation groups

Every split in training and evaluation is grouped (`StratifiedGroupKFold`). A union-find over cases
and labelled instances gives each case a group. Cases tied together by ground truth always share a
fold: a takeover and its mule ring, two fragments of one ring, rings that share accounts. Unlabelled
cases are their own group. For M5 and M6, a chain or account takes the group of the case that holds it.
The assertion `grouped_folds` makes on every split, and `test_grouped_folds_never_split_a_group`, keep
that property true.

## Time

- **Event time only.** Labels and features use when things happened (`occurred_at`, `added_at`,
  `opened_at`), never arrival time (`ingested_at`).
- **The later-events cutoff is 2 Sep 2026** (day 70 of the 90-day window). Past-only models learn from
  training cases whose last event is before it. The later-events test set holds held-out cases with any
  event on or after it, including the case the 22 Sep feed extends.

## Known limits

- Scenario instances are drawn from a small number of templates, so a model can learn template
  regularities that real fraud would not share. The twins and look-alikes exist to make that harder,
  and the "M7 without detector features" ablation shows how much rests on structure and timing alone.
- The demo world has only 4 suspicious cases. Its numbers are reported inside the held-out set and
  are never quoted on their own.
- Labels are binary. Typology is kept for per-typology recall but is not a training target.
