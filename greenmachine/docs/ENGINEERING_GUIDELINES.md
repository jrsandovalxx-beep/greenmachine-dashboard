# GreenMachine — Engineering Guidelines

**Specification version:** v6.3 — Foundation Clarifications
**Status:** v6.3 amendment applied, 2026-07-22
**Applies to:** all code in `src/greenmachine/`, `tests/`, and `config/`.

Rules of the road, so that a change made two years from now is as safe as one made today.

---

## 1. Priority order

1. **Correctness** over speed
2. **Determinism** over convenience
3. **Maintainability** over cleverness
4. **Readability** over abstraction
5. **Configuration** over hardcoded values

A change that makes the system faster but less explainable is a regression.

---

## 2. Determinism rules

**D1. The grading core is pure.** `domain/`, `scoring/`, and `validation/` perform no I/O, read
no clock, read no environment, use no randomness, and import neither `ingestion` nor
`persistence` nor `features`. Same `(EvaluationInput, Config)` ⇒ same `GradeResult`.

**D2. Time is injected, never read.** `datetime.now()` appears only at the composition root.
`evaluated_at` is produced by orchestration via an injected `Clock` and placed on the
**envelope** — never generated inside the core.

**D3. Ordering is explicit.** Any collection whose order affects output is sorted by a declared
key. Never rely on dict insertion order, set iteration, filesystem order, or query order.

**D4. Numeric policy is declared once (ADR-0002, Accepted).**
- **Decimal** for thresholds, values entering scoring, point values, category totals, and totals.
- **Never `Decimal(some_float)`.** Construct from provider strings, configuration strings, or
  integers. A value that has passed through `float` has already lost the guarantee.
- All grading arithmetic runs under a **project-local Decimal context**: precision **28**,
  rounding **`ROUND_HALF_EVEN`**. Never mutate the global context.
- Derived ratios and percentages are computed under that context and are **not quantized**
  before scoring.
- **No rounding before** bucket qualification, category aggregation, total aggregation, grade
  assignment, strong-category comparison, or signal assignment. Presentation rounding lives
  outside the core and never feeds back.
- **No epsilon comparisons anywhere in the grading path.** A tolerance in a review is evidence
  that a float leaked in.
- Canonical serialization emits Decimals as deterministic **base-10 strings**, never floats.
- Scoring buckets are **half-open `[lower, upper)`**; a value equal to a shared boundary belongs
  to the **upper** bucket; the terminal bucket is closed at the domain maximum.
- Grade cutoffs follow the same rule: D `[0,4)`, C `[4,6)`, B `[6,8)`, A `[8,10)`, S `[10,12]`.
- The Savant attack-angle event predicate is **independently inclusive at 5 and 20** and uses a
  separate, distinctly named helper.

**D5. Inputs are frozen before grading.** The core receives an immutable, content-hashed
snapshot. If the core *could* fetch, the core is wrong.

**D6. No NaN-carrying containers cross into the core.** pandas belongs to `ingestion` and
`features`. Inside the core, "missing" is a typed state, never `NaN` and never ambiguous `None`.
Numeric columns destined for scoring are read with a **string dtype** — pandas defaults to
`float64`, which silently violates D4.

**D7. `GradeResult` is unconditionally byte-identical** for identical inputs and config.
`EvaluationEnvelope` byte-identity additionally requires a fixed clock value — which is why
envelope determinism tests use `FixedClock`.

---

## 3. Window-profile rules

**W1. No silent cross-window fallback — ever.** A `RECENT_7D` evaluation may never consume a
`LONG_TERM_2Y` value, or vice versa. There is no automatic season fallback. If required data is
unavailable within the selected profile after approved **metric-level source** fallbacks, the
result is `NOT_EVALUABLE`.

**W2. Distinguish the two fallback kinds.** An approved *metric-level source* fallback (Savant
direct → structured extract → scrape → event-derived → configured proxy) is legitimate and
recorded in `attack_angle_source` / `fallback_used`. A *cross-window* substitution is
prohibited and is a different field entirely (`window_profile`). Code review treats any
expression that reads a profile other than the one being graded as a defect.

