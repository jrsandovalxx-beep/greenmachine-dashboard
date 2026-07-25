# Sprint 1 — Foundations

**Specification version:** v6.3 — Foundation Clarifications
**Status:** **SPRINT 1 COMPLETE** — closed out by GM-010 on 2026-07-24. Every ticket below is
implemented, independently reviewed, and accepted; the approved cumulative archive is
`greenmachine-gm-008-r3.zip`. See `docs/SPRINT_1_CLOSEOUT.md` for the acceptance record.

| Ticket | Accepted as | Ticket | Accepted as |
|---|---|---|---|
| GM-001 | initial delivery | GM-006 | r2 |
| GM-002 | r2 | GM-007 | r1 |
| GM-003 | r3 | GM-008 | r3 |
| GM-004 | r1 | GM-009 | r2 |
| GM-005 | r2 | GM-010 | closeout (this revision) |

**Code version note (recorded ruling).** The original plan targeted code version 0.2.0 at
sprint close. The approved GM-008-r3 archive freezes `src/` — including the version constant —
byte-identical, and the GM-010 closeout is documentation-only by Product Owner ruling, so the
original 0.2.0 target was **not applied** and the code version remained **0.1.0** through the
closeout. Any future version change requires an explicit ruling in the ticket that makes it;
no version was pre-assigned to any future ticket. (GM-020 subsequently carried exactly such a
ruling and moved the code to 0.2.0.)

---

## Sprint goal

> Build the deterministic, configuration-driven skeleton the grading engine will plug into —
> and prove the determinism and boundary guarantees with automated tests **before** any
> baseball logic or production threshold exists.

*Closeout interpretation (recorded 2026-07-24):* read "before any baseball logic or production
threshold exists" as **"before runtime grading logic or a production model configuration
exists."** `MODEL_SPEC.md` has always contained approved specification rules and defaults —
the 15% qualifying pitch-usage default, the grade boundaries, the signal conditions, the
5°–20° Ideal Attack Angle definition, the 75% strong-category rule. What Sprint 1 excluded was
implementing any of them as scoring behavior in `src/` or publishing a production
model-configuration version; the synthetic test configuration is not a production model
configuration.

The most important outcome is a CI job that fails if the system becomes non-deterministic, if
the import boundaries are breached, or if a value from one window profile could reach the other.

---

## In scope

- Repository and package scaffolding
- Tooling and CI
- Domain vocabulary and immutable contracts (including `WindowProfile`, component/measurement
  identifiers, `SampleStatus`, `MissingReason`, `provider_id`, `acquisition_method`)
- Configuration schema and strict loader, with profile-specific structure
- Config canonicalization and semantic hashing
- Determinism primitives
- `GradeResult` and `EvaluationEnvelope` contracts
- `InputSnapshot` contract
- `OutcomeRecord` contract — **schema boundary only** (see GM-006 note)
- Append-only persistence ports
- In-memory repository contract suite
- Testing infrastructure
- Error taxonomy
- Structured logging baseline
- ADR and documentation process

## Out of scope

Production bucket thresholds · real grading logic · final metric point allocations · Savant
scraping · Savant ingestion adapter · live provider calls · weather provider implementation ·
pitch-level ingestion · SQLite production adapter · Streamlit pages · backtesting engine ·
simulation engine · signal execution code · real daily pipeline.

Sprint 1 may **define** interfaces and schemas these capabilities need. It must not implement
them.

**Engineering must not invent:** metric point allocations, bucket thresholds, minimum sample
sizes, park-factor thresholds, wind cosine thresholds, or proxy definitions. Test fixtures use
obviously synthetic values that could not be mistaken for production settings.

---

## Blocked-by table

*Historical planning record — every Sprint 1 ticket below is now complete. GM-020 remains
deferred to Sprint 3+.*

| Ticket | Depends on tickets | Blocked by questions | Startable at t=0 |
|---|---|---|---|
| GM-001 | — | — | **Complete** |
| GM-002 | GM-001 | — (Q1–Q6, Q25–Q28, Q30 closed) | **Yes — GM-001 complete** |
| GM-003 | GM-001, GM-002 | — (Q25 closed). Q11–Q16 block *production config*, not the schema | No |
| GM-004 | GM-003 | — | No |
| GM-005 | GM-001 | — (numeric policy approved, MODEL_SPEC §4) | No |
| GM-006 | GM-002, GM-004, GM-005 | — | No |
| GM-007 | GM-006 | — | No |
| GM-008 | GM-003, GM-005, GM-006 | — | No |
| GM-009 | GM-001 | — | No |
| GM-010 | GM-001 | — | No |
| GM-020 | Sprint 3+ | Q19, Q20, Q21, Q23 | Deferred |

