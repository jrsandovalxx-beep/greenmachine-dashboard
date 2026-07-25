# GreenMachine — Model Specification

**Specification version:** GreenMachine Model Specification **v6.3 — Foundation Clarifications**
**Supersedes:** v6.2 (2026-07-22)
**Status:** Approved by Product Owner, 2026-07-22
**Owner:** Product Owner

This document is the **authoritative source for baseball and grading behavior**. Engineering
implements what is written here; engineering does not change it.

- Product and baseball behavior → **this document**
- Engineering structure → `ARCHITECTURE.md`
- Precise metric definitions → `GLOSSARY.md`
- Unresolved decisions → `OPEN_QUESTIONS.md`

Nothing in this document may be re-specified in Python. All numeric rules stated here are
expressed in configuration.

---

## 1. Specification lineage

`v6.3` is a **product-specification version**. It is not a code SemVer and not a model
configuration SemVer. See `ARCHITECTURE.md` §2 for the four version streams.

**v6.2** introduced bucketed scoring, a simplified Form category, the `RECENT_7D` and
`LONG_TERM_2Y` window profiles, and the Savant Ideal Attack Angle sourcing strategy.

**v6.3 — Foundation Clarifications** adds:

- Profile-specific snapshots linked by `source_capture_id`
- Profile-invariant point allocations
- Fractional points, with no rounding anywhere in the grading path
- A complete Decimal numeric policy
- The `attack_angle_quality` component with mutually exclusive measurements
- Generic `provider_id` + `acquisition_method` provenance
- `SampleStatus` separated from `MissingReason`, with insufficient samples still scored
- Point-in-time eligibility taking precedence over source priority
- Explicit configuration monotonicity and point invariants
- Canonical game identity and the pitch-usage denominator

---

## 2. Categories and maximum points

**Maximum total score: 12 points.**

| Category | Category maximum | Scored components |
|---|---:|---|
| Power Profile | 3 | Exit Velocity, Barrel %, Hard Hit % |
| Pitcher Matchup | 3 | Pitch Mix Pressure, Put-Away Pitch Exploitation |
| Form | 2 | Sweet Spot %, **Attack Angle Quality**, Bat Speed |
| Pull Power | 2 | Pull % on Air Balls |
| Environment | 2 | Park (max 1), Weather (max 1) |
| **Total** | **12** | |
| Validation Layer | 0 | advisory only — see §10 |

Form still has exactly three scored components. `attack_angle_quality` replaces the former
`ideal_attack_angle_pct` **component**; the Savant percentage is now one of its two permitted
*measurements* (§9). No new scored component is added.

**Removed from Form and not to be reintroduced:** Chase Rate, Zone Contact %, Whiff Rate.

### 2.1 Profile-invariant allocations

Per-component `max_points` and category maximums are **profile-invariant**.

| May differ between `RECENT_7D` and `LONG_TERM_2Y` | May **not** differ |
|---|---|
| Bucket thresholds | Component `max_points` |
| Minimum sample requirements | Category maximums |
| Actual sample counts | Total maximum score (12) |
| Data coverage | Grade cutoffs |

Configuration validates **one** allocation structure shared by both profiles.

---

## 3. Score aggregation

```
component score = points awarded by the highest qualifying bucket
category score  = sum of component scores within the category
total score     = sum of all category scores
```

Prohibited: averaging component scores, averaging category scores, rescaling after
calculation, and dynamic normalization or reweighting because data is missing.

### 3.1 Fractional points

**Fractional points are allowed and expected.** Allocations, bucket point values, category
scores, and totals may be non-integer.

**No rounding occurs before any of:** bucket qualification, category aggregation, total
aggregation, grade assignment.

Presentation rounding is a separate, downstream concern and never affects model behavior.

**Exact per-component point allocations are configurable and are NOT yet final** (Q11).
Production allocations must not be invented by engineering.

---

## 4. Numeric policy

Binding on every layer that touches a value entering scoring.

- **Decimal** is used for thresholds, metric values entering scoring, point values, category
  totals, and total scores
- **Never construct a Decimal from a binary float**
- Construct Decimals from **provider strings, configuration strings, or integers**
- A project-local Decimal context with **precision 28** and **`ROUND_HALF_EVEN`** governs all
  grading arithmetic
- Derived ratios and percentages are computed under that declared context
- Derived values are **not quantized** before scoring
- **No rounding** before bucket or grade comparisons
- Presentation rounding occurs **outside** the grading core
- Canonical serialization represents Decimal values as deterministic **base-10 strings**, never
  binary floats

