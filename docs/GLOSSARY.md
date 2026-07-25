# GreenMachine — Glossary

**Specification version:** v6.3 · **Status:** Draft, tracking MODEL_SPEC.md

Precise definitions for every term the system uses. Ambiguity here becomes a correctness bug,
so entries are written to be testable.

Items marked **⟨PO decision pending⟩** are unresolved and must not be invented by engineering.
Each links to an ID in `OPEN_QUESTIONS.md`.

**Terminology note (v6.3).** A **component** is a scored slot in a category. A **measurement**
is a specific quantity used to satisfy a component. Most components have exactly one possible
measurement; `attack_angle_quality` has two, mutually exclusive.

**Measurement convention (binding).** `MeasurementId` exists only to distinguish measurements
that a component could otherwise confuse, so it enumerates exactly the two attack-angle
measurements and nothing else. Every record carrying a `component_id` therefore also carries a
single `measurement_id` slot, filled as follows:

- **`attack_angle_quality` requires exactly one** `MeasurementId` — `ideal_attack_angle_pct` or
  `attack_angle_threshold_proxy`, never both, never neither.
- **Every other component requires `measurement_id = None`.** Those components have no separate
  measurement variant; their measurement is the component itself.

`None` here has exactly **one** meaning — "this component has no separate measurement variant" —
and never stands for absent or unknown data. Missing data is a different type entirely, carrying
a `MissingReason` (§5). Because the slot holds at most one value, a record can never carry two
measurements for one component. The pairing is enforced at construction.

---

## 1. Scored components

### Exit Velocity

| Field | Value |
|---|---|
| Display name | Exit Velocity |
| Component identifier | `exit_velocity` |
| Category | Power Profile |
| Baseball meaning | Average speed of the ball off the bat on batted-ball events; the raw power input |
| Formula | Mean `launch_speed` over eligible batted-ball events in the window |
| Unit | miles per hour (mph) |
| Sample type | `batted_ball_events` |
| Valid domain | ⟨PO decision pending — declared with buckets, Q12/Q13⟩ |
| Applicable windows | `RECENT_7D`, `LONG_TERM_2Y` |
| Direction | `higher_is_better` |
| Source priority | Statcast batted-ball events ⟨provider pending — Q23⟩ |
| Missing-data behavior | `NO_EVENTS_IN_WINDOW` if no eligible events. A value below the configured minimum is **still scored** and carries `SampleStatus.INSUFFICIENT` (Q14). |

### Barrel %

| Field | Value |
|---|---|
| Display name | Barrel % |
| Component identifier | `barrel_pct` |
| Category | Power Profile |
| Baseball meaning | Share of batted balls struck in the exit-velocity/launch-angle combination Statcast classifies as a barrel — the highest-value contact class |
| Formula | barreled events ÷ eligible batted-ball events × 100 |
| Unit | percent |
| Sample type | `batted_ball_events` |
| Valid domain | 0–100 |
| Applicable windows | `RECENT_7D`, `LONG_TERM_2Y` |
| Direction | `higher_is_better` |
| Source priority | Statcast event classification ⟨Q23⟩ |
| Missing-data behavior | as Exit Velocity |

### Hard Hit %

| Field | Value |
|---|---|
| Display name | Hard Hit % |
| Component identifier | `hard_hit_pct` |
| Category | Power Profile |
| Baseball meaning | Share of batted balls hit at or above the Statcast hard-hit exit-velocity threshold |
| Formula | events at or above the hard-hit threshold ÷ eligible batted-ball events × 100 |
| Unit | percent |
| Sample type | `batted_ball_events` |
| Valid domain | 0–100 |
| Applicable windows | `RECENT_7D`, `LONG_TERM_2Y` |
| Direction | `higher_is_better` |
| Source priority | Statcast ⟨Q23⟩ |
| Missing-data behavior | as Exit Velocity |

### Pitch Mix Pressure

| Field | Value |
|---|---|
| Display name | Pitch Mix Pressure |
| Component identifier | `pitch_mix_pressure` |
| Category | Pitcher Matchup |
| Baseball meaning | The degree to which the pitcher's qualifying pitch mix presents pitch types this batter handles well |
| Formula | **⟨PO decision pending — Q15⟩** |
| Unit | ⟨pending Q15⟩ |
| Sample type | `pitches` |
| Valid domain | ⟨pending Q15⟩ |
| Applicable windows | Season-based under both profiles |
| Direction | ⟨pending Q15⟩ |
| Source priority | Statcast pitch-level ⟨Q23⟩ |
| Missing-data behavior | Explicit missing state if no qualifying pitch type can be selected |

