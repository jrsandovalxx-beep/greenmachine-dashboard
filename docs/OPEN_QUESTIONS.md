# GreenMachine — Open Questions Register

Live register of unresolved requirements. **Closed questions are never deleted** — they are
marked closed with the approved answer and a decision date, because the reasoning behind a
decision is as valuable as the decision.

Statuses: `OPEN` · `CLOSED` · `DEFERRED`
Owners: **PO** (Product Owner) · **ENG** (Principal Engineer)

**Specification version:** v6.3 — Foundation Clarifications. Q25, Q26, Q27, Q28, and Q30 were
closed by this amendment on 2026-07-22 and moved to the Closed section, retained in full.

---

## Closed

### Q1 — Meaning of the category numbers and the aggregation formula
| | |
|---|---|
| **Status** | CLOSED |
| **Owner** | PO |
| **Decision date** | 2026-07-22 |
| **Tickets affected** | GM-002, GM-003, GM-006 |

**Answer.** The numbers are **category maximum points**. Maximum total is **12**: Power Profile
3, Pitcher Matchup 3, Form 2, Pull Power 2, Environment 2. Each scored component carries a
configurable `max_points`. Metric score = points from the highest qualifying bucket; category
score = sum of its metric scores; total = sum of category scores. No averaging, no rescaling,
no dynamic normalization. Config validation enforces: metric `max_points` sum to category
maximum; category maximums sum to 12; metric ≤ `max_points`; category ≤ category maximum;
total ≤ 12. (MODEL_SPEC §2–3.)

---

### Q2 — Unit of evaluation
| | |
|---|---|
| **Status** | CLOSED |
| **Owner** | PO |
| **Decision date** | 2026-07-22 |
| **Tickets affected** | GM-002, GM-006, GM-007 |

**Answer.** One batter, in one game, against the **expected starting pitcher**, using one
frozen grading-time input snapshot, under **one selected window profile**. Identity preserves
`game_id`, `batter_id`, `expected_starting_pitcher_id`, `snapshot_id`, `model_version`,
`config_hash`, `window_profile`. A pitcher change creates a new snapshot and a new evaluation
that supersedes the earlier one; both are preserved. Bullpen games use the announced opener or
expected starter known at snapshot time, with the role recorded as `opener`,
`expected_starter`, or `uncertain`. (MODEL_SPEC §6.)

---

### Q3 — Output contract, score range, and grade cutoffs
| | |
|---|---|
| **Status** | CLOSED |
| **Owner** | PO |
| **Decision date** | 2026-07-22 |
| **Tickets affected** | GM-002, GM-003, GM-006 |

**Answer.** Score range 0–12. Grades: S `[10,12]`, A `[8,10)`, B `[6,8)`, C `[4,6)`,
D `[0,4)`. Cutoffs live in configuration and are applied to the internal deterministic score
before presentation rounding. Evaluation status is `EVALUATED` or `NOT_EVALUABLE`;
`NOT_EVALUABLE` is distinct from Grade D and receives no score and no signal. A signal engine
(`STRONG_BET`, `LEAN`, `PASS`, `AVOID`) resolves in strict priority order. (MODEL_SPEC §13–15.)

---

### Q4 — Validation Layer semantics
| | |
|---|---|
| **Status** | CLOSED |
| **Owner** | PO |
| **Decision date** | 2026-07-22 |
| **Tickets affected** | GM-002, GM-006 |

**Answer.** **Advisory only.** It awards no points, removes no points, caps no grade, vetoes no
evaluable result, changes no signal, and reweights no category. It sits beside the scored
result as structured, auditable findings. Free-text bullpen notes must never become hidden
numerical scoring. (MODEL_SPEC §10.)

---

### Q5 — Missing-data policy
| | |
|---|---|
| **Status** | CLOSED |
| **Owner** | PO |
| **Decision date** | 2026-07-22 |
| **Tickets affected** | GM-002, GM-003, GM-006 |

**Answer.** Missing data is explicitly modeled with typed reasons. Zero, `NaN`, and ambiguous
`None` are prohibited inside domain and scoring objects. No dynamic reweighting, no silent
cross-window substitution, no silent season fallback. Metric-level source fallbacks are allowed
only where explicitly defined. Unresolved required data → `NOT_EVALUABLE`. `insufficient_sample`
is a distinct condition from missing. (MODEL_SPEC §8.)

---