### 4.1 Interval conventions

**Scoring buckets are half-open `[lower, upper)`.** A value equal to a shared boundary belongs
to the **upper** bucket. The terminal bucket is **closed** at the domain maximum.

**The Savant Ideal Attack Angle event predicate is independently inclusive at both 5 and 20.**
It is an event-level eligibility rule from an external definition, not a scoring bucket, and it
must not share an implementation with the bucket helper. See ADR-0002.

---

## 5. Scoring methods

MVP supports exactly two methods, with **separate validated schema shapes**:

| Method | Use | Schema shape |
|---|---|---|
| `bucketed` | Default for continuous baseball metrics | Ordered bucket boundaries over a declared domain |
| `binary` | Genuine yes/no conditions only | A qualification predicate and its point award; **not** forced to declare continuous bucket ranges |

Every scored component declares in configuration: `component_id`, `scoring_method`,
`direction` (`higher_is_better` | `lower_is_better`), `max_points`, `sample_type`,
`minimum_sample_required`, missing-data behavior, and applicable window profiles.
Bucketed components additionally declare a domain, ordered boundaries, and per-bucket points.

### 5.1 Bucketed scoring rules

- The **highest qualifying bucket wins**; bucket points are **not cumulative**
- Bucket sets are **exhaustive and non-overlapping** across the declared domain
- Edge behavior is deterministic under §4.1

### 5.2 Fuzzy scoring

Disabled for bucketed metrics. May remain an optional future capability for binary boundaries
only. Defaults to disabled. **Not implemented in Sprint 1.**

---

## 6. Window profiles and snapshots

### 6.1 The two profiles

| Profile | Display name | Window |
|---|---|---|
| `RECENT_7D` | Recent — Last 7 Days | Eligible events in the 7 days immediately preceding `as_of` |
| `LONG_TERM_2Y` | Long-Term — Rolling 2 Years | Eligible events between `as_of − 2 calendar years` and `as_of` |

`RECENT_7D` applies to: Exit Velocity, Barrel %, Hard Hit %, Sweet Spot %, Attack Angle
Quality, Bat Speed, Pull % on Air Balls.

`LONG_TERM_2Y` applies primarily to batted-ball-event components: Exit Velocity, Barrel %,
Hard Hit %, Sweet Spot %, Attack Angle Quality, Pull % on Air Balls. Bat Speed may use a
rolling two-year **swing-level** sample where tracked data exists, and is always labeled a
swing sample.

**Profile-invariant components:** Pitcher Matchup (season-based), Park (rolling three years),
Weather (grading-time forecast snapshot) resolve identically under both profiles.

### 6.2 One snapshot, one profile

> **An `InputSnapshot` represents exactly one `WindowProfile`.**

```
RECENT_7D InputSnapshot     →  RECENT_7D GradeResult
LONG_TERM_2Y InputSnapshot  →  LONG_TERM_2Y GradeResult
```

A single `InputSnapshot` may **never** contain or produce both profiles.

**One source capture may produce two independently frozen profile-specific snapshots.** Two
snapshots created during the same grading run may share a `source_capture_id`, which ties them
to the same source-data collection operation. They must nevertheless have distinct:

- `snapshot_id`
- `input_hash`
- `window_profile`
- `window_start`
- `window_end`
- metric observations

**Profile comparison occurs over the two independently stored `GradeResult`s**, never within a
snapshot and never inside the grading core.

### 6.3 Profile separation rules

Prohibited: averaging profiles, blending them, silently substituting one for the other, using
the two-year value as an automatic fallback for a seven-day value, and producing a hybrid grade
unless a future approved model version explicitly defines one.

Configuration supports **profile-specific** bucket definitions and minimum-sample requirements
without Python changes. Allocations remain profile-invariant (§2.1).

### 6.4 Window agreement

The dashboard will eventually toggle between profiles and support side-by-side comparison:

```
Recent Grade:     A
Long-Term Grade:  S
Window Agreement: Strong
```

Window agreement is **research context only** — not a scored category, not a point adjustment,
not a veto. Its exact definition is open (Q29).

---

## 7. Evaluation unit and game identity

### 7.1 Evaluation unit

> One batter, in one game, against the expected starting pitcher, using one frozen
> profile-specific input snapshot, under one selected window profile.

Evaluation identity preserves at least: `game_id`, `batter_id`,
`expected_starting_pitcher_id`, `snapshot_id`, `model_version`, `config_hash`,
`window_profile`.

