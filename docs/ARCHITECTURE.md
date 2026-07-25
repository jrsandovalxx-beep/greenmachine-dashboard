# GreenMachine — Architecture

**Specification version:** v6.3 — Foundation Clarifications
**Status:** Approved 2026-07-22 (v6.3 amendment applied)
**Scope:** Engineering structure only. Baseball and grading behavior lives in `MODEL_SPEC.md`
and is not restated or re-decided here.

---

## 1. Architectural thesis

GreenMachine is **a pure function wrapped in adapters**.

```
                  ┌────────────────────────────────────────────┐
    messy world ─▶│  INGESTION   (impure: network, retries,    │
                  │  provider adapters incl. Savant)           │
                  └───────────────────┬────────────────────────┘
                                      │ raw payloads, stored verbatim / hashed
                  ┌───────────────────▼────────────────────────┐
                  │  FEATURES: point-in-time event filtering,  │
                  │  window resolution, sample accounting      │
                  │  → InputSnapshot (frozen, content-hashed)  │
                  └───────────────────┬────────────────────────┘
                                      │ EvaluationInput + window_profile
  model config ──▶┌───────────────────▼────────────────────────┐
  (versioned,     │  GRADING CORE  (pure, deterministic)       │
   hashed)        │  buckets → metrics → categories → total    │
                  │  → grade → signal → validation findings    │
                  │  ⇒ GradeResult                             │
                  └───────────────────┬────────────────────────┘
                                      │
                  ┌───────────────────▼────────────────────────┐
                  │  ORCHESTRATION: injected clock, identity,  │
                  │  versions, hashes ⇒ EvaluationEnvelope     │
                  └───────────────────┬────────────────────────┘
                                      │
                  ┌───────────────────▼────────────────────────┐
                  │  PERSISTENCE (append-only)  │  REPORTING   │
                  │  evaluations · snapshots · outcomes (sep.) │
                  └────────────────────────────────────────────┘
```

Everything upstream of the core may be messy and re-run. Everything inside the core is pure.
Nothing downstream mutates history.

The six long-term capabilities are **six callers of the same core**:

| Capability | Input | Config | Profile |
|---|---|---|---|
| Daily grading | today's snapshot | active version | one or both |
| Replay | archived snapshot for date D | version recorded on that evaluation | as recorded |
| Backtest | archived snapshots over a range | one chosen version | one chosen profile |
| Simulation | archived snapshots | candidate version | chosen |
| Config comparison | one snapshot | two versions, diffed | held constant |
| Profile comparison | one snapshot | one version | both, diffed |

---

## 2. Four version streams

Never conflated. All four are recorded on every stored evaluation.

| Stream | Example | Changes when |
|---|---|---|
| **Product specification** | `v6.2` | Baseball/product specification changes |
| **Code version** | `0.2.0` (SemVer) | Software changes |
| **Model configuration version** | `v0.1.0` (SemVer) | Thresholds, allocations, buckets, cutoffs, signal config change |
| **Evaluation schema version** | `1` | Persisted snapshot/evaluation record format changes |

`GreenMachine v6.2` is a product-specification version. It is **not** a code SemVer.

---

## 3. Resolved requirements (Q1–Q4)

Recorded here because they shape the architecture. Authoritative text is in `MODEL_SPEC.md`.

- **Q1 — Aggregation.** Category numbers are **category maximum points**, total 12. Metric
  score = highest qualifying bucket's points; category = sum of metrics; total = sum of
  categories. No averaging, rescaling, or dynamic normalization. *Architectural impact:* the
  scoring pipeline is a pure fold with invariants checkable at every level, and config
  validation must enforce the point-sum rules at load time.
- **Q2 — Evaluation unit.** One batter, one game, versus the expected starting pitcher, one
  frozen snapshot, **one window profile**. *Architectural impact:* `window_profile` is part of
  evaluation identity; a pitcher change produces a new snapshot and a superseding evaluation.
- **Q3 — Output.** Score 0–12; grades S/A/B/C/D; status `EVALUATED` | `NOT_EVALUABLE`; signal
  engine with strict priority. *Architectural impact:* `GradeResult` must model an evaluated
  and a not-evaluable shape without inventing a score for the latter.
- **Q4 — Validation Layer.** Advisory only. *Architectural impact:* validation lives **beside**
  scoring inside the pure core (it is deterministic and derived from the same frozen input),
  contributes zero points, and cannot influence grade or signal.