### Q6 — Weather: forecast or observed
| | |
|---|---|
| **Status** | CLOSED |
| **Owner** | PO |
| **Decision date** | 2026-07-22 |
| **Tickets affected** | GM-006 |

**Answer.** Weather uses the **exact forecast available at grading time**, frozen into the
snapshot at or before `as_of`, under both window profiles. Observed post-game weather never
enters an evaluation. (MODEL_SPEC §12, §16.)

---

### Q8 — Backtest ground truth
| | |
|---|---|
| **Status** | CLOSED |
| **Owner** | PO |
| **Decision date** | 2026-07-22 |
| **Tickets affected** | GM-006, GM-007 |

**Answer.** Primary initial outcome: **whether the batter hit at least one home run in the
evaluated game.** Outcomes are stored separately from pregame evaluations and never mutate
them. (MODEL_SPEC §17.)

---

### Q10 — Deployment target
| | |
|---|---|
| **Status** | CLOSED |
| **Owner** | PO |
| **Decision date** | 2026-07-22 |
| **Tickets affected** | GM-001 |

**Answer.** Local, single-user Streamlit research dashboard. Stack direction: Python,
Streamlit, Pydantic, pytest, SQLite, pandas (ingestion/feature assembly only), Plotly
(presentation), pybaseball or direct first-party access. The domain and scoring core must not
depend on any of these. Architecture preserves later scheduling or hosted deployment without
building distributed infrastructure now. (MODEL_SPEC via amendment §23; ARCHITECTURE §9.)

---

### Q25 — May `max_points` differ per window profile?
| | |
|---|---|
| **Status** | CLOSED |
| **Owner** | PO |
| **Decision date** | 2026-07-22 (v6.3) |
| **Tickets affected** | GM-003, GM-004 |

**Raised by** engineering during the v6.2 correction pass.

**Answer.** **No — allocations are profile-invariant.** `RECENT_7D` and `LONG_TERM_2Y` may differ
in bucket thresholds, minimum sample requirements, actual sample counts, and data coverage. They
may **not** differ in component `max_points`, category maximums, total maximum score, or grade
cutoffs. Configuration validates **one** allocation structure shared by both profiles, and the
sum-to-category-maximum check runs once, not per profile. This is the engineering recommendation
as given: a shared scale keeps a recent grade and a long-term grade comparable. (MODEL_SPEC §2.1,
§19; ADR-0005.)

---

### Q26 — "Strong category" at 75% with integer point allocations
| | |
|---|---|
| **Status** | CLOSED |
| **Owner** | PO |
| **Decision date** | 2026-07-22 (v6.3) |
| **Tickets affected** | GM-003, GM-005 |

**Raised by** engineering: with integer points, 75% of a 3-point category requires 2.25, i.e.
exactly 3, so "strong" collapsed to "perfect".

**Answer.** **Fractional points are allowed and expected**, which dissolves the problem. The
strong-category rule is unchanged: `category_score >= category_max_points × 0.75`. A 3-point
category is strong at **2.25 or above**; a 2-point category at **1.50 or above**. No rounding
occurs before bucket qualification, category aggregation, total aggregation, grade assignment,
strong-category comparison, or signal assignment. Presentation rounding is separate and never
affects model behavior. This is what makes the Decimal policy mandatory rather than tidy — see
ADR-0002. (MODEL_SPEC §3.1, §16.)

---

### Q27 — `AVOID` precedence over `STRONG_BET`
| | |
|---|---|
| **Status** | CLOSED |
| **Owner** | PO |
| **Decision date** | 2026-07-22 (v6.3) |
| **Tickets affected** | GM-003, GM-006 |

**Raised by** engineering: a reachable line (Power Profile 1, all else maximal) yields Grade S
with signal `AVOID`.

**Answer.** **The priority is intentional.** `AVOID` → `STRONG_BET` → `LEAN` → `PASS`, first
match wins. A high total grade can still receive `AVOID` when Power Profile ≤ 1. The grade
reports the total score; the signal applies the prioritized decision rules. The pairing must be
presented with its **override reason**, e.g. `power_profile_veto`, in both the interface and the
audit trail, so it never reads as a defect. Override reason codes belong in configuration.
(MODEL_SPEC §16.1.)

---

### Q28 — 15% pitch-usage qualification threshold
| | |
|---|---|
| **Status** | CLOSED |
| **Owner** | PO |
| **Decision date** | 2026-07-22 (v6.3) |
| **Tickets affected** | GM-003 |