**Expected starting pitcher changes:** create a new snapshot and a new evaluation. Never
overwrite. The newer evaluation supersedes the earlier; both are preserved.

**Bullpen games:** use the announced opener or expected starter known at snapshot time. Record
the pitcher role as `opener`, `expected_starter`, or `uncertain`. History is never revised
after the game.

### 7.2 Canonical game identity

- The **official provider's unique game identifier is the canonical `game_id`**
- **No replacement internal game ID is generated** when an official canonical identifier exists
- Doubleheader games have **separate** official game IDs
- `slate_date` is the **official scheduled MLB date**, never a date derived from UTC
- Scheduled start time is stored in **UTC**, alongside the **venue-local scheduled time** and
  the **venue timezone**
- A postponed or rescheduled game follows the official provider identity
- A suspended and resumed game **retains** its official game ID
- A new grading-time snapshot and evaluation are created whenever the game reappears on a slate
  or relevant pregame context changes

---

## 8. Sample types, sample status, and missing data

### 8.1 Sample types

Every component input identifies its true denominator. Supported sample types:
`batted_ball_events`, `swings`, `air_balls`, `plate_appearances`, `pitches`, `games`.

| Component | Sample type |
|---|---|
| Exit Velocity, Barrel %, Hard Hit %, Sweet Spot % | `batted_ball_events` |
| Attack Angle Quality | valid tracked contact / batted-ball events with a recorded attack angle (measurement-dependent) |
| Bat Speed | qualifying `swings` |
| Pull % on Air Balls | `air_balls` |

**A single generic sample count must never be used across components.**

### 8.2 SampleStatus and MissingReason are different types

```
SampleStatus:   SUFFICIENT | INSUFFICIENT
```

```
MissingReason:  NO_EVENTS_IN_WINDOW | SOURCE_UNAVAILABLE | TRACKING_UNAVAILABLE
                PLAYER_NOT_COVERED  | INVALID_SOURCE_VALUE | EXPECTED_PITCHER_UNKNOWN
                WEATHER_UNAVAILABLE | UNSUPPORTED_HISTORICAL_PERIOD
```

> **`INSUFFICIENT` is not a `MissingReason`.**

**Approved MVP behavior:**

- A valid metric value with an insufficient sample **is still scored**
- It carries `SampleStatus.INSUFFICIENT`
- It creates an **advisory sample warning** in the Validation Layer
- It remains visible in the audit trail
- **Zero eligible events, or an unavailable value, is missing** — not insufficient
- Missing required data, after all approved source fallbacks, may produce `NOT_EVALUABLE`

**Never treat an insufficient sample as zero, or as automatically missing.**

Minimum-sample thresholds are configurable and not yet defined (Q14). They govern the
`SampleStatus` label and the advisory warning; they do **not** gate scoring.

### 8.3 Missing-data representation

Prohibited: zero as a missing value, `NaN` inside domain or scoring objects, ambiguous `None`,
dynamic category reweighting, silent cross-window substitution, silent season fallback.

**Component-level source fallbacks** are permitted only where explicitly defined — for example
the attack-angle measurement hierarchy in §9. That is categorically different from replacing
`RECENT_7D` with `LONG_TERM_2Y`, which is never permitted.

A partial 12-point score must never be manufactured by removing or reweighting unavailable
components.

### 8.4 Observation record

Every metric observation preserves: `component_id`, `measurement_id`, `window_profile`,
`window_start`, `window_end`, `as_of`, raw value, `unit`, `sample_type`, `sample_count`,
`minimum_sample_required`, `sample_status`, `data_coverage` status, `provider_id`,
`acquisition_method`, `source_as_of`, retrieval timestamp, `source_capture_id`,
`fallback_used`, the bucket configuration used, and `missing_reason` where applicable.

---

## 9. Attack Angle Quality

### 9.1 Component and measurements

The scored **component** is separated from the **measurement** used to satisfy it.

```
component_id:    attack_angle_quality
measurement_id:  ideal_attack_angle_pct  |  attack_angle_threshold_proxy
```

**Exactly one measurement may satisfy the component in a given evaluation.** It is prohibited
to score both, average both, blend both, label the proxy as Savant Ideal Attack Angle %, or
apply Ideal Attack Angle percentage buckets to the proxy unless buckets are explicitly
configured for that measurement.

### 9.1.1 The `measurement_id` convention