Specification v6.3 additionally closed **Q25** (allocations are profile-invariant), **Q26**
(fractional points allowed; strong category stays at 75% with no rounding), **Q27** (`AVOID`
priority is intentional and carries an override reason), **Q28** (15% pitch-usage default and
its denominator), and **Q30** (canonical provider `game_id`, official `slate_date`).

*Architectural impact of v6.3:* one `InputSnapshot` carries exactly one profile (§5); a single
allocation structure is validated rather than one per profile; Decimal replaces float
throughout the scoring path (§12 R4); the attack-angle component and its measurement become two
separate identifiers (§8); provenance becomes generic `provider_id` + `acquisition_method`
(§8); `SampleStatus` and `MissingReason` become distinct types with insufficient samples still
scored; and acquisition priority becomes subordinate to point-in-time eligibility (§7).

Full register, including questions still open, in `OPEN_QUESTIONS.md`.

---

## 4. Layers and responsibilities

Dependencies point **inward only**:
`cli → evaluation → {features, scoring, validation, config} → domain`.
`domain` depends on nothing. `scoring` never imports `persistence`, `ingestion`, or `features`.

### 4.1 `domain` — vocabulary
Frozen value objects and enums: `Batter`, `Pitcher`, `Venue`, `GameContext`, `WindowProfile`,
`MetricId`, `SampleType`, `MetricObservation`, `MissingReason`, `BucketHit`, `MetricScore`,
`CategoryScore`, `Grade`, `Signal`, `EvaluationStatus`, `ValidationFinding`, `GradeResult`,
`EvaluationEnvelope`, `InputSnapshot`, `OutcomeRecord`.
No I/O, no config knowledge, no third-party types beyond the modelling toolchain.

### 4.2 `config` — rules as data
Loading, strict schema validation, semantic validation, version resolution, canonicalization
and hashing. Supports **profile-specific buckets and minimum samples**. No dictionaries escape
this package.

### 4.3 `features` — point-in-time input assembly
Where backtest integrity is won or lost. Responsibilities:

- Filter the eligible event set by **event timestamp** against `as_of` and the profile window
- Resolve `window_start` / `window_end` explicitly and record them
- Select the highest-priority **eligible** acquisition method (§7) and record why higher-priority
  methods were ineligible
- Convert provider values into `Decimal` **from strings**, never from parsed floats (ADR-0002)
- Compute per-metric sample counts using each metric's **own** denominator
- Apply approved metric-level source fallbacks (e.g. attack-angle hierarchy) and record them
- Convert wind FROM-direction to TO-direction and resolve pull-field bearing
- Record coverage: requested period, actual period, coverage status, source availability
- Freeze and content-hash the result into **one profile-specific `InputSnapshot`**, tagged with
  the `source_capture_id` of the collection operation it came from

pandas is permitted here. It must not cross into `scoring`. Numeric columns destined for scoring
must be read with a string dtype: pandas defaults to `float64`, and a value that has passed
through a binary float has already lost the Decimal guarantee.

### 4.4 `scoring` — the grading core (pure)
Bucket resolution → metric scoring → category aggregation → total → grade → signal.
Enforces invariants: metric ≤ `max_points`, category ≤ category max, total ≤ 12.

### 4.5 `validation` — advisory layer (pure)
Consumes the same frozen input, produces structured findings. Zero points. Structurally unable
to alter score, grade, or signal — enforced by the fact that it runs after grading and its
output is attached, not fed back.

### 4.6 `evaluation` — orchestration
Resolves config version → assembles input → invokes core → wraps the `GradeResult` in an
`EvaluationEnvelope` with identity, versions, hashes, provenance, and `evaluated_at` from the
**injected clock**.

### 4.7 `ingestion` — provider adapters (impure, isolated)
One adapter per source. All provider-specific vocabulary, parsing, scraping, retry logic, and
schema-change detection lives here and nowhere else.

### 4.8 `persistence` — ports and adapters
Repository *interfaces* with append-only semantics; concrete storage is an adapter. Separate
repositories for snapshots, evaluations, and **outcomes**.

### 4.9 `reporting` / `cli` / (later) Streamlit UI
Read-only consumers over stored evaluations. The UI never grades.

---