**Answer.** The default qualifying threshold is **15%**, and it is **model configuration** —
changing it requires a new model configuration version. The denominator is **all pitches thrown
by the expected starting pitcher to batters using the evaluated hitter's relevant batting
side**, over the **current season through `as_of`**. Pitch types remain separate during MVP;
fastball families are not grouped. (MODEL_SPEC §12.1.)

---

### Q30 — Slate date, doubleheaders, and game identity
| | |
|---|---|
| **Status** | CLOSED |
| **Owner** | PO |
| **Decision date** | 2026-07-22 (v6.3) |
| **Tickets affected** | GM-002, GM-006 |

**Answer.** The **official provider's unique game identifier is the canonical `game_id`**; no
replacement internal ID is generated when one exists. Doubleheader games have separate official
IDs. `slate_date` is the **official scheduled MLB date**, never derived from UTC. Scheduled
start time is stored in **UTC**, alongside venue-local scheduled time and venue timezone. A
postponed or rescheduled game follows official provider identity; a suspended and resumed game
retains its official ID. A new grading-time snapshot and evaluation are created whenever the
game reappears on a slate or relevant pregame context changes.

**Residual:** which provider is "official" is decided by Q23. The domain type is unaffected —
an opaque identifier plus its `provider_id` — so this does not block GM-002. (MODEL_SPEC §7.2.)

---

### Q31 — Which game types are eligible for a window
| | |
|---|---|
| **Status** | CLOSED |
| **Owner** | PO |
| **Decision date** | 2026-07-24 (GM-020 ruling) |
| **Tickets affected** | GM-020 |

**Answer.** **Regular season only.** Only events with `game_type == "R"` are eligible for either
window profile. Spring training, exhibition, All-Star, and postseason events are excluded, and
every exclusion is **counted by type** in the normalization report rather than silently dropped.
A **missing** game type is never treated as regular season — it is excluded and counted
separately. The provider request narrows to regular season at the source *and* the normalizer
re-enforces the rule after parsing, so a provider-side filter change cannot widen the window
unnoticed.

**Implemented:** `ingestion/events.py`; audited in `reports/normalization_*.json`.

---

### Q32 — Denominator for Pull % on air balls
| | |
|---|---|
| **Status** | CLOSED (initial denominator frozen; revisable with evidence) |
| **Owner** | PO |
| **Decision date** | 2026-07-24 (GM-020 ruling) |
| **Tickets affected** | GM-020 |

**Answer.** The frozen initial denominator is **`fly_ball` + `line_drive`** batted-ball events
with a valid batting stand and usable hit coordinates. Pull is classified per row from **that
row's own `stand`** value, which is correct for switch hitters, using exact Decimal geometry
with `TAN_15_DEGREES = 0.26794919243112270647` and the boundary **inclusive on the pull side**.

Alternative denominators — fly-ball only, fly + line drive + popup, and overall pull across all
batted balls — are computed and published in `reports/pull_audit_*.json` so the choice can be
revisited against real data. Those alternatives are **audit-only and never enter a snapshot**.
Overall Pull % is likewise report-only and is not a scored component.

**Residual:** revisiting the denominator later is a model-configuration decision, not a code
change; the audit report exists so the decision can be made on evidence.

---

### Q33 — Expected starting pitcher when the provider signals an opener or uncertainty
| | |
|---|---|
| **Status** | CLOSED |
| **Owner** | PO |
| **Decision date** | 2026-07-24 (GM-020 ruling) |
| **Tickets affected** | GM-020 |

**Answer.** The provider's own note governs the recorded role. An announced opener maps to
`PitcherRole.OPENER`; an uncertainty marker (for example "TBD", "likely", "expected to") on a
**named** pitcher maps to `PitcherRole.UNCERTAIN`; an ordinary probable maps to
`PitcherRole.EXPECTED_STARTER`. If no pitcher is identified at all, the run is an **eligibility
failure** — no placeholder or fabricated pitcher is ever created, and no snapshot is produced.
A changed probable pitcher is a new capture producing new snapshots, never an edit to an
existing one.

**Residual:** whether an `OPENER` should alter scoring is a Sprint 2+ model question; GM-020
only records the role faithfully.

---

## Open — blocking