**Final status.** All ten Sprint 1 tickets are delivered and accepted. Work proceeded one
ticket at a time in the order GM-002 → GM-005 → GM-009 → GM-003 → GM-004 → GM-006 → GM-007 →
GM-008 → GM-010, matching the suggested order below (with the approved Savant feasibility
spike executed between GM-007 and GM-008 as an isolated experiment).

**Precondition fully satisfied.** GM-005's precondition — "after the numeric policy is approved"
— is met in full by v6.3. ADR-0002 is **Accepted** and specifies Decimal representation,
permitted construction sources, the project-local context (precision 28, `ROUND_HALF_EVEN`), the
no-rounding rule, canonical base-10 string serialization, and both interval conventions.

---

## Dependency graph

```
GM-001 ─┬─────────────────────────────────────────────▶ GM-009
        ├─────────────────────────────────────────────▶ GM-010
        ├─────────────────────────────────────────────▶ GM-005 ─┐
        └─ GM-002 ─▶ GM-003 ─▶ GM-004 ────────────────────────┬─┤
                        │                                     ▼ ▼
                        │                                    GM-006 ─▶ GM-007
                        └──────────────────────────────────────┬─────────┘
                                                               ▼
                                                            GM-008

                                    (GM-020 Savant adapter — deferred, Sprint 3+)
```

**Suggested order:** ~~GM-001~~ (done) → **GM-002** → GM-005 → GM-009 → GM-003 → GM-004 →
GM-006 → GM-007 → GM-008 → GM-010.

GM-002 is pulled forward because v6.3 closed every question its vocabulary depended on, and
because GM-003, GM-006, and the architecture tests all key off its identifiers.

GM-005 and GM-009 are pulled early because every later ticket is cleaner once the numeric policy
and error taxonomy exist. GM-010 closes last so it can record what actually happened.

**One ticket per request.** Implementation proceeds one ticket at a time.

---

## Tickets

### GM-001 — Repository scaffolding, tooling, and CI · **COMPLETE (approved 2026-07-22)**

**Goal.** A reproducible development environment and a CI pipeline that enforces the engineering
guidelines mechanically rather than socially.

**Files.** `pyproject.toml` · `.gitignore` · `.pre-commit-config.yaml` ·
`.github/workflows/ci.yml` · `src/greenmachine/__init__.py` (version constant only) ·
`tests/conftest.py` · `Makefile`

**Dependencies.** None.

**Acceptance criteria**
- Package installs editable on a clean environment; Python version pinned
- `ruff format --check`, `ruff check`, `mypy --strict src/` pass on the empty package
- `pytest` runs and reports zero tests without error
- CI runs lint, type check, and tests on every push; any violation fails the build
- Pre-commit hooks installed for format, lint, trailing whitespace
- Directory skeleton from ARCHITECTURE.md §10 exists, including `ingestion/savant/` as an empty
  documented package and `data/` gitignored
- `pyproject.toml` records the code version; no baseball content anywhere

**Tests**
- `test_package_imports` — package imports and exposes `__version__`
- `test_version_matches_pyproject`
- CI verification: push a deliberately mis-formatted commit to a scratch branch and confirm the
  build fails

---

### GM-002 — Domain model and vocabulary · **COMPLETE (accepted r2)**

**Goal.** The immutable, typed vocabulary shared between the baseball specification and the
code, with no behavior attached.

**Files.** `src/greenmachine/domain/enums.py` · `entities.py` · `values.py` · `observations.py` ·
`results.py` · `tests/unit/domain/` · `tests/architecture/test_import_boundaries.py`

**Dependencies.** GM-001 (complete).

**Acceptance criteria**
- `WindowProfile` enum with exactly `RECENT_7D` and `LONG_TERM_2Y`, each carrying its display
  name ("Recent — Last 7 Days", "Long-Term — Rolling 2 Years")
- **`ComponentId` enumerates exactly the eleven scored components** from MODEL_SPEC §2 —
  `exit_velocity`, `barrel_pct`, `hard_hit_pct`, `pitch_mix_pressure`,
  `put_away_pitch_exploitation`, `sweet_spot_pct`, **`attack_angle_quality`**, `bat_speed`,
  `pull_pct_air_balls`, `park`, `weather`. Chase Rate, Zone Contact %, and Whiff Rate must not
  appear.
- **`MeasurementId` is a separate enum** containing `ideal_attack_angle_pct` and
  `attack_angle_threshold_proxy`. The types must make it impossible for one observation to carry
  two measurements for one component.