## 5. Window-profile architecture

Profiles are a **first-class dimension**, not a parameter that gets lost.

- `WindowProfile` is a domain enum: `RECENT_7D`, `LONG_TERM_2Y`
- It appears in: `InputSnapshot` window bounds, every `MetricObservation`, `GradeResult`, and
  evaluation identity
- Configuration is addressable per profile for **buckets and minimum samples only**; component
  `max_points`, category maximums, and grade cutoffs are **profile-invariant** and validated as a
  single shared allocation structure
- **One `InputSnapshot` carries exactly one profile** and may never contain or produce both
- **One source capture may produce two independently frozen profile-specific snapshots**, sharing
  a `source_capture_id` but with distinct `snapshot_id`, `input_hash`, `window_profile`,
  `window_start`, `window_end`, and observations
- Profile comparison happens in `reporting`, over two independently stored `GradeResult`s

**Structurally prohibited** (enforced by design and by test, not by convention):

- Averaging or blending profiles
- Substituting `LONG_TERM_2Y` values into a `RECENT_7D` evaluation, or vice versa
- Producing a hybrid grade
- A snapshot containing observations from more than one profile

The distinction that must stay crisp: an **approved component-level acquisition fallback**
(`direct_aggregate` → `event_derived` → `configured_proxy`) is legitimate. A **cross-window
fallback** is not. These live in different layers and are represented by different fields
(`acquisition_method` and `fallback_used` vs. `window_profile`), which makes the illegal case
hard to express by accident. Since v6.3 a cross-window substitution is additionally hard to
express *structurally*, because the two profiles no longer share a snapshot to borrow from.

**Window agreement** is computed in `reporting` over two stored results. It never enters the
core.

### 5.1 Profile-invariant components
Pitcher Matchup (season), Park (rolling 3 years), Weather (grading-time forecast) resolve
identically under both profiles. They are still recorded with explicit window bounds so an
audit never has to infer them.

---

## 6. GradeResult vs. EvaluationEnvelope

The single most important structural separation in the system.

| | `GradeResult` | `EvaluationEnvelope` |
|---|---|---|
| Purity | **Pure** — a function of `(frozen EvaluationInput, config)` | Impure context |
| Produced by | `scoring` + `validation` | `evaluation` orchestration |
| Contains | status, window profile, metric observations (`component_id` + `measurement_id`), bucket results, component scores, category scores, total (if evaluated), grade (if evaluated), signal and override reason (if evaluated), validation findings, complete audit derivation. All scores are `Decimal`. | `evaluation_id`, `snapshot_id`, **`source_capture_id`**, `evaluated_at`, code version, model version, **product-specification version**, schema version, `config_hash`, `input_hash`, subject identity, provenance, `supersedes` |
| Time | **Never** reads or generates time | `evaluated_at` supplied via injected clock |

**Determinism guarantee:** given identical inputs, configuration, *and* envelope metadata, the
canonical serialized output is **byte-identical**. Note the scope — the envelope carries
`evaluated_at`, so byte-identity across two real grading runs holds only when the clock value
is held constant. `GradeResult` alone is byte-identical unconditionally, which is why the
determinism test targets `GradeResult` and the envelope test uses a `FixedClock`.

---

## 7. Point-in-time correctness

For an evaluation with `as_of` = **T**:

- `RECENT_7D`: events with timestamp `< T` and `≥ T − 7 days`
- `LONG_TERM_2Y`: events with timestamp `< T` and `≥ T − 2 calendar years`
- Pitcher season data: only information available before T
- Weather: the grading-time forecast frozen at or before T
- **No observation dated after T may enter the evaluation**

**Implementation rule:** the eligible event set is reconstructed from **event timestamps**.
Recomputing a historical window from a current aggregate table is prohibited — it is the single
easiest way to leak the future, and it leaks silently.

**Partial coverage** is preserved and visible: requested coverage period, actual coverage
period, coverage percentage/status, source availability, sample count. A 6-month sample is
never presented as a 2-year sample.

### 7.1 Source eligibility outranks source priority

An acquisition method is **eligible** only if it can produce the exact selected profile, the
correct `window_start` and `window_end`, using no observation after T. Feature assembly selects
the highest-priority **eligible** method — not the highest-priority available one — and records
why each higher-priority method was ineligible.