`measurement_id` exists to distinguish measurements a component could otherwise confuse, so
`attack_angle_quality` is the **only** component with declared measurement identifiers. Every
record carrying a `component_id` also carries a single `measurement_id` slot:

| Component | Required `measurement_id` |
|---|---|
| `attack_angle_quality` | **Exactly one** of `ideal_attack_angle_pct` or `attack_angle_threshold_proxy` |
| Every other component | **`None`** |

`None` in this slot has exactly **one** meaning — "this component has no separate measurement
variant; its measurement is the component itself" — and **never** signifies absent or unknown
data. Missing data is a separate representation carrying a `MissingReason` (§8.2).

Both halves are mandatory: `attack_angle_quality` without a measurement is invalid, and any
other component *with* one is invalid. Because the slot holds at most one value, no record can
carry two measurements for one component.

Configuration supports **measurement-specific and profile-specific** bucket definitions.

**Display:** when `ideal_attack_angle_pct` is used, display "Ideal Attack Angle %". When
`attack_angle_threshold_proxy` is used, display "Attack Angle Proxy".

### 9.2 `ideal_attack_angle_pct`

**Definition (Baseball Savant):** an eligible tracked contact event has an Ideal Attack Angle
when its attack angle is **from 5 degrees through 20 degrees, inclusive at both ends**.

```
ideal_attack_angle_pct
  = ( count of valid events with 5 ≤ attack_angle ≤ 20 )
  / ( count of all valid events with a recorded attack_angle )
  × 100
```

Direction: `higher_is_better`. This replaces the previously discussed custom 14°–24° range.
**Raw average attack angle must not be scored as a monotonic higher-is-better metric.** The 5°
and 20° inclusion rules must be tested explicitly at both boundaries.

### 9.3 `attack_angle_threshold_proxy`

Used only when no eligible measurement of `ideal_attack_angle_pct` exists. It uses exact
configured thresholds, is deterministic and auditable, has its own units and definition, is
clearly presented as a proxy, and is never silently mixed with Savant-sourced percentages.
**Proxy thresholds are not yet defined** (Q21).

### 9.4 Acquisition priority, subordinate to point-in-time eligibility

| Priority | `acquisition_method` | Description |
|---|---|---|
| 1 | `direct_aggregate` | Official published aggregate from a stable first-party source |
| 2 | `structured_extract` | Official structured endpoint or embedded structured page data |
| 3 | `rendered_scrape` | Controlled extraction from a rendered leaderboard |
| 4 | `event_derived` | Exact event-level derivation using the §9.2 formula |
| 5 | `configured_proxy` | `attack_angle_threshold_proxy` |

> **Priority is subordinate to eligibility.** See §11.

**Rendered-scrape constraints:** lives only in the provider ingestion adapter, validates
required column names, fails loudly on schema change, records retrieval metadata, preserves the
raw response or a content hash where practical, has fixture-based parser tests, never silently
returns empty or zero, and respects source access limits.

Direct, structured-extract, scraped, derived, and proxy values must remain distinguishable in
backtesting.

---

## 10. Provider provenance

Provider-specific **parsing vocabulary** stays inside ingestion adapters. Core and stored
normalized records carry stable, generic provenance:

```
provider_id:          baseball_savant  (and others, as approved)
acquisition_method:   direct_aggregate | structured_extract | rendered_scrape
                      event_derived    | configured_proxy
```

**Prohibited in domain and scoring models:** provider HTML column names, page-layout details,
parser selectors, and raw endpoint-specific structures.

User-facing source labels are **derived** from `provider_id` plus `acquisition_method`. They
are not stored as a single opaque composite label.

Unavailability is **not** an acquisition method. A component with no eligible measurement is
represented by a `MissingReason` (§8.2).

---

## 11. Point-in-time correctness and source eligibility

### 11.1 Point-in-time correctness

For an evaluation with `as_of` = **T**:

- `RECENT_7D` may include only events before T and within the preceding 7 days
- `LONG_TERM_2Y` may include only events before T and within the preceding 2 years
- Pitcher season data may include only information available before T
- Weather must use the grading-time forecast frozen at or before T
- **No event or observation occurring after T may enter the evaluation**

Historical rolling windows must **never** be recomputed from a current aggregate table. The
eligible event set is stored or reconstructed using event timestamps and point-in-time filters.

When two complete years of data do not exist, preserve requested coverage period, actual
coverage period, coverage percentage or status, source availability, and sample count.
**Partial coverage must remain visible and must never be presented as complete.**