**W3. Profile is carried, not inferred.** `window_profile` appears on every
`MetricObservation`, on the `InputSnapshot`, on the `GradeResult`, and in evaluation identity.
The core validates profile consistency on entry and **raises** on mismatch rather than
degrading.

**W3a. One snapshot, one profile.** An `InputSnapshot` represents exactly one `WindowProfile`
and may never contain or produce both. One source capture may produce two independently frozen
profile-specific snapshots sharing a `source_capture_id`; they must differ in `snapshot_id`,
`input_hash`, `window_profile`, `window_start`, `window_end`, and observations. Assembly code
that could place an observation into the wrong profile's snapshot is a defect, and there is a
test for it.

**W4. No blending.** No averaging, no hybrid grade, no substitution. Window agreement is
computed in `reporting` over two stored results and never enters the core.

**W5. Profile-specific configuration, profile-invariant allocations.** Buckets and
minimum-sample requirements are addressable per profile without Python changes. Component
`max_points`, category maximums, the 12-point total, and grade cutoffs are **profile-invariant**
and validated as a single shared allocation structure. A schema that permits per-profile
allocations is itself the bug.

---

## 4. Sample-type rules

**S1. Every metric declares its own denominator.** A single generic sample count across metrics
is prohibited. Exit Velocity, Barrel %, Hard Hit %, and Sweet Spot % use `batted_ball_events`;
Bat Speed uses `swings`; Pull % on Air Balls uses `air_balls`; Ideal Attack Angle % uses valid
tracked events with a recorded attack angle.

**S2. Bat Speed is always labeled a swing sample**, never a batted-ball-event sample, in code,
storage, and presentation.

**S3. Three distinct states, and two distinct types.** `zero`, insufficient sample, and missing
are never collapsed. `SampleStatus` (`SUFFICIENT` | `INSUFFICIENT`) and `MissingReason` are
**separate enums**; `INSUFFICIENT` is not a `MissingReason` and must never appear in one.

**S3a. Insufficient samples are still scored.** A valid value below its configured minimum is
computed, **scored**, labeled `SampleStatus.INSUFFICIENT`, surfaced as an advisory Validation
Layer warning, and preserved in the audit trail. Zero eligible events or an unavailable value is
*missing*, which is a different thing. Minimum-sample configuration governs the label and the
warning; it does **not** gate scoring.

**S4. Full observation provenance.** Every `MetricObservation` preserves `component_id`,
`measurement_id`, `window_profile`, `window_start`, `window_end`, `as_of`, raw value, `unit`,
`sample_type`, `sample_count`, `minimum_sample_required`, `sample_status`, `data_coverage`,
`provider_id`, `acquisition_method`, `source_as_of`, retrieval timestamp, `source_capture_id`,
`fallback_used`, the bucket configuration used, and `missing_reason` where applicable. An
observation missing any required provenance field fails construction.

---

## 5. Point-in-time correctness rules

**P1. Reconstruct from event timestamps.** Never recompute a historical rolling window from a
current aggregate table. This is the single easiest way to leak the future, and it leaks
silently.

**P2. Strict `as_of` filtering.** No event or observation dated after `as_of` may enter an
evaluation, for any metric, under any profile, including pitcher season data and weather.

**P3. The filter is a pure, directly testable function** of `(events, as_of, profile)` — unit
tested with events exactly at `as_of`, one unit before, one unit after, and at both window
edges.

**P4. Coverage stays visible.** Requested period, actual period, coverage status, source
availability, and sample count are preserved. Partial coverage is never presented as complete.

**P5. Backtests use archived snapshots**, never live re-fetches. A backtest that re-queries a
provider is not a backtest.

**P6. Eligibility outranks priority.** An acquisition method may be used only if it can produce
the exact selected profile, the correct `window_start`/`window_end`, using no observation after
`as_of`. Select the highest-priority **eligible** method, not the highest-priority available
one, and record why each higher-priority method was ineligible. Expect today's slate and a
historical backtest to legitimately resolve the same component through different methods.

---

## 6. Ingestion, scraper, and parser expectations

Applies to every provider adapter, and with particular force to the Savant adapter (GM-020).