**Qualifying pitch type:** used ≥ **15%** (configurable default) of all pitches thrown by the
expected starting pitcher to batters using the evaluated hitter's relevant batting side, over
the current season through `as_of`. Pitch types are evaluated separately; fastball families are
not grouped during MVP.

### Put-Away Pitch Exploitation

| Field | Value |
|---|---|
| Display name | Put-Away Pitch Exploitation |
| Component identifier | `put_away_pitch_exploitation` |
| Category | Pitcher Matchup |
| Baseball meaning | How well the batter handles the pitcher's primary two-strike put-away offering |
| Formula | **⟨PO decision pending — Q16⟩** |
| Unit | ⟨pending Q16⟩ |
| Sample type | `pitches` |
| Valid domain | ⟨pending Q16⟩ |
| Applicable windows | Season-based under both profiles |
| Direction | ⟨pending Q16⟩ |
| Source priority | Statcast pitch-level ⟨Q23⟩ |
| Missing-data behavior | Fall back to highest-usage qualifying pitch with audit note `fallback_highest_usage_pitch`; explicit missing state if none |

### Sweet Spot %

| Field | Value |
|---|---|
| Display name | Sweet Spot % |
| Component identifier | `sweet_spot_pct` |
| Category | Form |
| Baseball meaning | Share of batted balls hit in the launch-angle band Statcast defines as the sweet spot; a contact-quality indicator |
| Formula | sweet-spot events ÷ eligible batted-ball events × 100 |
| Unit | percent |
| Sample type | `batted_ball_events` |
| Valid domain | 0–100 |
| Applicable windows | `RECENT_7D`, `LONG_TERM_2Y` |
| Direction | `higher_is_better` |
| Source priority | Statcast ⟨Q23⟩ |
| Missing-data behavior | as Exit Velocity |

### Attack Angle Quality

| Field | Value |
|---|---|
| Display name | Attack Angle Quality |
| Component identifier | `attack_angle_quality` |
| Category | Form |
| Baseball meaning | How often the batter's swing arrives at the ball on a productive plane |
| Permitted measurements | `ideal_attack_angle_pct` **or** `attack_angle_threshold_proxy` — exactly one per evaluation |
| Applicable windows | `RECENT_7D`, `LONG_TERM_2Y` |
| Direction | `higher_is_better` |
| Buckets | **Measurement-specific and profile-specific.** Ideal-percentage buckets must not be applied to the proxy unless explicitly configured for that measurement. |
| Missing-data behavior | `TRACKING_UNAVAILABLE` / `UNSUPPORTED_HISTORICAL_PERIOD`; contributes to `NOT_EVALUABLE` if no measurement is eligible |

**Prohibited:** scoring both measurements, averaging them, blending them, labeling the proxy as
Savant Ideal Attack Angle %, or presenting one under the other's display name.

**Display:** `ideal_attack_angle_pct` → "Ideal Attack Angle %". `attack_angle_threshold_proxy`
→ "Attack Angle Proxy".

#### Measurement — `ideal_attack_angle_pct`

| Field | Value |
|---|---|
| Display name | Ideal Attack Angle % |
| Measurement identifier | `ideal_attack_angle_pct` |
| Baseball meaning | Share of tracked contact events where the bat's attack angle fell in Savant's ideal band |
| Formula | events with **5 ≤ attack_angle ≤ 20** ÷ all valid events with a recorded attack angle × 100 |
| Unit | percent |
| Sample type | valid tracked contact / batted-ball events with a recorded attack angle |
| Valid domain | 0–100 |
| Acquisition priority | `direct_aggregate` → `structured_extract` → `rendered_scrape` → `event_derived`, **subject to point-in-time eligibility** (MODEL_SPEC §11.2) |

**Boundary rule.** The 5°–20° band is **inclusive at both ends**. It is an event-level
eligibility predicate from Savant's published definition and is deliberately *not* governed by
the half-open `[lower, upper)` scoring-bucket convention. Both `attack_angle = 5.0` and
`attack_angle = 20.0` count as ideal, and both must be tested explicitly.

**Prohibited.** Raw average attack angle must not be scored as a monotonic higher-is-better
metric. It is not a substitute for this measurement.

#### Measurement — `attack_angle_threshold_proxy`