### 11.2 Source eligibility outranks source priority

**The acquisition hierarchy is subordinate to point-in-time correctness.**

An acquisition method is **eligible** only if it can produce:

- the exact selected `WindowProfile`
- the correct `window_start` and `window_end`
- using no observation after `as_of`

> **Choose the highest-priority *eligible* method, not merely the highest-priority *available*
> method.**

Worked examples:

- A current leaderboard aggregate may be **eligible** for today's exact seven-day evaluation
- The same aggregate is **not eligible** for a historical backtest if it cannot reproduce the
  historical `as_of` window
- **Event-level derivation may therefore be the highest eligible method for historical
  evaluations**, even though it is lower in nominal priority

Every fallback decision must record **why each higher-priority method was ineligible**.

---

## 12. Pitcher Matchup rules

Pitcher Matchup remains **season-based** under both window profiles.

### 12.1 Qualifying pitch usage

- Default qualifying threshold: **15%**
- **Denominator:** all pitches thrown by the **expected starting pitcher** to batters using the
  evaluated hitter's relevant batting side
- **Window:** current season through `as_of`
- The threshold lives in model configuration; changing it requires a new model configuration
  version
- Pitch types remain **separate**; fastball families are **not** grouped during MVP

### 12.2 Primary put-away pitch selection

1. Consider qualifying pitch types
2. Select the pitch with the highest put-away rate
3. Break ties by higher usage
4. If valid put-away data is unavailable, use the qualifying pitch with the highest usage and
   record the audit note `fallback_highest_usage_pitch`
5. If no qualifying pitch can be selected, use an explicit missing state

Pitch Mix Pressure and Put-Away Pitch Exploitation remain the approved scored components. Their
final formulas, measurements, buckets, and allocations are configurable and **not yet defined**
(Q15, Q16). Engineering must not invent a pitcher-matchup score.

---

## 13. Environment rules

**Environment maximum: 2 points.** Park max 1, Weather max 1.

**Park** uses a versioned, rolling-three-year, handedness-adjusted home-run park factor. Source
and bucket threshold are open (Q17).

**Weather** uses the exact forecast available at grading time. Current qualification (all
conditions): temperature ≥ 85 °F, wind speed ≥ 10 mph, wind traveling **toward** the hitter's
pull field.

**Direction handling.** Providers commonly report the direction wind comes **FROM**. The
environment feature layer converts FROM-direction to TO-direction before evaluating alignment.
Alignment uses explicit vector or cosine computation; informal text matching such as "wind out"
is prohibited. The exact cosine threshold is open (Q18).

**Batting side.** Actual batting side when known. Switch hitter vs. RHP with unknown side → LHB
pull direction. Switch hitter vs. LHP with unknown side → RHB pull direction.

The wind-alignment formula, stadium orientation, source assumptions, and thresholds are
configuration-driven and auditable. Environment may use `binary` scoring for MVP.
**No weather or park constants may appear in Python scoring code.**

---

## 14. Grades

Score range for successfully evaluated results: **0 through 12**.

| Grade | Interval |
|---|---|
| S | `[10, 12]` — terminal, closed at the domain maximum |
| A | `[8, 10)` |
| B | `[6, 8)` |
| C | `[4, 6)` |
| D | `[0, 4)` |

Cutoffs are preserved exactly in configuration, are profile-invariant, and cover the full range
without gaps or overlaps. **Grade assignment uses the internal deterministic Decimal score
before any presentation rounding.**

---

## 15. Evaluation status

| Status | Meaning |
|---|---|
| `EVALUATED` | The complete approved scoring contract was resolved |
| `NOT_EVALUABLE` | Required data remained unavailable after all approved component-specific fallbacks |

`NOT_EVALUABLE` is **not** a D grade, receives **no** manufactured score, must explain which
required inputs prevented evaluation, and must preserve the snapshot and the failure audit.

A complete but poor candidate receives a numeric score and Grade D.

---

## 16. Evaluation output (betting classifications removed)

**GreenMachine intentionally separates evaluation from decision-making.** The platform's
responsibility ends after producing a transparent, deterministic, auditable evaluation. Any
wagering, fantasy, DFS, or other downstream decision belongs entirely to the user and is outside
the scope of GreenMachine.

The grading engine's output is exactly and only:

1. **Total Score**
2. **Tier** (the Grade of §14)
3. **Component Breakdown** (per-component and per-category scores)
4. **Audit Trail** (the ordered derivation)
5. **Warnings** (for example insufficient-sample findings)
6. **Fallbacks** (provenance of any fallback actually used)