This is a real behavioural difference between today's slate and a backtest: a current
leaderboard aggregate can satisfy today's seven-day window but cannot reproduce a historical
`as_of` window, so `event_derived` may be the highest eligible method for historical
evaluations. Research must therefore be able to segment results by `acquisition_method`, which
is why it is preserved on every observation.

**Testing hook:** the point-in-time filter is a pure function taking `(events, as_of, profile)`
and is unit-tested directly with events straddling every boundary, including exactly at T. The
eligibility predicate is likewise a pure function of `(method, profile, as_of, coverage)` and is
tested independently of any provider.

---

## 8. Savant ingestion adapter boundary

**Savant-specific behavior is prohibited in `domain`, `scoring`, `validation`, `evaluation`,
and evaluation records.** It exists only in `ingestion/savant/`.

What crosses the boundary is a normalized `MetricObservation` carrying generic provenance —
`provider_id`, `acquisition_method`, `source_as_of`, coverage, `fallback_used` — and numeric
values as **strings** for Decimal construction. Not a Savant payload, not a Savant column name,
not a URL-shaped assumption, and not a provider-specific composite source label.

Provider HTML column names, page-layout details, parser selectors, and endpoint-specific
structures are prohibited in `domain`, `scoring`, `validation`, `evaluation`, and stored
records. User-facing source labels are **derived** from `provider_id` + `acquisition_method`
rather than stored as an opaque string.

```
ingestion/savant/  ──▶ normalized MetricObservation ──▶ features ──▶ snapshot ──▶ core
   client.py                (provider_id, acquisition_method,
   structured_extract.py     source_as_of, coverage, content
   leaderboard_parser.py     hash, adapter version, values
   event_derivation.py       as strings)
   mapping.py
```

Adapter requirements (source hierarchy and constraints are specified in `MODEL_SPEC.md` §9):
validate expected column names, fail loudly on schema change, record retrieval metadata,
preserve the raw response or content hash where practical, fixture-based parser tests, never
silently return empty or zero, respect source access limits.

The proxy is a **separately named measurement** (`attack_angle_threshold_proxy`) of the
`attack_angle_quality` component, never a substituted value under the Savant measurement's name.
Exactly one measurement satisfies the component per evaluation, and buckets are
measurement-specific — so direct, structured-extract, scraped, derived, and proxy values remain
distinguishable in backtesting by construction, and ideal-percentage buckets cannot be applied
to a proxy value by accident.

**Not implemented in Sprint 1.** Implemented by **GM-020** for one vertical slice: the slice
derives its metrics from events (`AcquisitionMethod.EVENT_DERIVED`) and records why each
higher-priority method was ineligible. No proxy measurement is produced, and no direct,
structured-extract, or scraped acquisition path exists yet.

---

## 9. Technology direction and dependency rules

Intended stack: Python, Streamlit, Pydantic, pytest, SQLite, pandas (ingestion/features only),
Plotly (presentation), pybaseball or direct first-party access.

**The deterministic domain and scoring core must not depend on:** Streamlit, pandas, Plotly,
SQLite, network clients, or any data-provider adapter.

Enforced by an automated import-boundary test in CI, not by convention.

Initial delivery target: a local, single-user Streamlit research dashboard. The architecture
preserves later scheduling or hosted deployment without building distributed infrastructure now.

---

## 10. Recommended folder structure