| Field | Value |
|---|---|
| Display name | Attack Angle Proxy |
| Measurement identifier | `attack_angle_threshold_proxy` |
| Baseball meaning | A separately named, deterministic, configuration-defined stand-in used **only** when no eligible measurement of `ideal_attack_angle_pct` exists |
| Formula | **⟨PO decision pending — Q21⟩** |
| Unit | ⟨pending Q21⟩ |
| Acquisition method | `configured_proxy` |
| Rules | Presented as a proxy; never labeled as Savant Ideal Attack Angle %; never silently mixed with Savant-sourced percentages; remains distinguishable in backtesting |

### Bat Speed

| Field | Value |
|---|---|
| Display name | Bat Speed |
| Component identifier | `bat_speed` |
| Category | Form |
| Baseball meaning | Average speed of the bat through the hitting zone on qualifying swings |
| Formula | Mean bat speed over qualifying swings in the window |
| Unit | miles per hour (mph) |
| Sample type | `swings` — **always labeled a swing sample, never a batted-ball-event sample** |
| Valid domain | ⟨pending Q12/Q13⟩ |
| Applicable windows | `RECENT_7D`; `LONG_TERM_2Y` where tracked coverage allows ⟨adequacy open — Q22⟩ |
| Direction | `higher_is_better` |
| Source priority | Statcast bat-tracking ⟨Q23⟩ |
| Missing-data behavior | `TRACKING_UNAVAILABLE` / `UNSUPPORTED_HISTORICAL_PERIOD` for periods predating bat tracking |

### Pull % on Air Balls

| Field | Value |
|---|---|
| Display name | Pull % on Air Balls |
| Component identifier | `pull_pct_air_balls` |
| Category | Pull Power |
| Baseball meaning | Share of air balls hit to the pull field — the batted-ball direction most associated with home-run production |
| Formula | pulled air balls ÷ eligible air balls × 100 |
| Unit | percent |
| Sample type | `air_balls` |
| Valid domain | 0–100 |
| Applicable windows | `RECENT_7D`, `LONG_TERM_2Y` |
| Direction | `higher_is_better` |
| Source priority | Statcast ⟨Q23⟩ |
| Missing-data behavior | `NO_EVENTS_IN_WINDOW`; below-minimum values are still scored with `SampleStatus.INSUFFICIENT` |

### Park

| Field | Value |
|---|---|
| Display name | Park |
| Component identifier | `park` |
| Category | Environment (max 1 point) |
| Baseball meaning | The venue's tendency to suppress or inflate home runs for the batter's handedness |
| Formula | Versioned rolling-three-year, handedness-adjusted home-run park factor |
| Unit | park-factor index ⟨scale pending — Q17⟩ |
| Sample type | `games` (venue-level reference data) |
| Valid domain | ⟨pending Q17⟩ |
| Applicable windows | Rolling three years under **both** profiles |
| Direction | `higher_is_better` |
| Source priority | ⟨PO decision pending — Q17⟩ |
| Missing-data behavior | `SOURCE_UNAVAILABLE` |

### Weather

| Field | Value |
|---|---|
| Display name | Weather |
| Component identifier | `weather` |
| Category | Environment (max 1 point) |
| Baseball meaning | Whether conditions at first pitch favor carry toward the batter's pull field |
| Formula | Qualifies when **all** hold: temperature ≥ 85 °F; wind speed ≥ 10 mph; wind traveling **toward** the batter's pull field by explicit vector/cosine alignment ⟨threshold pending — Q18⟩ |
| Scoring method | `binary` for MVP — declares a qualification predicate, **not** continuous bucket ranges |
| Sample type | single forecast observation |
| Valid domain | qualifies / does not qualify |
| Applicable windows | Grading-time forecast snapshot under **both** profiles |
| Source priority | ⟨provider pending — Q23⟩ |
| Missing-data behavior | `WEATHER_UNAVAILABLE` |

**FROM/TO conversion.** Providers usually report the direction wind comes **FROM**. The feature
layer converts to **TO**-direction before alignment. Informal text matching ("wind out") is
prohibited.

**Batting side for pull direction.** Actual batting side when known. Switch hitter vs. RHP with
unknown side → LHB pull direction. Switch hitter vs. LHP with unknown side → RHB pull direction.

---

## 2. Validation inputs (advisory, zero points)