- Validation inputs are enumerated separately from scored components
- `SampleType`, `SampleStatus` (`SUFFICIENT`/`INSUFFICIENT`), `MissingReason` (the eight members
  in MODEL_SPEC §8.2, **with no insufficient-sample member**), `EvaluationStatus`, `Grade`,
  `Signal`, `PitcherRole`, **`ProviderId`**, and **`AcquisitionMethod`** (`direct_aggregate`,
  `structured_extract`, `rendered_scrape`, `event_derived`, `configured_proxy`) match MODEL_SPEC
  and GLOSSARY exactly
- **No composite provider-specific source label type exists.** The former `AttackAngleSource`
  enum is replaced by `ProviderId` + `AcquisitionMethod`; user-facing labels are derived.
- `MetricObservation` requires every provenance field in MODEL_SPEC §8.4 — including
  `component_id`, `measurement_id`, `provider_id`, `acquisition_method`, `source_capture_id`,
  and `sample_status` — and construction fails if any is absent
- Scores and metric values are typed `Decimal`; no domain field entering scoring is typed `float`
- Game identity carries the official provider `game_id`, `slate_date` (official scheduled MLB
  date), UTC scheduled start, venue-local scheduled time, and venue timezone. No internal
  replacement game ID is generated.
- Missing is a first-class typed state with a reason — never `None` used ambiguously, never `NaN`
- All types frozen and hashable; invalid construction raises a typed error
- `domain` imports nothing internal and no pandas/Streamlit/Plotly/SQLite/network client

**Tests**
- Valid construction for each type; each validation rule rejects out-of-range input
- Immutability — attribute assignment raises
- Equality and hashing behave by value
- **Architecture test:** `domain` has no internal or forbidden imports
- **Drift test:** every `ComponentId`, `MeasurementId`, and enum member has a `GLOSSARY.md`
  entry, and every glossary identifier exists in code
- **Regression test:** removed Form metrics are absent from `ComponentId`
- **Regression test:** `MissingReason` has no insufficient-sample member, and
  `SampleStatus.INSUFFICIENT` is not assignable where a `MissingReason` is required
- **Regression test:** `ComponentId` contains `attack_angle_quality` and does **not** contain
  `ideal_attack_angle_pct`; `MeasurementId` contains both measurements
- **Static test:** no domain field carrying a value that enters scoring is typed `float`

---

### GM-003 — Configuration schema and strict loader · **COMPLETE (accepted r3)**

**Goal.** Make the grading rules data. Load YAML into validated typed objects, failing loudly
and specifically before anything can produce a wrong grade.

**Files.** `src/greenmachine/config/schema.py` · `loader.py` · `validation_rules.py` ·
`errors.py` · `tests/fixtures/config/` (synthetic only) · `tests/unit/config/`

**Dependencies.** GM-001 (complete), GM-002. **Schema shape unblocked — Q25 closed.**

**Acceptance criteria**
- Loader returns a fully typed frozen config object; no dictionaries escape the module
- Strict parsing: unknown keys error, missing required keys error, no silent defaults
- Schema supports **profile-specific** bucket sets and minimum-sample requirements, and
  **measurement-specific** bucket sets, with no Python change needed to add either
- **Allocations are profile-invariant**: `max_points`, category maximums, and grade cutoffs live
  in a single shared structure. A schema that permits per-profile allocations fails review.
- **`bucketed` and `binary` use separate validated schema shapes.** Binary components declare a
  qualification predicate and its point award and are **not** required to declare continuous
  bucket ranges.
- Each component declares: `component_id`, `scoring_method`, `direction`, `max_points`,
  `sample_type`, `minimum_sample_required`, missing-data behavior, applicable window profiles;
  bucketed components additionally declare a domain, ordered boundaries, and per-bucket points
- All numeric configuration values are parsed into `Decimal` **from their configuration
  strings**, never via `float`
- Semantic validation at load time enforces **every invariant in MODEL_SPEC §19**, including:
  - bucket points `>= 0` and `<= max_points`; the strongest qualifying bucket awards `max_points`
  - monotonicity in the declared direction
  - every in-domain value resolves to exactly one bucket; no gaps, no overlaps
  - component `max_points` sum exactly to the category maximum; category maxima sum to 12
  - allocations identical across profiles
  - grade cutoffs ordered, profile-invariant, covering `[0, 12]`
  - every category references only defined components; every defined component is referenced
  - profile-specific bucket sets exist for every component declaring that profile;
    measurement-specific bucket sets exist for every declared measurement
  - signal rules reference defined grades, categories, thresholds, and override reason codes;
    priority order explicit
  - fuzzy scoring absent or explicitly disabled
- Errors name the file, key path, and specific violation
- **No production thresholds committed.** Only synthetic fixture configs. No file under
  `config/model/` is finalized in this ticket.
- No threshold or bucket edge appears anywhere in `src/`