```
greenmachine/
├── README.md
├── CHANGELOG.md
├── pyproject.toml
├── .pre-commit-config.yaml
├── .github/workflows/ci.yml
│
├── docs/
│   ├── MODEL_SPEC.md            # authoritative baseball + grading spec (v6.2)
│   ├── ARCHITECTURE.md          # this file — engineering structure
│   ├── PHILOSOPHY.md
│   ├── ENGINEERING_GUIDELINES.md
│   ├── GLOSSARY.md
│   ├── OPEN_QUESTIONS.md
│   ├── SPRINT_1_PLAN.md
│   └── adr/
│
├── config/
│   ├── model/
│   │   └── v0.1.0/
│   │       ├── model.yaml              # spec version, category maxima, grade cutoffs
│   │       ├── allocations.yaml        # profile-INVARIANT max_points per component
│   │       ├── signals.yaml            # rules, priority, strong threshold, override reasons
│   │       ├── profiles/
│   │       │   ├── recent_7d.yaml      # profile-specific buckets + min samples ONLY
│   │       │   └── long_term_2y.yaml
│   │       ├── components/             # method, direction, domain, sample type
│   │       ├── measurements/           # measurement-specific bucket sets
│   │       └── validation.yaml
│   ├── parks/                          # versioned rolling-3y handedness-adjusted factors
│   ├── stadium_orientation/            # bearings for wind alignment
│   └── sources.yaml
│
├── src/greenmachine/
│   ├── domain/
│   ├── config/
│   ├── features/
│   ├── scoring/
│   ├── validation/
│   ├── evaluation/
│   ├── ingestion/                      # GM-020 vertical slice
│   │   ├── mlb/                        # schedule + live feed client/parser
│   │   └── savant/                     # event export client/parser + metrics
│   ├── persistence/
│   ├── reporting/
│   ├── cli/
│   └── common/
│
├── tests/
│   ├── unit/ integration/ golden/ property/ architecture/ fixtures/
│
├── data/                               # gitignored
│   ├── raw/ snapshots/ evaluations/ outcomes/
│
└── scripts/
```

---

## 11. Architectural strengths

1. Determinism declared before line one — it cannot be retrofitted.
2. Rules as versioned, hashed, governed data; threshold tuning never touches Python.
3. Immutable append-only history, which is what makes honest configuration comparison possible.
4. Two explicit profiles instead of an implicit fallback — the previous silent season fallback
   was a correctness hazard, and removing it is the most valuable change in v6.2.
5. Explicit missing/insufficient/zero separation, and `NOT_EVALUABLE` instead of a manufactured
   partial score.
6. `GradeResult` / `EvaluationEnvelope` separation, which keeps `evaluated_at` outside the core.
7. Outcomes stored separately from pregame evaluations — structurally prevents hindsight
   contamination.
8. Advisory-only Validation Layer, keeping the score honest while retaining context.

---

## 12. Engineering risks

Ordered by severity. R1–R2 from the original review are now **mitigated by specification** and
are retained with their mitigations recorded.

### R1 — Input non-determinism · *mitigated, monitor*
Weather forecasts, provider revisions, and moving aggregates would break replay silently.
**Mitigation (approved):** frozen, content-hashed `InputSnapshot` as the unit of
reproducibility; weather is the grading-time forecast; windows rebuilt from event timestamps.
**Residual:** enforcement depends on the core being physically unable to fetch. Guarded by the
import-boundary test.

### R2 — Missing-data ambiguity · *mitigated*
**Mitigation (approved):** typed missing reasons, `insufficient_sample` distinct from missing,
no zero/NaN/None, `NOT_EVALUABLE` terminal state.
**Residual:** minimum sample thresholds (Q14) are undefined, so `sample_status` cannot be
resolved in production until they exist.

### R3 — Profile leakage · *substantially mitigated by v6.3*
A `LONG_TERM_2Y` value silently entering a `RECENT_7D` evaluation. **Mitigation:** since one
snapshot carries exactly one profile, there is no longer a shared container to borrow across;
profile is carried on every observation and validated at core entry; a mismatch raises rather
than degrades; golden tests cover both profiles from one source capture.
**Residual:** the join risk moves upstream — two snapshots from one source capture must not be
mixed during assembly. `source_capture_id` links them for research while `snapshot_id` and
`input_hash` keep them distinct, and an assembly-time test must assert no observation from one
profile reaches the other's snapshot.

### R4 — Numeric drift and float leakage (HIGH)
Two distinct hazards, both addressed by the v6.3 Decimal policy (ADR-0002, now Accepted).

*Boundary conventions.* Half-open `[lower, upper)` for scoring buckets vs. **inclusive
`[5, 20]`** for the Savant attack-angle event predicate. Two conventions in one system is a bug
magnet. Mitigation: separate layers (event eligibility in `features`, buckets in `scoring`),
two distinctly named helpers, ADR-0002, and explicit boundary tests at 5.0 and 20.0.

*Float leakage.* Fractional points make exact comparison mandatory: a strong-category test is
`category_score >= category_max × 0.75`, and in binary floats `2.25 >= 2.25` is not reliably
true once the left side is a sum. Mitigation: Decimal throughout, constructed only from strings
or integers, under a project-local context (precision 28, `ROUND_HALF_EVEN`).
**Residual, and the most likely real-world violation:** pandas reads numeric columns as
`float64` by default, so any column feeding scoring must be read with a string dtype. This
needs an explicit adapter-boundary test, because a leaked float produces plausible answers that
are subtly wrong at bucket edges rather than an obvious failure.