| Term | Identifier | Meaning |
|---|---|---|
| wOBA (window-matched) | `woba_window` | Weighted On-Base Average over the same window profile as the evaluation, where available. Result-based context against the process-based score. |
| Relief Vulnerability | `relief_vulnerability` | Structured indication of how vulnerable the opposing bullpen is to home runs. ⟨definition pending⟩ |
| Bullpen Notes | `bullpen_notes` | Free-text context (usage, availability, injuries). **Never converted into numerical scoring.** |
| Sample-size warnings | `sample_warnings` | One structured finding per component carrying `SampleStatus.INSUFFICIENT` |
| Source-coverage warnings | `coverage_warnings` | Findings where a window had partial coverage or a degraded source |
| Fallback status | `fallback_status` | Which approved component-level fallbacks were used, to what, and **why each higher-priority acquisition method was ineligible** |

---

## 3. Window profiles and snapshots

| Term | Meaning |
|---|---|
| **Window profile** | A named, selectable evaluation view defining the time window for windowed components. Profiles are separate evaluations, never blended. |
| **`RECENT_7D`** | "Recent — Last 7 Days." Eligible events in the 7 days immediately preceding `as_of`. |
| **`LONG_TERM_2Y`** | "Long-Term — Rolling 2 Years." Eligible events between `as_of − 2 calendar years` and `as_of`. |
| **`window_start` / `window_end`** | The exact bounds actually applied, stored on the snapshot and on every observation. |
| **Snapshot / `InputSnapshot`** | The frozen, content-hashed set of all inputs for **exactly one** window profile. The unit of reproducibility. A snapshot may never contain or produce both profiles. |
| **`snapshot_id`** | Deterministic identifier derived from snapshot content. Distinct per profile. |
| **Source capture** | One source-data collection operation. **One source capture may produce two independently frozen profile-specific snapshots.** |
| **`source_capture_id`** | Shared by snapshots produced from the same source capture. It links them; it does not make them identical. `snapshot_id`, `input_hash`, `window_profile`, `window_start`, `window_end`, and observations all remain distinct. |
| **Profile comparison** | Comparison performed in `reporting`, over two independently stored `GradeResult`s. Never within a snapshot, never inside the core. |
| **Window agreement** | Research-only context describing how closely the two profiles' grades align. Not scored, not a modifier, not a veto. ⟨definition pending — Q29⟩ |
| **Profile-invariant component** | A component whose window does not change with profile: Pitcher Matchup (season), Park (rolling 3 years), Weather (grading-time forecast). |

---

## 4. Sample types and status

| Term | Meaning |
|---|---|
| `batted_ball_events` | Events where the ball was put in play and tracked |
| `swings` | Qualifying tracked swings (Bat Speed denominator) |
| `air_balls` | Batted balls in the air (Pull % on Air Balls denominator) |
| `plate_appearances` | Completed plate appearances |
| `pitches` | Individual pitches (pitcher-matchup denominators) |
| `games` | Game-level records (venue reference data) |
| `sample_count` | The true denominator actually observed for that component in that window |
| `minimum_sample_required` | Configured minimum for the component **and** profile ⟨pending Q14⟩. Governs the label and the advisory warning; **does not gate scoring**. |
| **`SampleStatus`** | `SUFFICIENT` \| `INSUFFICIENT`. A distinct type from `MissingReason`. |
| **`SampleStatus.INSUFFICIENT`** | A valid value computed from fewer events than the configured minimum. **It is still scored**, carries the status through the audit trail, and raises an advisory Validation Layer warning. It is **not** a missing reason and **not** zero. |
| `data_coverage` | Requested vs. actual coverage period, coverage percentage/status, source availability |
| **`CoverageStatus`** | `COMPLETE` \| `PARTIAL` \| `NONE`. How completely the requested window was actually covered (MODEL_SPEC §11.1). |
| **`CoverageStatus.COMPLETE`** | The requested period was covered in full. Requires an available source and a recorded actual coverage period. |
| **`CoverageStatus.PARTIAL`** | The source was available and covered only part of the requested period. Requires a recorded actual coverage period, which must fall inside the requested one. **Partial coverage is never presented as complete.** |
| **`CoverageStatus.NONE`** | Nothing was covered: no actual coverage period and a sample count of zero. An unavailable source can only be `NONE`. |

> Three distinct states, never collapsed: **zero**, **insufficient sample**, **missing**.

---

## 5. Missing reasons

`MissingReason` members — note that `INSUFFICIENT` is deliberately absent.