### Q11 — Final per-metric `max_points` allocations
| | |
|---|---|
| **Status** | OPEN · blocking production config |
| **Owner** | PO |
| **Blocks** | first production model configuration version; does **not** block GM-003 schema work |
| **Tickets affected** | GM-003, GM-004, GM-008 |

Within each category, how are the category maximum points distributed across its components?

Constraints now fixed by v6.3: allocations are **profile-invariant** (one shared structure, not
one per profile, Q25), **fractional values are permitted and expected** (Q26), component
`max_points` sum exactly to the category maximum, and the strongest qualifying bucket of each
component awards exactly its `max_points`. Engineering will build and test the schema against
synthetic fixture configurations only.

### Q12 — Final bucket thresholds for `RECENT_7D`
| | |
|---|---|
| **Status** | OPEN · blocking production config |
| **Owner** | PO |
| **Blocks** | first production model configuration version |
| **Tickets affected** | GM-003, GM-008 |

Ordered boundaries, per-bucket points, and declared domain for every windowed component under
the 7-day profile. Under v6.3 the `attack_angle_quality` component additionally needs
**measurement-specific** bucket sets: `ideal_attack_angle_pct` buckets may not be applied to
`attack_angle_threshold_proxy` unless explicitly configured for it.

### Q13 — Final bucket thresholds for `LONG_TERM_2Y`
| | |
|---|---|
| **Status** | OPEN · blocking production config |
| **Owner** | PO |
| **Blocks** | first production model configuration version |
| **Tickets affected** | GM-003, GM-008 |

As Q12, for the 2-year profile. Distributions differ from 7-day, so these are expected to be
different values, not copies.

### Q14 — Minimum sample sizes by metric and profile
| | |
|---|---|
| **Status** | OPEN · blocking production config |
| **Owner** | PO |
| **Blocks** | `sample_status` resolution in production |
| **Tickets affected** | GM-003, GM-006 |

Per component **and** per window profile, in the component's own sample type.

**Scope reduced by v6.3.** An insufficient sample no longer withholds a score: a valid value is
still scored, labeled `SampleStatus.INSUFFICIENT`, and raised as an advisory Validation Layer
warning (MODEL_SPEC §8.2). These thresholds therefore govern the label and the warning, not
whether a component scores. That lowers the urgency: a wrong threshold now mislabels rather
than silently changes a grade.

**GM-020 status.** The ingestion slice **injects** a sample-minimum policy and provides **no
default anywhere in `src/`** — a run cannot silently adopt an invented minimum. Validation uses
a clearly labeled non-production fixture policy that carries its own disclaimer and is to be
replaced the moment this question is answered.

### Q15 — Pitch Mix Pressure formula
| | |
|---|---|
| **Status** | OPEN · blocking |
| **Owner** | PO |
| **Blocks** | Sprint 2 scoring, GLOSSARY completion |
| **Tickets affected** | GM-002, GM-003 |

Exact baseball formula, batter-versus-pitch measurement, unit, domain, and direction.

### Q16 — Put-Away Pitch Exploitation formula
| | |
|---|---|
| **Status** | OPEN · blocking |
| **Owner** | PO |
| **Blocks** | Sprint 2 scoring, GLOSSARY completion |
| **Tickets affected** | GM-002, GM-003 |

Exact baseball formula, unit, domain, and direction. Selection rules for the primary put-away
pitch are already approved (MODEL_SPEC §11).

**GM-020 status (Q15 and Q16).** Both composites are emitted as **missing** with
`MissingReason.SOURCE_UNAVAILABLE` — an interim mapping, documented as such, chosen because no
formula exists to compute them. The slice does capture and publish the transparent underlying
**ingredients** per batting stand and pitch type (usage %, two-strike counts, putaway finishes)
in `reports/pitcher_ingredients.json`, so whichever formulas are approved can be evaluated
against real captured data. **No composite value is invented.**

---

## Open — non-blocking for Sprint 1

### Q17 — Park-factor source and bucket threshold
| | |
|---|---|
| **Status** | OPEN |
| **Owner** | PO |
| **Blocks** | Environment scoring configuration |
| **Tickets affected** | GM-003 |

Which published or derived rolling-three-year, handedness-adjusted HR park factor, on what
scale, and what threshold earns the 1 point?

### Q18 — Exact wind-alignment cosine threshold
| | |
|---|---|
| **Status** | OPEN |
| **Owner** | PO |
| **Blocks** | Environment scoring configuration |
| **Tickets affected** | GM-003 |