### R5 — Provider source fragility (HIGH)
Rendered extraction breaks when a page changes. **Mitigation:** narrow adapter, required column
validation, loud failure, fixture-based parser tests, never silently empty, and an explicit
`MissingReason` → possible `NOT_EVALUABLE` rather than a fabricated value.
**Related (NEW):** acquisition priority is now subordinate to point-in-time eligibility, so a
method that works today may be ineligible for a backtest. The eligibility decision and its
reasons must be recorded per observation, or backtest results become uninterpretable.

### R6 — Schema evolution of stored records (MEDIUM-HIGH)
Append-only history is worthless if year-old records become unreadable. Mitigation: mandatory
`schema_version`, explicit reader handling, typed error on unknown versions.

### R7 — Identity and joining across sources (MEDIUM)
Player, team, venue, and game IDs differ per provider; a wrong join is a silent correctness
bug. Mitigation: canonical ID registry with explicit crosswalks; unmapped entity is an error,
never a silent drop.

### R8 — Timezone, slate date, doubleheaders (MEDIUM · Q30)
Store UTC; define slate date once, in config; handle doubleheader game identity explicitly.

### R9 — Config validation gaps (MEDIUM)
Overlapping buckets, gaps, or allocations that do not sum will produce a plausible wrong grade.
Mitigation: strict + semantic validation at load; every committed config version validated in CI.

### R10 — Signal-rule interaction surprises · *confirmed intentional (Q26, Q27 closed)*
`AVOID` precedence can produce Grade S with signal `AVOID`. This is deliberate: the grade
reports the total score, the signal applies the prioritized rules. **Mitigation:** the override
reason (e.g. `power_profile_veto`) is a required field on the result and must be shown in the
interface, so the pairing never looks like a bug to a user. The 75% concern is dissolved by
fractional points: a 3-point category is strong at 2.25, which is now reachable.

### R11 — Backtest depth vs. metric availability (LOW-MEDIUM · Q20, Q22)
Bat tracking and attack-angle coverage cap full-fidelity backtest depth. A documented degraded
mode may be required.

---

## 13. Technical-debt watch list

| Item | Acceptable now because | Must be paid when |
|---|---|---|
| In-memory/file storage before SQLite | No DB code in Sprint 1 | Before the first real backtest run |
| Single model configuration version | Only one will exist | Before the first configuration comparison |
| Park factors as static versioned config | Correct for MVP | If they become derived or season-dependent |
| Decimal-from-string discipline enforced by test rather than by type | No values flow yet | If a third provider adapter lands without a shared string-carrying value type |
| pandas in `features` | Pragmatic for event filtering | Must never cross into `scoring` — NaN and dtype semantics are a determinism hazard |
| No canonical ID registry | One provider family today | At the second independent provider |
| Manual config authoring | Small surface | When profile × metric × bucket counts make hand-editing error-prone |
| Fuzzy scoring absent | Explicitly disabled by spec | Only if a future approved model version enables it for binary boundaries |
| Window agreement undefined | Research context only | Before it is displayed (Q29) |

---

## 14. Sprint dependency corrections

The earlier plan overstated availability. Corrected:

- **GM-004 depends on GM-003** — hashing cannot be built before the config object exists
- **GM-007 depends on GM-006** — repository ports need the record contracts
- **GM-008 depends on GM-003, GM-005 and GM-006** — the golden harness needs config, canonical
  serialization, and record contracts

**Engineering note.** The amendment lists GM-001, GM-005, GM-009, GM-010 as immediately
available. Strictly, GM-005, GM-009, and GM-010 all require the repository, package skeleton,
and CI from GM-001 to exist first. At t=0 only **GM-001** is startable; the other three unblock
immediately on its completion. The corrected graph in `SPRINT_1_PLAN.md` reflects this.

Also note: GM-005's precondition ("after the numeric policy is approved") is **fully satisfied**
as of v6.3. ADR-0002 is now **Accepted** and specifies the complete policy: Decimal
representation, permitted construction sources, the project-local context, the no-rounding rule,
canonical base-10 string serialization, and both interval conventions. GM-005 is
implementation-ready.