| Reason | Meaning |
|---|---|
| `NO_EVENTS_IN_WINDOW` | Window contained zero eligible events |
| `SOURCE_UNAVAILABLE` | The source could not be reached or returned nothing usable |
| `TRACKING_UNAVAILABLE` | The tracking technology did not cover this player or period |
| `PLAYER_NOT_COVERED` | Player absent from the source's population |
| `INVALID_SOURCE_VALUE` | Source returned a value failing domain validation |
| `EXPECTED_PITCHER_UNKNOWN` | No expected starter or opener known at snapshot time |
| `WEATHER_UNAVAILABLE` | No forecast available at grading time |
| `UNSUPPORTED_HISTORICAL_PERIOD` | The measurement did not exist or was not collected in that period |

---

## 6. Provenance

| Term | Meaning |
|---|---|
| **`provider_id`** | Stable identifier for the data provider, e.g. `baseball_savant`. Carried in core and stored records. |
| **`acquisition_method`** | How the value was obtained: `direct_aggregate` \| `structured_extract` \| `rendered_scrape` \| `event_derived` \| `configured_proxy`. Unavailability is **not** an acquisition method — it is a `MissingReason`. |
| **Source label** | A user-facing string **derived** from `provider_id` + `acquisition_method`. Not stored as an opaque composite. |
| **Eligible acquisition method** | A method that can produce the exact selected profile, the correct `window_start`/`window_end`, using no observation after `as_of`. Selection takes the highest-priority **eligible** method, not the highest-priority available one. |
| **`fallback_used`** | Records that a lower-priority method was selected, together with why each higher-priority method was ineligible. |
| **Parsing vocabulary** | Provider HTML column names, page-layout details, parser selectors, endpoint-specific structures. **Prohibited** in domain and scoring models; confined to ingestion adapters. |

---

## 7. Grading and result terms

| Term | Meaning |
|---|---|
| **Component** | A scored slot in a category, carrying a `max_points` allocation |
| **Measurement** | A specific quantity used to satisfy a component. Exactly one per component per evaluation. |
| **Component score** | Points awarded by the highest qualifying bucket. Not cumulative across buckets. May be fractional. |
| **Category score** | Sum of component scores within a category. Never averaged, never rescaled. |
| **Total score** | Sum of category scores. Range 0–12, in Decimal. |
| **Grade** | S `[10,12]` · A `[8,10)` · B `[6,8)` · C `[4,6)` · D `[0,4)`. Assigned from the internal Decimal score, before any presentation rounding. Profile-invariant cutoffs. |
| **Strong category** | `category_score >= category_max_points × 0.75`, compared in Decimal without rounding. 3-point category → strong at ≥ 2.25; 2-point category → strong at ≥ 1.50. |
| **Signal** | `AVOID` \| `STRONG_BET` \| `LEAN` \| `PASS`, resolved in **that** strict priority order; first match wins. `AVOID` is evaluated **first** (MODEL_SPEC §16, Q27), which is why a high grade can still resolve to `AVOID` with an override reason. Earlier revisions of this glossary listed the members `STRONG_BET, LEAN, PASS, AVOID` and called that the priority order; that was an editorial error, corrected here to match MODEL_SPEC §16. The `Signal` enum is declared in this order. |
| **Signal override** | A case where a higher-priority rule supersedes what the grade alone would suggest — e.g. Grade S with `AVOID` and reason `power_profile_veto`. The reason code is displayed and audited. |
| **Evaluation status** | `EVALUATED` \| `NOT_EVALUABLE` |
| **`NOT_EVALUABLE`** | Required data unavailable after all approved component-specific fallbacks. Not a D grade, no manufactured score, no signal, with a recorded failure audit. |
| **Bucket** | A half-open `[lower, upper)` interval over a component's declared domain, awarding fixed points. Terminal bucket closed at the domain maximum. |
| **Highest qualifying bucket** | Among buckets containing the value, the one awarding the most points — the awarded value |
| **Presentation rounding** | Rounding applied only for display, outside the grading core. Never affects bucket, grade, strong-category, or signal decisions. |

---

## 8. Numeric terms

| Term | Meaning |
|---|---|
| **Decimal policy** | Thresholds, values entering scoring, point values, category totals, and total scores are `Decimal`. |
| **Permitted Decimal construction** | From provider **strings**, configuration **strings**, or **integers**. |
| **Prohibited Decimal construction** | From a **binary float**. This constrains ingestion: numeric fields destined for scoring must be carried as strings out of the adapter, not as parsed floats. |
| **Decimal context** | Project-local, precision **28**, rounding **`ROUND_HALF_EVEN`**. All grading arithmetic runs under it. |
| **Quantization** | Deliberately not applied to derived values before scoring. |
| **Canonical Decimal serialization** | Deterministic base-10 strings. Never binary floats. |