What cosine (or vector-alignment) value between TO-wind direction and pull-field bearing counts
as "toward the pull field"? Also needed: the stadium-orientation reference data source.

### Q19 — Savant structured endpoint availability
| | |
|---|---|
| **Status** | OPEN · research |
| **Owner** | ENG (research) → PO (approval) |
| **Blocks** | Savant ingestion adapter design |
| **Tickets affected** | GM-020 (deferred) |

Does an official export, structured endpoint, or embedded structured page datum expose the
Ideal Attack Angle aggregate directly? Determines whether Priority 2 extraction is needed.

### Q20 — Savant historical Attack Angle coverage
| | |
|---|---|
| **Status** | OPEN · research |
| **Owner** | ENG (research) → PO (approval) |
| **Blocks** | maximum backtest depth at full fidelity |
| **Tickets affected** | GM-020 (deferred) |

How far back does tracked attack-angle data exist, and for what share of the player population?

### Q21 — Exact configured Attack Angle proxy definition
| | |
|---|---|
| **Status** | OPEN |
| **Owner** | PO |
| **Blocks** | Priority-4 fallback |
| **Tickets affected** | GM-003, GM-020 |

Exact thresholds, formula, and units for the `attack_angle_threshold_proxy` **measurement** of
the `attack_angle_quality` component, plus its own bucket set. To be researched and backtested.
Must never be labeled as Savant Ideal Attack Angle %, and must not borrow the ideal-percentage
buckets.

### Q22 — Long-term Bat Speed coverage adequacy
| | |
|---|---|
| **Status** | OPEN |
| **Owner** | PO |
| **Blocks** | `LONG_TERM_2Y` Form completeness |
| **Tickets affected** | GM-003 |

Is bat-tracking coverage sufficient for a rolling two-year swing sample? If not, what is the
approved behavior — `tracking_unavailable`, or a profile-specific configuration?

### Q23 — Final data providers
| | |
|---|---|
| **Status** | OPEN |
| **Owner** | PO |
| **Blocks** | ingestion adapters (Sprint 3+) |
| **Tickets affected** | GM-020 (deferred), future ingestion tickets |

Providers for Statcast events, pitch-level data, probable pitchers and lineups, weather
forecasts, and park factors — plus access limits and permitted historical bulk retrieval.

**Residual dependency from Q30.** Q30 closed by designating "the official provider's unique game
identifier" as the canonical `game_id`. Which provider is *official* is decided here. The domain
type is unaffected (an opaque identifier plus its `provider_id`), so this does not block GM-002,
but the concrete identifier space cannot be fixed until Q23 closes.

### Q24 — Backtest odds and ROI data sources
| | |
|---|---|
| **Status** | OPEN |
| **Owner** | PO |
| **Blocks** | ROI-based research (post-MVP) |
| **Tickets affected** | future research tickets |

Which historical odds source, at what timestamp relative to first pitch, and stored where?
Odds are outcome-adjacent data and must live outside evaluations.

### Q9 — Required backtest depth
| | |
|---|---|
| **Status** | OPEN |
| **Owner** | PO |
| **Blocks** | degraded-mode policy for limited-history metrics |
| **Tickets affected** | GM-006 |

How far back must full-fidelity backtesting reach? Interacts with Q20 and Q22: some metrics
cannot exist before their tracking era, so a documented degraded mode may be required.

### Q7 — Data source licensing and access constraints
| | |
|---|---|
| **Status** | OPEN (partially answered) |
| **Owner** | PO |
| **Blocks** | ingestion design |
| **Tickets affected** | GM-020 (deferred) |

Direction given (pybaseball / first-party access); specific licensing terms, rate limits, and
permitted bulk historical retrieval remain unconfirmed. Superseded in part by Q23.

---

## Open — raised by engineering

These surfaced while reconciling amendments. Q25–Q28 and Q30 were raised here and have since
been closed by specification v6.3; they are retained in the Closed section above.

### Q29 — Window agreement definition
| | |
|---|---|
| **Status** | OPEN · non-blocking |
| **Owner** | PO |
| **Tickets affected** | future presentation tickets |

What exactly produces "Strong / Moderate / Weak" agreement — grade distance, score distance, or
signal concordance? Research context only; no scoring impact. Computed in `reporting` over two
independently stored `GradeResult`s from two profile-specific snapshots, never inside the core.