---

## 15. Approval and implementation status

Architectural direction **approved**; this document carries the **v6.3 Foundation
Clarifications** amendment on top of the v6.2 correction pass. Q25–Q28 and Q30 are closed;
outstanding items are tracked in `OPEN_QUESTIONS.md`.

**Sprint 1 is complete** (GM-001 through GM-010, closed out 2026-07-24; acceptance record in
`docs/SPRINT_1_CLOSEOUT.md`, cumulative approved archive `greenmachine-gm-008-r3.zip`, all
eight ADRs Accepted).

**Implemented and frozen:**

- the domain model — the full §4.1 vocabulary, immutable and construction-validated
- the deterministic numeric policy (ADR-0002): project-local Decimal context, string/int-only
  construction, distinct half-open and inclusive interval helpers
- configuration contracts: strict typed loading with every MODEL_SPEC §19 invariant enforced
  at load time (synthetic fixtures only — no production configuration exists)
- semantic configuration hashing and versioning, with modified-after-use detection
- canonical serialization: byte-identical encoding, evaluation record schema version 1
- the `InputSnapshot` and `GradeResult` contracts (ADRs 0003/0004): content-derived snapshot
  identity behind a construction authority; pure result variants separated from the envelope
- profile separation (ADR-0005): one snapshot, one profile, structurally enforced
- persistence contracts (ADR-0006): append-only ports, in-memory adapters, chain-hashed
  `OutcomeRevision`, and the reusable adapter contract suite
- the golden/property-test framework (ADR-0008): profile-aware golden cases, injected scorer
  boundary, deterministic Hypothesis seed, suite-wide parent and guarded-child network blocking

**Implemented for one vertical slice** — provider ingestion (§4.7), delivered by **GM-020** in
code version 0.2.0: one selected slate, one game, one hitter, the expected pitcher;
prospectively archived MLB/Savant raw responses under an immutable content-addressed manifest;
fail-closed schema contracts; normalized provider-neutral records; event-derived metrics in
exact Decimal; separate `RECENT_7D` and `LONG_TERM_2Y` snapshots from one source capture; and
deterministic offline replay. It computes no score, covers no full slate, and sources neither
weather nor park factors. Reference: [GM_020_VERTICAL_SLICE.md](GM_020_VERTICAL_SLICE.md). The
approved feasibility spike remains an isolated experiment outside production source. GM-040
adds a composition-only operator layer (`ingestion/operator.py` + the
`run_gm040_real_slice.py` script root): explicit selections, honest prospective vs.
retrospective-development classification, per-bundle operator reports, and idempotent
publication — one independent manifest-v1 bundle per hitter
([GM_040_REAL_SLICE.md](GM_040_REAL_SLICE.md)).

**Implemented as a usability prototype** — the manual-review dashboard (GM-030):
`reporting` view models and a read-only loader (with strict display adapters for the
audit/context reports) over approved archived GM-020 runs, presented by the repository-root
`streamlit_app.py` composition root (the only module that imports Streamlit,
architecture-enforced) with the static `hub_theme.py` presentation asset (original
GreenMachine console-style landing hub; no remote assets). Archived runs only; no automated
scoring; no live capture; Whiff Rate omitted by ruling; pitcher-specific metrics deferred;
not production-ready — UI refinement waits for Product Owner usage. Reference:
[STREAMLIT_PROTOTYPE.md](STREAMLIT_PROTOTYPE.md).

**Not yet implemented** (placeholder packages only; nothing here has any behavior):

- the production scoring engine (§4.4) and Validation Layer execution (§4.5) — Sprint 2
- production feature calculation (§4.3)
- daily orchestration beyond the serialization boundary (§4.6)
- production reporting/CLI behavior beyond the GM-030 prototype (§4.9)
- production weather ingestion and park-factor sourcing (§13 configs)
- bullpen- and pitcher-target features (deferred product backlog)

**Approved post-Sprint-1 sequence** (supersedes any earlier ordering that placed the full
grading core before ingestion): 1. Sprint 1 / GM-010 closeout → 2. provider architecture and
baseball/data-semantics review → 3. GM-020 thin production ingestion vertical slice →
4. first real `RECENT_7D` and `LONG_TERM_2Y` snapshots → 5. grading-core implementation and
real-data integration → 6. full-slate expansion.