**Tests**
- Valid synthetic config loads and round-trips to the expected typed structure
- One failing case per MODEL_SPEC §19 invariant, each asserting the specific error type and that
  the message names the offending key: overlapping buckets · bucket gap · negative bucket points ·
  bucket points exceeding `max_points` · strongest bucket not awarding `max_points` ·
  non-monotonic points for each direction · unknown key · missing key · undefined component
  reference · orphan component · allocations not summing to the category maximum · category maxima
  not summing to 12 · **per-profile allocations present** · unordered cutoffs · cutoff gap ·
  missing missing-data policy · missing profile bucket set · missing measurement bucket set ·
  binary component forced to declare bucket ranges · fuzzy scoring enabled
- Unit: a fractional allocation fixture validates and sums exactly in `Decimal`
- Unit: no configuration value reaches a typed object via `float`
- Property: a config whose buckets cover the domain resolves every in-domain value to exactly one
  bucket (totality; resolution logic itself is Sprint 2)
- CI: every committed config version loads and validates

---

### GM-004 — Configuration versioning and semantic hashing · **COMPLETE (accepted r1)**

**Goal.** Give every configuration version a stable semantic identity, so any stored evaluation
ties to the exact rules that produced it and two versions can be compared later.

**Files.** `src/greenmachine/config/versioning.py` · `hashing.py` · `tests/unit/config/`

**Dependencies.** GM-003.

**Acceptance criteria**
- A model configuration version is resolvable by identifier and exposes a `config_hash`
- The hash is **semantic**: computed over canonicalized content — sorted keys, normalized
  numeric representation, fixed UTF-8, normalized newlines
- Comments, formatting, indentation, and key order **do not** change the hash; any threshold,
  allocation, cutoff, or signal change **does**
- Stable across processes and machines; no `PYTHONHASHSEED` dependence
- Multiple versions load simultaneously without interference
- No write path to `config/` exists in application code
- Immutability guard: a documented mechanism to detect that a configuration version which has
  already produced an evaluation has been modified on disk

**Tests**
- Hash stability across key reordering, indentation changes, comment insertion
- Hash changes on any single threshold, allocation, cutoff, or signal-rule change
- Hash identical across two subprocess invocations
- Two versions loaded together retain independent hashes and content
- Unknown version identifier raises a typed, informative error
- Modified-after-use detection fires on a tampered fixture

---

### GM-005 — Determinism primitives · **COMPLETE (accepted r2)**

**Goal.** The shared utilities that make determinism achievable rather than aspirational.

**Files.** `src/greenmachine/common/numeric.py` · `clock.py` · `serialization.py` · `ids.py` ·
`docs/adr/0002-numeric-and-bucket-boundary-policy.md` · `tests/unit/common/` ·
`tests/property/test_determinism.py`

**Dependencies.** GM-001 (complete). Numeric policy **fully specified and accepted** —
MODEL_SPEC §4 and ADR-0002 (Accepted). Implementation-ready.

**Acceptance criteria**
- **Decimal helpers**: a project-local context (precision 28, `ROUND_HALF_EVEN`) that never
  mutates the global context, and constructors that accept **strings and integers only**
- A static check rejects any `Decimal(...)` constructed from a `float` anywhere in `src/`
- One rounding policy, implemented once, used everywhere; ADR-0002 (Accepted) records it
- **No rounding helper is reachable from bucket, grade, strong-category, or signal comparison
  paths**; presentation rounding lives in its own module, outside the core
- Half-open interval helper: a value equal to a shared boundary resolves to the **upper**
  bucket; terminal bucket closed at the domain top
- **A separate, distinctly named inclusive-range helper** exists for event-level eligibility
  predicates such as the 5°–20° attack-angle rule, so the two conventions cannot be confused or
  accidentally shared
- Grade-cutoff resolution uses the internal score, with a documented separation from presentation
  rounding
- `Clock` protocol; `SystemClock` instantiated only at the composition root; `FixedClock` used in
  tests
- Canonical serialization is byte-identical for equal objects: sorted keys, **Decimals emitted
  as deterministic base-10 strings**, no binary floats, no locale or platform dependence
- Identifiers derived deterministically from content — no randomness, no UUID4, no time
- CI static check: no `datetime.now`, `random`, or `uuid4` outside the composition root

**Tests**
- `ROUND_HALF_EVEN` at `.5` boundaries, negatives, and the declared precision limit
- A fractional fixture: `0.75 + 0.75 + 1.5` compares exactly equal to `3`; a strong-category test
  at exactly `2.25` against a 3-point maximum returns true