**Historical note.** Specification v6.3 defined a signal engine here that resolved
`AVOID` → `STRONG_BET` → `LEAN` → `PASS` in strict priority order, with an override reason
(§16.1) and a "strong category" fraction of 0.75 that existed only to feed those rules. GM-041
removed all of it — the `Signal` enum, the `signal` and `signal_reason` result fields, the
configuration rule family, and the strong-category fraction — by Product Owner ruling. No
betting classification, recommendation engine, or equivalent may be reintroduced. Q27, which
closed on the priority ordering, is superseded and recorded as such in `OPEN_QUESTIONS.md`.

---

## 17. Validation Layer

**Advisory only.** It does not award points, remove points, cap a grade, veto an evaluable
result, or reweight a category. It sits beside the scored result.

Validation context includes: wOBA for the corresponding profile where available, Relief
Vulnerability, Bullpen Notes, **sample-size warnings (including every `INSUFFICIENT` sample
status)**, source-coverage warnings, fallback status and ineligibility reasons, and
process-versus-result context.

Validation findings must be structured and auditable. **Free-text bullpen notes must never be
converted into hidden numerical scoring.**

---

## 18. Immutability and outcomes

Historical evaluations are append-only. Never overwritten: input snapshots, grade results,
evaluation envelopes, configuration versions, outcome records. Corrections create new records
with supersession references.

**Game outcomes are stored separately from pregame evaluations**, and structurally separate
from `InputSnapshot`, `GradeResult`, and `EvaluationEnvelope`. The primary initial backtest
outcome is *whether the batter hit at least one home run in the evaluated game.* An outcome
record never mutates a pregame evaluation. `OutcomeRecord` remains a minimal Sprint 1 schema
boundary; **no outcome ingestion or research logic is added during Sprint 1.**

---

## 19. Configuration invariants

Mandatory semantic validation at configuration load time. A violation is a load failure, not a
warning.

**Point and allocation invariants**

1. Every bucket's points are **≥ 0**
2. Every bucket's points are **≤ component `max_points`**
3. The **strongest qualifying bucket awards `max_points`**
4. Component maximums **sum exactly to** their category maximum
5. Category maximums **sum exactly to 12**
6. Allocations are **identical across `WindowProfile`s**

**Monotonicity invariants**

7. For `higher_is_better` components, awarded points **never decrease** as values increase
8. For `lower_is_better` components, awarded points **never increase** as values increase

**Coverage invariants**

9. Every valid in-domain value resolves to **exactly one** bucket
10. Bucket sets contain **no gaps and no overlaps**

**Schema-shape invariants**

11. `bucketed` and `binary` scoring use **separate validated schema shapes**
12. **Binary components are not forced to declare continuous bucket ranges**

**Additional structural rules**

13. Grade cutoffs are ordered, profile-invariant, and cover `[0, 12]` without gaps or overlaps
14. Every category references only defined components, and every defined component is referenced
15. Profile-specific bucket sets exist for every component declaring that profile
16. Measurement-specific bucket sets exist for every declared measurement of a component

---

## 20. Configuration governance

Configuration is part of the model. Changing a threshold must never require changing Python
grading logic. Every production configuration change requires: a new model configuration
version, Product Owner approval, strict schema and semantic validation, golden-test review,
historical comparison or backtest where applicable, changelog documentation, and preservation
of the previous configuration.

Once a model configuration has produced an evaluation, it is **immutable**. YAML comments,
formatting, indentation, and key order must not change the semantic config hash. A baseball
rule change and a code implementation change are different events and are versioned separately.

---

## 21. Audit requirements

Every `EVALUATED` result must answer, from stored data alone:

- Which window profile was used, over exactly which window bounds, from which
  profile-specific snapshot and `source_capture_id`
- Every component's `component_id`, `measurement_id`, raw value, unit, sample type, sample
  count, and sample status
- Which bucket configuration was used, which bucket the value landed in, and the points awarded
- Each category subtotal and the total, in exact Decimal terms
- Which grade cutoff applied
- `provider_id`, `acquisition_method`, `fallback_used`, and **why each higher-priority
  acquisition method was ineligible**
- The model configuration version and config hash in force

Every `NOT_EVALUABLE` result must record which required inputs were unavailable, the missing
reason for each, and every fallback that was attempted and why it failed or was ineligible.