**I1. Provider vocabulary stops at the adapter.** No provider HTML column names, page-layout
details, parser selectors, URL assumptions, or endpoint-specific payload shapes appear in
`domain`, `scoring`, `validation`, `evaluation`, or stored records. What crosses is generic:
`provider_id` and `acquisition_method`. User-facing source labels are **derived** from those
two, never stored as an opaque composite string.

**I1a. Values cross as strings.** Numeric fields destined for scoring leave the adapter as
strings so they can be constructed into Decimals without passing through a binary float (D4).

**I2. Validate the schema you were promised.** Required columns/fields are asserted on every
retrieval. A schema change **fails loudly** — it never degrades into partial data.

**I3. Never silently return empty or zero.** An empty result is an explicit typed outcome that
becomes a modeled missing reason, not a `0`.

**I4. Record retrieval metadata** on every fetch: source identifier or URL, retrieval
timestamp, `source_as_of`, coverage bounds, adapter/parser version, and a raw content hash (or
the raw payload) where practical.

**I5. Fixture-based parser tests are mandatory.** Every parser is tested against saved fixture
payloads, including at least one malformed and one schema-changed fixture that must raise.

**I6. Respect source access limits.** No aggressive polling, no unbounded retries, no parallel
hammering. Rate limits are configuration, not hardcoded.

**I7. Source labels are preserved end to end**, so direct, structured-extract, scraped,
derived, and proxy values remain distinguishable in backtesting.

**I8. The proxy is a different measurement.** `attack_angle_threshold_proxy` and
`ideal_attack_angle_pct` are two mutually exclusive measurements of the one
`attack_angle_quality` component. Exactly one satisfies the component per evaluation. Never
score both, average both, blend both, write one under the other's name, or apply
ideal-percentage buckets to the proxy unless buckets are explicitly configured for that
measurement. Display "Ideal Attack Angle %" or "Attack Angle Proxy" accordingly.

---

## 7. Code standards

- **Python 3.11+**, pinned in `pyproject.toml`
- **Type hints everywhere**; `mypy --strict` on `src/`; no unexplained `Any`
- **Immutability by default** — frozen models; mutation is explicit, local, and justified
- **`ruff format` + `ruff check`**, not debated in review
- **Baseball vocabulary, not abstractions** — `ideal_attack_angle_pct`, not `metric_7`;
  `CategoryScore`, not `ScoreNode`. The Product Owner should be able to read `domain/`.
- **Identifiers match `GLOSSARY.md` exactly.** A drift test enforces this.
- **No inheritance for code reuse.** Composition, plain functions, Protocols for ports.
- **Typed, specific errors** carrying structured context. No bare `except Exception`.
- **No silent defaults.** Missing config is an error; missing data is a modeled state that
  reaches the output.

---

## 8. Configuration standards and governance

- Config lives in `config/`, is version-controlled, and is **never written by the application**
- YAML for authoring; validated into typed objects at load; no dictionaries escape `config/`
- **Strict parsing:** unknown keys rejected, required keys enforced, no silent defaults
- **Semantic validation at load time** — the full invariant list is MODEL_SPEC §19; every rule
  there is a load failure, not a warning. In summary:
  - every bucket's points are `>= 0` and `<= max_points`; the strongest qualifying bucket awards
    exactly `max_points`
  - monotonicity: `higher_is_better` points never decrease as values increase;
    `lower_is_better` points never increase
  - every valid in-domain value resolves to exactly one bucket; no gaps, no overlaps
  - `bucketed` and `binary` use **separate validated schema shapes**; binary components are
    **not** forced to declare continuous bucket ranges
  - component `max_points` sum exactly to the category maximum; category maxima sum exactly
    to 12; **allocations are identical across profiles**
  - grade cutoffs ordered, profile-invariant, covering `[0, 12]` without gaps or overlaps
  - every category references only defined components, and every defined component is referenced
  - profile-specific bucket sets exist for every component declaring that profile, and
    measurement-specific bucket sets exist for every declared measurement
  - signal rules reference defined grades, categories, thresholds, and override reason codes
  - all thresholds parse as Decimals from their configuration strings