---

## 9. Identity, time, and architecture terms

| Term | Meaning |
|---|---|
| **`game_id`** | The **official provider's** unique game identifier, used canonically. No replacement internal ID is generated. Doubleheader games have separate official IDs; a suspended and resumed game retains its ID. |
| **`slate_date`** | The **official scheduled MLB date**, never derived from UTC |
| **Scheduled start time** | Stored in **UTC**, alongside venue-local scheduled time and venue timezone |
| **`as_of`** | The point-in-time timestamp the snapshot represents. All windows are computed relative to it. |
| **Point-in-time correctness** | No event or observation dated after `as_of` entered the evaluation, and windows were reconstructed from event timestamps rather than current aggregates |
| **`GradeResult`** | The pure deterministic grading output derived solely from `(frozen EvaluationInput, model configuration)`. One profile. |
| **`EvaluationEnvelope`** | The orchestration/persistence wrapper around a `GradeResult`, carrying identity, versions, hashes, provenance, and supersession |
| **`config_hash`** | Semantic content hash of a model configuration version; unchanged by comments, formatting, indentation, or key order |
| **`input_hash`** | Content hash of the frozen profile-specific evaluation input. Distinct per profile. |
| **Supersession** | A newer record replacing an earlier one in interpretation while both remain stored and readable |
| **Outcome record** | Post-game result stored separately from, and structurally independent of, `InputSnapshot`, `GradeResult`, and `EvaluationEnvelope`. Primary initial outcome: did the batter hit ≥ 1 home run in the evaluated game. |
| **Product-specification version** | The baseball/product lineage (currently v6.3) — distinct from code, model configuration, and schema versions |

---

## 10. Domain enum vocabulary

The complete enumerated vocabulary of the domain layer, listed **in declaration order**. For
`Signal` that order is also the evaluation priority order (MODEL_SPEC §16); for the others it is
simply the order the members are declared in.

This section is the machine-checked source of truth for the drift test: it compares the block
below against the code exactly — every enum, every member, in order — so an identifier can never
be added, renamed, reordered, or removed on one side only. Definitions of what each member
*means* live in the sections above.

<!-- BEGIN DOMAIN VOCABULARY -->

| Enum | Members, in declaration order |
|---|---|
| `WindowProfile` | `RECENT_7D`, `LONG_TERM_2Y` |
| `Category` | `power_profile`, `pitcher_matchup`, `form`, `pull_power`, `environment` |
| `ComponentId` | `exit_velocity`, `barrel_pct`, `hard_hit_pct`, `pitch_mix_pressure`, `put_away_pitch_exploitation`, `sweet_spot_pct`, `attack_angle_quality`, `bat_speed`, `pull_pct_air_balls`, `park`, `weather` |
| `MeasurementId` | `ideal_attack_angle_pct`, `attack_angle_threshold_proxy` |
| `ValidationInputId` | `woba_window`, `relief_vulnerability`, `bullpen_notes`, `sample_warnings`, `coverage_warnings`, `fallback_status` |
| `SampleType` | `batted_ball_events`, `swings`, `air_balls`, `plate_appearances`, `pitches`, `games` |
| `SampleStatus` | `SUFFICIENT`, `INSUFFICIENT` |
| `MissingReason` | `NO_EVENTS_IN_WINDOW`, `SOURCE_UNAVAILABLE`, `TRACKING_UNAVAILABLE`, `PLAYER_NOT_COVERED`, `INVALID_SOURCE_VALUE`, `EXPECTED_PITCHER_UNKNOWN`, `WEATHER_UNAVAILABLE`, `UNSUPPORTED_HISTORICAL_PERIOD` |
| `ProviderId` | `baseball_savant` |
| `AcquisitionMethod` | `direct_aggregate`, `structured_extract`, `rendered_scrape`, `event_derived`, `configured_proxy` |
| `PitcherRole` | `opener`, `expected_starter`, `uncertain` |
| `EvaluationStatus` | `EVALUATED`, `NOT_EVALUABLE` |
| `Grade` | `S`, `A`, `B`, `C`, `D` |
| `Signal` | `AVOID`, `STRONG_BET`, `LEAN`, `PASS` |
| `CoverageStatus` | `COMPLETE`, `PARTIAL`, `NONE` |

<!-- END DOMAIN VOCABULARY -->