- Decimal round-trips through canonical serialization unchanged, as a base-10 string
- The static no-`Decimal(float)` check fails on a deliberately seeded violation
- Half-open boundary behavior at an exact edge and one precision unit either side
- **Inclusive-range helper tested at both closed ends**, plus a test asserting the two helpers
  are distinct implementations with different boundary behavior at the same input
- Grade-cutoff assignment at exactly 4, 6, 8, 10, and 12, and just below each
- Property: canonical serialization stable under dict key reordering
- Determinism: serialize the same object graph in two subprocesses; assert byte equality
- `FixedClock` fully controls time in a dependent component
- CI static check fails on a deliberately seeded violation

---

### GM-006 — GradeResult, EvaluationEnvelope, InputSnapshot, and OutcomeRecord contracts · **COMPLETE (accepted r2)**

**Goal.** Define the immutable, self-describing contracts that make a grade explainable and
reproducible forever — with the pure result cleanly separated from orchestration metadata.
Contracts only; no grading.

**Files.** `src/greenmachine/domain/grade_result.py` · `envelope.py` · `snapshot.py` ·
`outcome.py` · `src/greenmachine/evaluation/serialization.py` ·
`docs/adr/0004-graderesult-vs-evaluationenvelope.md` ·
`docs/adr/0003-snapshot-and-point-in-time-policy.md` ·
`docs/adr/0006-outcomes-separate-from-evaluations.md` · `tests/unit/domain/` ·
`tests/fixtures/evaluations/`

**Dependencies.** GM-002, GM-004, GM-005.

**Acceptance criteria**

*GradeResult (pure)*
- Contains only: evaluation status, selected `window_profile`, metric observations
  (`component_id` plus its single `measurement_id` slot — exactly one `MeasurementId` for
  `attack_angle_quality`, `None` for every other component, per MODEL_SPEC §9.1.1; never two
  measurements for one component), bucket results including the bucket
  configuration used, component scores, category scores, total score (when `EVALUATED`), grade
  (when `EVALUATED`), signal **and its override reason** (when `EVALUATED`), validation findings
  including one advisory warning per `SampleStatus.INSUFFICIENT` component, and the complete
  audit derivation
- All scores and metric values are `Decimal`; none is `float`
- Contains **no** timestamp, no identity, no version, no hash
- `NOT_EVALUABLE` is representable **without** a score, grade, or signal, and **requires** a
  recorded list of the required inputs that were unavailable with their missing reasons and every
  attempted fallback
- Type-level impossibility: an `EVALUATED` result without a score, or a `NOT_EVALUABLE` result
  with one, cannot be constructed

*EvaluationEnvelope*
- Carries `evaluation_id`, `snapshot_id`, **`source_capture_id`**, `evaluated_at`, code version,
  model configuration version, **product-specification version**, `schema_version`,
  `config_hash`, `input_hash`, subject identity (official provider `game_id`, `slate_date`,
  `batter_id`, `expected_starting_pitcher_id`, `window_profile`), pitcher role
  (`opener` | `expected_starter` | `uncertain`), provenance, and `supersedes`
- `evaluated_at` is accepted as a parameter; the envelope never generates it

*InputSnapshot*
- **Represents exactly one `WindowProfile`.** The type must make a two-profile snapshot
  unconstructable.
- Frozen and content-hashed; records `as_of`, resolved `window_start`/`window_end`,
  `source_capture_id`, `provider_id`/`acquisition_method`/`source_as_of` per input, whether
  weather was a grading-time forecast, why each higher-priority acquisition method was
  ineligible, and full coverage status (requested period, actual period, coverage status, source
  availability, sample count)
- Two snapshots from one source capture share a `source_capture_id` and differ in `snapshot_id`,
  `input_hash`, `window_profile`, `window_start`, `window_end`, and observations

*OutcomeRecord (schema boundary only)*
- A minimal separate contract carrying game/batter identity and the primary initial outcome —
  whether the batter hit at least one home run in the evaluated game
- **Structurally impossible** to attach an outcome to a `GradeResult` or `EvaluationEnvelope`;
  no outcome field exists on either type
- No outcome ingestion, no additional outcome fields
- *Scope note flagged for approval:* the amendment permits outcome work in Sprint 1 only "if
  required for the schema boundary." It is required — without the contract, nothing prevents an
  outcome field being added to the envelope later. Scope is limited to the contract and its tests.

*General*
- Records are immutable and expose no mutating operation
- Serialization round-trips losslessly and canonically
- A record with an unknown or newer `schema_version` raises a typed error naming the version;
  never silently misinterpreted
- A record is sufficient to reconstruct the grading decision given only the referenced config
  version and input snapshot

**Tests**
- Round-trip serialize/deserialize preserves every field exactly
- Canonical serialization of an equal `GradeResult` is byte-identical **without** a fixed clock
- Envelope byte-identity holds under `FixedClock` and differs when the clock differs — asserting
  the documented determinism scope