- **`config_hash` is semantic:** comments, formatting, indentation, and key order must not
  change it; any threshold, allocation, cutoff, or signal change must
- **Once a configuration version has produced an evaluation, it is immutable.** Fix forward with
  a new version.
- **Every production configuration change requires:** a new model configuration version,
  Product Owner approval, strict schema and semantic validation, golden-test review, historical
  comparison or backtest where applicable, changelog documentation, and preservation of the
  previous version.
- **Engineering does not invent baseball thresholds.** Unresolved values go to
  `OPEN_QUESTIONS.md`. Test fixtures use obviously synthetic values that could never be mistaken
  for production settings.

---

## 9. Testing strategy

### 9.1 Unit
Every pure function, with emphasis on **boundaries**: exact bucket edges, values one unit of
precision either side, domain minima and maxima, and each missing-data path.

### 9.2 Numeric policy tests (mandatory)
- No `Decimal` in the codebase is constructed from a `float`; asserted by a static check.
- Arithmetic runs under the project-local context; the global context is never mutated.
- A fractional-allocation fixture sums exactly: a 3-point category scored `0.75 + 0.75 + 1.5`
  compares equal to `3`, and a strong-category test at exactly `2.25` returns true.
- Canonical serialization of a Decimal round-trips through JSON unchanged, as a base-10 string.
- An adapter-boundary test asserts that values arriving from a fixture provider payload are
  strings, not floats.

### 9.3 Attack-angle boundary tests (mandatory, explicit)
The Ideal Attack Angle predicate is **inclusive at both ends**: `5 ≤ angle ≤ 20`. Required
cases: `4.9` excluded, `5.0` **included**, `5.1` included, `19.9` included, `20.0` **included**,
`20.1` excluded. A test must also assert that this inclusive predicate is *not* implemented with
the half-open bucket helper — the two conventions are deliberately different and must not share
an implementation.

### 9.4 Property (`hypothesis`)
- Bucket resolution is **total**: every in-domain value maps to exactly one bucket
- Bucket scoring is **monotonic** in the declared direction
- Component score ≤ `max_points`; category score ≤ category maximum; total ≤ 12 — for all inputs
- Grading is **idempotent** across repeated calls and process restarts
- `config_hash` is stable under key reordering and reformatting
- No sequence of Decimal operations under the declared context produces a value outside its
  declared domain

### 9.5 Golden tests — **profile-specific**
Every golden case declares its `window_profile` and references one profile-specific snapshot.
Coverage must include, at minimum: a `RECENT_7D` case and a `LONG_TERM_2Y` case from the **same
source capture** (two snapshots sharing a `source_capture_id`), a `SampleStatus.INSUFFICIENT`
case that is **still scored** and raises an advisory warning, a `NOT_EVALUABLE` case, one case
per signal, a signal-override case (Grade S with `AVOID` and reason `power_profile_veto`), a
fractional-score case, one case per attack-angle measurement, and a grade-boundary case at each
cutoff. Any change to scoring must appear as a golden diff, or the
change is untested. Goldens are regenerated only by deliberately running the update script.

### 9.6 Integration
Orchestration end to end with fake adapters. **No network in the test suite, ever** — enforced
by a blocked-socket fixture.

### 9.7 Determinism
Grade the same fixture in two separate processes; assert byte-identical serialized
`GradeResult`. Envelope determinism uses `FixedClock`. Runs in CI on every commit.

### 9.8 Architecture tests
Automated import-boundary checks: `domain` imports nothing internal; `scoring` and `validation`
import no `ingestion`, `persistence`, or `features`; the core imports no pandas, Streamlit,
Plotly, SQLite, or network client. A violation fails the build.

### 9.9 Config tests
Every committed config version loads and semantically validates in CI. A broken config fails the
build, not the slate.

**Standards:** ≥95% meaningful coverage on `scoring/`, `config/`, `domain/`; tests deterministic
and order-independent; no test depends on the current date.

---

## 10. Documentation standards

- **Docstrings** stating baseball meaning, assumptions, and raises — not just mechanics
- **ADRs** for every expensive-to-reverse decision; append-only, superseded ones marked
- **`MODEL_SPEC.md` owns product behavior; `ARCHITECTURE.md` owns engineering structure.**
  Never mix them. A PR that puts a baseball rule in ARCHITECTURE.md is rejected.
- **`GLOSSARY.md`** defines every metric exactly; unresolved formulas stay marked as Product
  Owner decisions
- **`OPEN_QUESTIONS.md`** is the live register. Nothing is implemented on a guess; closed
  questions are never deleted
- **`CHANGELOG.md`** lists product-specification, code, model-configuration, and schema changes
  separately

---

## 11. Versioning

Four independent streams: **product specification** (v6.2), **code** (SemVer), **model
configuration** (SemVer), **evaluation schema**. All four recorded on every stored evaluation.
Four reasons to change, never conflated.

---

## 12. Definition of Done

- [ ] Acceptance criteria met
- [ ] `mypy --strict` passes; lint and format clean
- [ ] Unit tests written; boundary cases covered
- [ ] Architecture import-boundary tests pass
- [ ] Determinism test passes
- [ ] Golden tests updated **only** for intended model changes, with both profiles considered
- [ ] Public functions documented
- [ ] No hardcoded thresholds, magic numbers, or silent defaults
- [ ] No cross-window substitution introduced; no snapshot carries two profiles
- [ ] No `Decimal` constructed from a `float`; no rounding before a grading comparison
- [ ] Identifiers match `GLOSSARY.md`
- [ ] CHANGELOG updated
- [ ] New ambiguity logged in `OPEN_QUESTIONS.md` rather than guessed at

---

## 13. Review checklist

1. Could this produce a different answer tomorrow for the same inputs? → block
2. Is a baseball rule now in Python instead of config? → block
3. Could a value from one window profile reach the other, or one snapshot carry two? → block
4. Is a Decimal built from a float, or is anything rounded before a grading comparison? → block
5. Can the evaluation still explain itself completely, including why a lower-priority
   acquisition method was chosen? → block
6. Does this make replay or backtest harder? → block
7. Is history mutated anywhere? → block
8. Did the core gain a dependency on time, I/O, pandas, or a provider? → block
9. Is missing data represented as zero, or an insufficient sample treated as missing? → block
10. Is this abstraction earned by two existing use cases? → simplify
11. Would a new engineer understand this in six months without asking? → clarify

---

## 14. Anti-patterns (forbidden)

- `datetime.now()` outside the composition root, or `evaluated_at` generated inside the core
- Thresholds, bucket edges, park constants, or weather constants as literals in `src/`
- Silent cross-window or season fallback
- Averaging or blending window profiles; producing a hybrid grade
- A single `InputSnapshot` carrying or producing two window profiles
- Per-profile `max_points`, category maximums, or grade cutoffs
- `Decimal(some_float)`; epsilon comparisons in the grading path; rounding before a bucket,
  grade, strong-category, or signal comparison; serializing a score as a binary float
- Treating insufficient sample as missing, or putting `INSUFFICIENT` in `MissingReason`
- Refusing to score a valid value because its sample is below the configured minimum
- Treating missing data or insufficient sample as zero
- `NaN` or ambiguous `None` inside domain or scoring objects
- Manufacturing a partial score by dropping or reweighting unavailable metrics
- Scoring raw average attack angle as monotonic higher-is-better
- Labeling proxy values as Savant Ideal Attack Angle %, or scoring both attack-angle
  measurements in one evaluation
- Applying ideal-percentage buckets to the proxy without measurement-specific configuration
- Storing a provider-specific composite source label instead of `provider_id` +
  `acquisition_method`
- Choosing the highest-priority *available* acquisition method rather than the highest-priority
  *eligible* one
- Generating a replacement internal `game_id` when an official canonical identifier exists
- Converting free-text bullpen notes into numerical scoring
- Mutating or recomputing a stored evaluation, snapshot, config version, or outcome
- Attaching outcome data to a pregame evaluation record
- `except Exception: pass`
- Database, network, or provider access from `scoring/`
- Speculative generality — plugin systems and abstract hierarchies for implementations that do
  not exist
- Premature optimization; a slate is small and correctness dominates
- Adding metrics or changing the model without Product Owner approval