- Immutability enforced on all four contracts
- `NOT_EVALUABLE` without score/grade/signal constructs successfully; with them, raises
- `EVALUATED` missing a score raises
- Unknown `schema_version` raises a typed error naming the version
- Missing required provenance or coverage field fails construction
- **Structural test:** no outcome-shaped field exists on `GradeResult` or `EvaluationEnvelope`
- **Structural test:** `GradeResult` contains no timestamp or version field
- Golden: a hand-authored fixture record deserializes to the expected object

---

### GM-007 — Persistence ports with append-only semantics · **COMPLETE (accepted r1)**

**Goal.** Storage interfaces that make history mutation structurally impossible, plus an
in-memory adapter for testing. No durable storage in this sprint.

**Files.** `src/greenmachine/persistence/ports.py` · `in_memory.py` · `errors.py` ·
`tests/unit/persistence/` · `tests/integration/test_repository_contract.py`

**Dependencies.** GM-006.

**Acceptance criteria**
- Three separate repositories: snapshots, evaluations, **outcomes**
- Ports expose `append`, `get`, `query` only — **no `update`, `delete`, or `upsert`**
- Appending an existing identity raises a typed conflict error rather than overwriting
- Corrections are new records with a `supersedes` reference; superseded records remain readable
  and the chain is traversable
- Query supports the access patterns replay, comparison, and research need: by date, by subject,
  by model configuration version, **by window profile**, and **by `source_capture_id`** so the two
  profile-specific results from one capture can be retrieved together for comparison
- Query results returned in deterministic, explicitly sorted order
- A reusable **contract test suite** that any future adapter (file, SQLite) must pass unchanged
- Outcome repository is separate; no API allows writing an outcome into an evaluation

**Tests**
- Contract suite against the in-memory adapter: append/get round-trip · duplicate append raises ·
  retrieval by each query dimension including `window_profile` · deterministic ordering ·
  supersession chain readable end to end
- Introspection test: ports expose no mutating method — fails if someone adds `update`
- Two profile-specific snapshots from one source capture both persist, are independently
  retrievable by `snapshot_id`, have distinct `input_hash` values, and are jointly retrievable by
  `source_capture_id`
- The two GradeResults derived from them persist and are independently retrievable
- Querying a missing record returns an explicit empty result, never a silent default
- No cross-repository write path allows outcome data into an evaluation

---

### GM-008 — Test harness: fixtures, golden runner, property setup · **COMPLETE (accepted r3)**

**Goal.** The testing infrastructure that carries the project for years — above all the
profile-aware golden runner that makes every future scoring change an explicit, reviewable diff.

**Files.** `tests/conftest.py` · `tests/golden/runner.py` · `tests/golden/cases/` ·
`tests/property/conftest.py` · `tests/fixtures/` · `scripts/update_goldens.py` ·
`docs/adr/0008-golden-testing-strategy.md` *(originally planned as
`0005-golden-testing-strategy.md`; ADR-0005 had already been assigned to the window-profile
architecture on delivery of GM-006, and ADR numbers are never reused, so the Product Owner
ruled the golden-testing ADR is **ADR-0008**)*

**Delivered (r1–r3 rulings recorded).** Beyond the criteria below, the accepted revision adds:
a documented lowercase stable `case_id` convention (`^[a-z][a-z0-9_-]*$`); per-case batch
outcomes in `run_cases` with deterministic execution-failure rendering (never exception repr);
the explicit fixed Hypothesis seed **20260724** via `--hypothesis-seed` in pyproject `addopts`
(with `derandomize=False` so the seed genuinely drives generation); complete parent-session
network blocking (TCP, UDP, and resolver paths) plus a portable guarded child bootstrap for
every test-spawned Python interpreter that survives competing `sitecustomize` modules; and
case-root confinement rejecting symlinked or escaping case directories at discovery and at the
update-script write boundary.

**Dependencies.** GM-003, GM-005, GM-006.

**Acceptance criteria**
- A golden case is a directory containing **one profile-specific** input snapshot, a config
  version reference, an explicit `window_profile`, and an expected `GradeResult`; adding a case
  requires no code change
- **Every case declares its profile**, and the runner refuses a case that omits it
- The runner reports field-level readable diffs, not opaque assertions
- Goldens regenerate only via deliberate script invocation; the suite never self-heals
- Hypothesis configured with a fixed seed and deterministic CI profile
- Whole suite runs with no network access and no dependence on the current date, enforced by a
  blocked-socket fixture
- At least one end-to-end case per profile, built from **two profile-specific snapshots sharing
  one synthetic `source_capture_id`**, using a stub scorer, proving the harness is ready for
  Sprint 2
- `tests/README.md` explains how to add a case
- Fixture values are obviously synthetic and cannot be mistaken for production thresholds

**Tests**
- Meta: the runner detects a deliberately corrupted expected value and fails
- Meta: the runner passes on an unmodified case
- Meta: the runner rejects a case with no declared `window_profile`
- Meta: two cases from one `source_capture_id`, each with its own profile-specific snapshot,
  produce different expected results and both pass — proving profiles are genuinely separate paths
- Meta: the runner rejects a snapshot fixture that declares two profiles
- Meta: the suite fails if a test attempts a network call
- `update_goldens.py` rewrites only the targeted case

---

### GM-009 — Error taxonomy and structured logging baseline · **COMPLETE (accepted r2)**

**Goal.** Failures that are specific, actionable, and traceable — with logging observational
only, never behavior-affecting.

**Files.** `src/greenmachine/common/errors.py` · `logging.py` ·
`docs/adr/0007-error-handling-and-logging.md` · `tests/unit/common/`

**Dependencies.** GM-001.

**Acceptance criteria**
- Hierarchy rooted at `GreenMachineError`, with distinct branches for configuration, data/input,
  domain-invariant, ingestion/source, and persistence failures
- Every error carries structured context — file, key path, metric, profile, subject — not just a
  string
- Ingestion branch includes a schema-change error type that adapters must raise loudly
- Structured logging (key–value/JSON); records include `model_version`, `config_hash`,
  `input_hash`, and `window_profile` where available
- Logging never mutates state or alters control flow; the core does not log in any way that could
  vary output
- No bare `except Exception` in `src/`, enforced by a CI lint rule
- Log level configurable, defaulting to quiet

**Tests**
- Each error type carries and exposes its structured context
- Error messages include identifying context (asserted on fields, not prose)
- Structured log output parses as JSON and contains required correlation fields
- CI lint rejects a deliberately introduced bare `except Exception`

---

### GM-010 — Documentation system, ADR process, and register maintenance · **COMPLETE (Sprint 1 closeout, 2026-07-24)**

**Goal.** Documentation as a maintained, verified part of the codebase rather than a snapshot
that rots.

**Delivered, with recorded adjustments.** GM-010 executed as the Sprint 1 closeout under
Product Owner change boundaries (documentation and status reconciliation only; no production
behavior):

- The ADR template, process, and ADR-0001 had already landed with GM-001; GM-010 verified
  them. The actual ADR/ticket mapping is: 0002 → GM-005, 0003/0004/0005 → GM-006,
  0006 → GM-007, 0007 → GM-009, **0008 → GM-008** (the plan's original "0002–0007" listing
  predated the golden-testing ADR renumbering ruling).
- `CHANGELOG.md` reconciled with every accepted Sprint 1 delivery. The code version remains
  **0.1.0** — the planned 0.2.0 target was not applied, because the approved GM-008-r3 archive
  freezes `src/` byte-identical and the closeout is documentation-only; any future version
  change requires an explicit ruling in that future ticket (recorded ruling).
- `docs/SPRINT_1_CLOSEOUT.md` created as the sprint acceptance record.
- Documentation-integrity tests delivered at `tests/unit/docs/test_documentation_integrity.py`:
  markdown-link resolution, ADR section/status/index consistency, ticket-referenced open
  questions existing in the register, stale-status guards, and placeholder-package purity.
  Enum/GLOSSARY drift has been enforced since GM-002 by
  `tests/unit/domain/test_glossary_drift.py`; the "no baseball threshold outside
  MODEL_SPEC/GLOSSARY" rule remains review-enforced (a mechanical scan cannot distinguish a
  threshold from an ordinary number without unacceptable false positives).
- `CONTRIBUTING.md` and `OPEN_QUESTIONS.md` edits were **excluded** from the closeout by the
  Product Owner's GM-010 change boundaries (neither file is in the permitted-changes list);
  authorizing a CONTRIBUTING.md remains an open Product Owner decision recorded in the
  closeout document.

**Files.** `docs/adr/README.md` · `TEMPLATE.md` · `0001-record-architecture-decisions.md` ·
`CONTRIBUTING.md` · `CHANGELOG.md` · `tests/unit/docs/test_documentation_integrity.py`

**Dependencies.** GM-001.

**Scope note.** `MODEL_SPEC.md`, `GLOSSARY.md`, and `OPEN_QUESTIONS.md` were authored during the
Phase 1 correction pass. This ticket **maintains and verifies** them rather than creating them,
and adds the ADR process plus automated documentation-integrity tests.

**Acceptance criteria**
- ADR template and process documented: Context / Decision / Consequences / Status; append-only;
  superseded ADRs marked, never deleted
- ADR-0001 records the decision to use ADRs; ADRs 0002–0007 land with GM-005, GM-006, GM-008,
  GM-009 as listed
- `OPEN_QUESTIONS.md` maintained with ID, status, owner, blocking status, tickets affected, and
  decision date on closure; closed questions retained
- `CONTRIBUTING.md` states the Definition of Done and review checklist from
  ENGINEERING_GUIDELINES §12–13
- `CHANGELOG.md` updated for 0.2.0 with product-specification, code, model-configuration, and
  schema changes listed separately
- Documented rule enforced in review: `MODEL_SPEC.md` owns product behavior, `ARCHITECTURE.md`
  owns engineering structure

**Tests**
- Every relative link in `docs/` and root markdown files resolves
- Every `MetricId` and enum member has a `GLOSSARY.md` entry, and vice versa
- Every ADR has the required sections and a valid `Status`
- Every open question referenced by a ticket exists in `OPEN_QUESTIONS.md`
- No document outside `MODEL_SPEC.md` and `GLOSSARY.md` defines a baseball threshold

---

## Deferred ticket (not Sprint 1)

**Post-closeout status (recorded 2026-07-24).** The ticket text below is the original Sprint 1
planning description, retained as history — including its "Sprint 3+" placement and its
Ideal-Attack-Angle-adapter framing, both of which are **superseded**. Under the approved
post-Sprint-1 sequence (see `docs/SPRINT_1_CLOSEOUT.md`), GM-020 is the next implementation
milestone and its current planning target is a **thin production ingestion vertical slice**:
one selected slate, one game, one hitter, the expected pitcher; prospectively archived
MLB/Savant raw responses; normalized provider-neutral records; separate `RECENT_7D` and
`LONG_TERM_2Y` snapshots; deterministic offline replay. The final GM-020 ticket will be frozen
only after the Gemini architecture review, the Grok baseball/provider-semantics review, and
Product Owner rulings.

### GM-020 — Savant ingestion adapter *(original planning text — superseded, see above)*

**Goal.** Acquire Savant Ideal Attack Angle percentages for both window profiles under the
approved source hierarchy, entirely behind the ingestion boundary.

**Files (anticipated).** `src/greenmachine/ingestion/savant/client.py` ·
`structured_extract.py` · `leaderboard_parser.py` · `event_derivation.py` · `mapping.py` ·
`tests/fixtures/savant/`

**Dependencies.** GM-002, GM-006, GM-007, plus provider decisions.

**Blocked by.** Q19 (structured endpoint availability), Q20 (historical coverage), Q21 (proxy
definition), Q23 (final providers).

**Notes.** Source hierarchy, extractor constraints, required provenance fields, and the
prohibition on labeling proxy values as Savant Ideal Attack Angle % are specified in
MODEL_SPEC §9 and ENGINEERING_GUIDELINES §6. **Explicitly deferred; not started in Sprint 1.**
Sprint 1 delivers only the empty documented package that marks the boundary.

---

## Definition of Done for the sprint

*Closed 2026-07-24: every item below holds for the accepted repository, with two recorded
adjustments — the CHANGELOG is reconciled but the code version remained 0.1.0 at closeout (see
the version note at the top of this plan), and the ENGINEERING_GUIDELINES §12 "CHANGELOG updated" item was
satisfied at closeout rather than per ticket, by the deferral ruling made at GM-008.*

- All ten tickets meet the Definition of Done in ENGINEERING_GUIDELINES §12
- CI green and enforcing lint, types, tests, determinism, import boundaries, and config validation
- Determinism test passes across separate processes
- Architecture import-boundary tests pass
- Profile-aware golden harness runs both profiles from one source capture, as two
  profile-specific snapshots, with a stub scorer
- No `Decimal` is constructed from a `float` anywhere in `src/`
- No baseball rule, threshold, allocation, or sample minimum exists anywhere in `src/`
- No production configuration version has been finalized
- `OPEN_QUESTIONS.md` reflects the current state of every unresolved requirement

---

## Sprint 2 preview (historical — ordering superseded 2026-07-24)

*This preview predates the closeout. The approved post-Sprint-1 sequence inserts the provider
architecture and baseball/data-semantics review, the GM-020 thin ingestion vertical slice, and
the first real profile snapshots **before** grading-core implementation, so scoring is built
against real point-in-time data; see `docs/SPRINT_1_CLOSEOUT.md`. The scoring scope itself
remains as previewed:*

Bucket resolution, component scoring, category aggregation, grade assignment, signal engine
execution with override reasons, and the Validation Layer — plus the first production model
configuration version. Requires Q11–Q16 to be answered before scoping. Q25 is closed.
