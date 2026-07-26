# Changelog

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

GreenMachine tracks **four independent versions**, listed separately in every entry:

- **Product specification** — the baseball/product lineage (e.g. v6.2)
- **Code version** — the software (this file's headings)
- **Model configuration version** — thresholds, allocations, buckets, cutoffs
- **Evaluation schema version** — persisted snapshot and evaluation record formats

---

## [Unreleased]

### Fixed — GM-041.5-HF2 deterministic Hypothesis health-check policy (2026-07-26)

**Product specification** v6.3 · **Code** 0.2.0 · **Model configuration** none approved ·
**Evaluation schema** 1. No frozen contract changed. Supersedes the health-check decision in
GM-041.5-HF1; the HF1 hub-wording work is untouched.

- **The accepted no-suppression policy is restored, without reintroducing the environment
  dependence.** HF1 correctly identified that leaving `suppress_health_check` unspecified lets
  Hypothesis inherit it from the active built-in profile — which on a hosted runner suppresses
  `HealthCheck.too_slow` — and correctly concluded the field must be pinned. It then pinned the
  wrong value. `tests/property/conftest.py`, `tests/README.md`, and ADR-0008 all state that
  GreenMachine suppresses **no** health check, so HF1 left the repository asserting two
  contradictory policies at once, and no test noticed. The registration now passes
  `suppress_health_check=()`: explicit, so nothing is inherited from the environment, and empty,
  so the value is the one the project actually chose. `test_ci_profile_is_registered_with_deterministic_settings`
  asserts exactly `()`. Every other profile field — `derandomize=False`, `database=None`,
  `deadline=None`, `max_examples=50`, `print_blob=False` — is unchanged, as is the fixed seed
  20260724 delivered through `pyproject` addopts.
- **`HealthCheck.too_slow` does not fire under the restored policy.** The property suite was run
  with the empty tuple under `CI` unset, `CI=true`, and `GITHUB_ACTIONS=true`; all three pass. No
  timing limit was raised, no check suppressed, and no test skipped or xfailed to reach that
  result.
- **A subprocess probe proves the profile is identical across environments.** Hypothesis decides
  CI-ness while it is being imported, so an in-process `os.environ` edit proves nothing; each
  case therefore registers the profile in a fresh interpreter under a fabricated environment and
  reads it back. The three dumps are compared to each other as well as to the declared values,
  and a meta-test confirms an *unspecified* profile still does vary with CI — so the guard is
  measuring something real.
- **A documentation-integrity regression prevents the drift from recurring.** Four sources
  describe this profile; HF1 changed one and left three contradicting it. The new guard compares
  each document's claimed values against the live registered profile and against each other,
  matching meaning rather than one fixed sentence, so the files can be reworded freely but cannot
  disagree.

### Fixed — GM-041.5-HF1 CI stability and landing-page wording (2026-07-26)

**Product specification** v6.3 · **Code** 0.2.0 · **Model configuration** none approved ·
**Evaluation schema** 1. No frozen contract changed. Post-merge hotfix on top of the merged
GM-041.5 (PR #4).

- **GitHub Actions is green again.** Merged `main` inherited a property test that could only
  pass off-CI: `tests/conftest.py` registered the `greenmachine-ci` Hypothesis profile without
  pinning `suppress_health_check`, and Hypothesis adds `HealthCheck.too_slow` by itself when it
  detects a hosted runner. The effective profile therefore differed between a developer machine
  and CI — the one thing a determinism profile must never do — so
  `test_ci_profile_is_registered_with_deterministic_settings` passed locally and failed on every
  hosted run. The registration now pins `suppress_health_check` explicitly, making the effective
  settings identical in both environments, and the test asserts that single value. Every other
  profile field is unchanged. The assertion was **not** widened to accept either shape; that
  would have re-admitted the environment dependence it exists to rule out.
  **Superseded by GM-041.5-HF2:** HF1 pinned the field to `(HealthCheck.too_slow,)`. Pinning was
  right and the value was wrong — it contradicted the no-suppression policy recorded in
  `tests/property/conftest.py`, `tests/README.md`, and ADR-0008. HF2 keeps the explicit pin and
  empties it.
- **The landing hub names the console, not one of its screens.** The subtitle read
  `MANUAL REVIEW CONSOLE · PROTOTYPE · v0.2.0`, which stopped being true once the Engine
  Evaluation screen began running the deterministic grading engine, and it is the largest text on
  the landing page. It now reads `GREENMACHINE RESEARCH CONSOLE · v0.2.0`. Wording only — the
  original artwork, layout, and CSS are untouched, and no recommendation or decision language is
  introduced. The module docstring and `docs/STREAMLIT_PROTOTYPE.md` title, which described the
  whole application as a manual-review prototype, are corrected the same way; the historical
  GM-030 ticket references elsewhere are accurate and left alone.
- A focused regression asserts the new subtitle renders, the old one does not, all six hub
  destinations remain present, and `ENGINE EVALUATION` is still available.

No production behaviour, evidence, golden, scoring rule, threshold, schema, or configuration
content changed.

### Added — GM-041.5 Stabilization & UX Review (2026-07-25)

**Product specification** v6.3 · **Code** 0.2.0 · **Model configuration** none approved ·
**Evaluation schema** 1. No frozen contract changed.

- **Engine Evaluation screen** — a sixth hub destination rendering the GM-041 engine's six
  outputs (Total Score, Tier, Component Breakdown, Audit Trail, Warnings, Fallbacks) for
  either window profile of an approved archived run. Evaluated and not-evaluable results
  render as structurally distinct states; a not-evaluable result never becomes a zero or a
  tier D.
- **Every displayed score is a synthetic demonstration.** No production model configuration
  is approved while Q11–Q16 remain open, so the screen runs under the disclaimed
  non-production configuration and says so above the result, beside the total and tier, and
  again below it. It produces no automated recommendation and no decision output.
- **`reporting.load_verified_run`** — a new additive accessor returning a frozen
  `VerifiedRun` (view models plus both frozen `InputSnapshot`s) from exactly one
  replay-verification pass, with each snapshot deserialized once. `load_dashboard` is
  unchanged for every existing caller and now delegates to it. This is what lets the
  composition root score a run while `reporting` still imports neither `scoring` nor
  `config`.

### Changed — GM-041.5

- The disclaimed synthetic configuration moved **byte-for-byte** from
  `tests/fixtures/config/valid/` to `config/nonproduction/gm041_engine_synthetic.yaml`, so the
  deployed application never reads an executable configuration out of the test tree. No second
  copy remains. Source digest, semantic `config_hash`, and version identifier are unchanged,
  and the committed GM-041 sample JSON and Markdown remain byte-identical.
- The GM-003 configuration-location guards now permit `config/nonproduction/` alongside
  `tests/fixtures/`, and additionally require every configuration in that directory to
  announce itself as synthetic and non-production.

---


### Added — GM-040 prospective real-data vertical slice (2026-07-25)

Pure composition over the frozen GM-020 pipeline — zero capture, archive, replay, metric,
mapping, snapshot, or dashboard behavior changed; manifest v1, schema version 1, and
`InputSnapshot` are untouched. One new module (`ingestion/operator.py`) and one operator
script (`scripts/run_gm040_real_slice.py`) add the missing operator-facing extension points:

- **explicit operator selection** (slate date, gamePk, hitter MLBAM id, projected/confirmed
  lineup status, capture mode, optional note) — nothing guessed, invalid values fail closed;
  lineup status is recorded in the generated operator report only
  (`reports/operator_report.json` + `OPERATOR_REPORT.md`, appended before atomic
  publication), never in an identity;
- **honest timing classification** from recorded manifest instants: `prospective` restates
  the frozen timing proof; explicitly permitted `retrospective-development` captures publish
  but are clearly distinguished and never represented as locked pregame predictions — even
  when their timestamps precede the scheduled start;
- **expected-pitcher cross-check** (verification only — manifest v1 binds the pitcher capture
  to the feed resolution, so a mismatch fails closed before publication; no override exists);
- **idempotent publication**: identical re-runs verify (`verified-existing`) without writing,
  true content conflicts fail explicitly, nothing is ever overwritten;
- multi-player operation is independent one-hitter v1 bundles, demonstrated by live evidence:
  a second real prospective bundle for the same game and a different hitter, discovered by the
  existing Streamlit run selector with no code change;
- the unguarded `validation` placeholder from the readiness memo is now enforced.

Deliberately absent: slate aggregation, rankings, Pitchers/Bullpens to Target, bullpen
capture, Record Book, outcomes, databases, weather, park changes, UI redesign, scheduled
jobs, and all scoring. Reference: [`docs/GM_040_REAL_SLICE.md`](docs/GM_040_REAL_SLICE.md) and
[`docs/GM_040_RUNBOOK.md`](docs/GM_040_RUNBOOK.md).

### Added — GM-030 Streamlit manual-review prototype (2026-07-24)

A **usability prototype** dashboard over approved archived GM-020 runs — not the final
interface and not production-ready. Code version stays **0.2.0** during this prototype ticket;
a later explicit ruling will determine the next version.

- **Archived runs only, verified read-only.** The app discovers approved run bundles beneath
  `evidence/gm020_vertical_slice/` (deterministic, path-confined discovery), re-verifies each
  through the existing GM-020 read-only replay path on load, performs no provider network
  request, and never writes to a run bundle. Integrity failure renders a focused user-facing
  error, never a traceback.
- **Provider-neutral reporting layer** (`greenmachine.reporting`): immutable view models,
  exact-Decimal display formatting, data-status badges, and the read-only loader. Streamlit is
  confined to the repository-root `streamlit_app.py` composition root (architecture-enforced);
  ingestion never imports reporting.
- **Data-status colors only** — green/yellow/gray/blue/red communicate presence, sample
  sufficiency under the archived validation-only policy, missingness, audit-only context, and
  errors. No performance threshold exists anywhere (Q11–Q14 remain open), and a persistent
  legend says so.
- **Manual review worksheet**: user-entered category scores (Power Profile 0–3, Pitcher
  Matchup 0–3, Form 0–2, Pull Power 0–2, Environment 0–2), arithmetic total, and the frozen
  manual tier (S 10–12 · A 8–9 · B 6–7 · C 4–5 · D 0–3) once complete. Explicitly **not** the
  GreenMachine scoring engine: no signal, no recommendation, no betting output. Deterministic
  JSON/CSV exports carry the run identities and the disclaimer "manual user review — not
  automated GreenMachine scoring"; no implicit timestamp is ever read.
- **Whiff Rate is excluded** by frozen Product Owner ruling — no card, table, tooltip, export,
  or filter surface; archived audit fields matching the exclusion are dropped in the view-model
  layer and tests enforce the absence end-to-end. Overall Pull% appears as clearly labeled
  audit-only context beside Pull Air%.
- **Deliberately absent**: automated scoring, full-slate ingestion or aggregation, live
  dashboard capture, weather/park/bullpen/Pitchers-to-Target, betting recommendations, and
  database storage. UI refinement waits for Product Owner usage notes.
- Dependency: optional `ui` extra pinning `streamlit>=1.32,<2`; committed
  `.streamlit/config.toml` (telemetry off, headless, focused errors); reference documentation
  in [`docs/STREAMLIT_PROTOTYPE.md`](docs/STREAMLIT_PROTOTYPE.md).

*GM-030-r1 correction pass (same day):*

- **Original GreenMachine console-style landing hub** as the default screen — dark
  emerald/black geometric grid, glowing baseball-seamed energy sphere, neon-green menu bars,
  circular accents, console typography from local/system fonts, subtle pulse on the hub only.
  The styling is original and uses no Xbox-owned asset; there is no remote font, image,
  stylesheet, script, or CDN request. Five destinations (Overview, Hitter Metrics — which now
  also hosts the profile comparison — Matchup Context, Data Audit, Manual Review), each with a
  return-to-hub control; content screens keep a calmer readable layout.
- **Whiff Rate simply omitted**: the visible sidebar notice was removed, and an AppTest sweep
  proves the complete rendered element tree contains no whiff-related text on any screen.
- **Pitcher-specific metrics deferred** to the later Pitchers to Target work: the visible
  ingredient table was removed, Matchup Context shows expected-pitcher identity and role only,
  and the archived ingredient report is no longer parsed for UI purposes (the GM-020 evidence
  itself is unchanged). The manual Pitcher Matchup worksheet category remains.
- **Manual-review state made canonical**: duplicate, unknown, or missing category keys are
  rejected; scores/rationales/notes/timestamp are type-checked; construction normalizes to one
  canonical mapping so displayed totals, the tier, and both exports can never disagree, and
  input tuple order cannot change an export byte.
- **Strict dashboard report adapters**: the audit/context reports (which are display-only and
  not part of `SourceCaptureId`) are now parsed with duplicate-key rejection, type/structure
  validation, canonical-Decimal checks, and non-negative counts; every malformation surfaces
  as a focused `DashboardLoadError` naming the run and report — never a raw traceback. The
  integrity banner now states the verification scope precisely.

---

## [0.2.0] — 2026-07-24 — First production ingestion vertical slice (GM-020)

**Code version 0.2.0.** The sprint plan's original 0.2.0 target was **not applied** during
the documentation-only GM-010 closeout, and any version change requires an explicit ruling in
the ticket that makes it; GM-020 carries exactly such a ruling, so the version moves 0.1.0 →
0.2.0 with this entry. Product specification stays v6.3; no model configuration version has
been published; the evaluation record schema version in force is **1** (introduced by GM-006's
canonical record wrapper). The capture manifest introduces its own **manifest schema version 1**,
independent of the evaluation record schema.

### Added — provider ingestion (GM-020), the first real data path

A thin production **vertical slice**: one slate date, one game, one hitter, one expected
starting pitcher, from live provider responses to two frozen `InputSnapshot`s. Full engineering
reference in [`docs/GM_020_VERTICAL_SLICE.md`](docs/GM_020_VERTICAL_SLICE.md).

**Prospective raw capture.** MLB Stats API schedule and live feed plus Baseball Savant batter
and pitcher event exports are archived as raw bytes before any interpretation. Retrieval uses
an injected transport under an explicit retry policy — **at most 3 attempts**, fixed backoff
with no jitter, `Retry-After` honoured when integral and capped — with every attempt recorded.
A run assembles entirely in memory and publishes atomically; a published run directory is
immutable. **A failed capture never publishes**: it writes only under `failed_run/`, preserving
the raw bytes that did arrive alongside the eligibility and attempt records, with no manifest
and no snapshots.

**Content-derived identity.** Capture-entry, manifest, and `SourceCaptureId` identifiers derive
from provider, endpoint, sorted parameters, and body digests — never UUIDs, randomness, or
filesystem paths. The `SourceCaptureId` covers only the **participating** captures, so the
audit-only pitcher capture cannot perturb snapshot identity. One flipped byte in any raw
artifact is detected on replay.

**Two profile-specific snapshots from one capture.** `RECENT_7D` and `LONG_TERM_2Y` snapshots
share a `source_capture_id` and differ in `snapshot_id`, `input_hash`, window bounds, and
observations — the v6.3 rule realised against real data. Both share one coordinated `as_of`:
the latest **participating** retrieval completion, so the audit-only pitcher capture's timing
and bytes are provably inert for both hitter snapshots. All present observations are
`EVENT_DERIVED`; **only Ideal Attack Angle %** carries a `FallbackRecord` (it alone bypasses an
approved higher-priority acquisition hierarchy, and its record names exactly those methods with
IAA-specific ineligibility reasons) — every other metric's `fallback_used` is `None`, because
recording a bypassed hierarchy that does not exist would be false provenance.

**Genuine prospective timing, from recorded instants.** A prospective run publishes (and
replays) only when both sources report pregame state with agreeing scheduled starts and every
participating capture — and the run itself — completed strictly before the scheduled first
pitch, all proven from the manifest's recorded instants; the current date never participates,
and completion exactly at first pitch fails.

**Self-contained, strictly replayable bundles.** The exact supplied sample-policy bytes are
archived verbatim at `inputs/sample_minimum_policy.json` and digest-pinned by
`inputs/replay_inputs.json`; replay accepts no caller-supplied policy, so a run can never be
silently replayed under different minimums. `manifest.json` is parsed under a strict
fail-closed contract — exact field sets, no unknown fields, no coercion, per-entry recorded
`capture_id` verified against its recomputed identity before any raw parsing.

*(The three paragraphs above reflect the GM-020-r1 correction pass: fallback provenance
narrowed to IAA only, `as_of` anchored to participating captures, prospective timing enforced
from recorded instants, strict manifest replay, and the archived digest-pinned replay inputs.
The raw live evidence bytes and its `SourceCaptureId` were unchanged; both snapshots were
regenerated offline from the original archived bytes and retrieval instants.)*

*(The GM-020-r2 integrity-hardening pass added: path-safe atomic publication — one
centralized bundle-relative path validator rejects traversal, absolute paths, and duplicate or
colliding destinations before any byte is written, with resolved destinations re-verified at
write time, and the release-archive builder runs its file plan through the same validator;
`manifest_id` widened to the complete canonical manifest content with recomputed capture
identities, so no published manifest field can change silently; the v1 semantic contract —
exactly the five GM-020 captures with exact participation, coherent attempt histories,
successful responses, and provider requests byte-equal to what GM-020 constructs for the
recorded selection; duplicate-JSON-key rejection for every GreenMachine-owned document;
exact-value validation of all replay-input metadata; and an idempotent replay report, making
the documented replay command repeatable. Raw bytes, digests, `SourceCaptureId`, and both
snapshots were again unchanged; only `manifest.json` and the replay report were regenerated
offline for the widened identity.)*

**Frozen date and game-type policy.** Regular season only (`game_type == "R"`), with every
exclusion counted by type and a missing type never treated as regular season; half-open windows
`[slate − 7, slate)` and `[slate − 730, slate)` that always exclude the slate date; the selected
game excluded unconditionally; `slate_date` taken from the provider and never derived from UTC.

**Frozen metric definitions.** Barrel uses the official `launch_speed_angle == "6"` bucket;
hard-hit is `>= 95`; sweet spot is `[8, 32]` inclusive; Ideal Attack Angle % is `[5, 20]`
inclusive over **all** rows with a tracked attack angle — swing-level, not batted-ball-level,
and event-derived rather than the published leaderboard aggregate. Pull % (air balls) uses a
frozen initial `fly_ball` + `line_drive` denominator with row-level stand handling (correct for
switch hitters) and exact Decimal geometry inclusive at the 15° boundary; fly-ball-only,
fly+line+popup, and overall-pull variants are reported for evidence but are **audit-only** and
never enter a snapshot.

**Fail-closed schema contracts.** A missing required field, a changed required type, or
malformed JSON/CSV fails the run with `SchemaDriftError`. Additive provider change is accepted
and audited through a schema fingerprint. Identical duplicate event rows collapse and are
counted; a genuine conflict under one event key fails closed.

**Deterministic offline replay.** `scripts/run_gm020_vertical_slice.py` reconstructs a
published run, recomputes identities, verifies digests, and regenerates both snapshots
byte-identically — with no network access, independent of the working directory, and stable
across `PYTHONHASHSEED` values and host timezones.

### Added — dependency

- `tzdata` as a runtime dependency: `zoneinfo` has no bundled database on Windows, and venue
  timezone resolution must not depend on the host. It is a versioned data input, not a
  behavioral one.

### Interim mappings and open decisions (nothing invented)

- Pitch-matchup composites remain missing with `SOURCE_UNAVAILABLE` pending **Q15/Q16**; the
  underlying pitcher ingredients are captured and reported transparently, but no composite is
  invented.
- Park remains missing with `SOURCE_UNAVAILABLE`; weather remains missing with
  `WEATHER_UNAVAILABLE`.
- **Sample minimums are injected, never defaulted.** Production minimums are **Q14**, still
  open. A clearly labelled non-production fixture policy exists for validation only, carrying
  its own disclaimer; there is no default anywhere in `src/`.

### Not implemented (deliberately) — the exact boundary

No runtime scoring engine exists; there is no production feature calculation, daily
orchestration across a full slate, reporting/CLI/dashboard behavior, weather or park-factor
sourcing, bullpen modelling, or durable storage adapter. **No production model-configuration
version has been published, and no baseball threshold, allocation, or scoring behavior is
implemented in `src/`.** `MODEL_SPEC.md` *does* contain approved specification rules and
defaults — the 15% qualifying pitch-usage default, the grade boundaries, the signal conditions,
the 5°–20° Ideal Attack Angle definition, the 75% strong-category rule — which engineering
implements but never invents; the synthetic test configuration under `tests/fixtures/` is not a
production model configuration. `scoring`, `features`, `reporting`, and `cli` remain
docstring-only placeholder packages; `ingestion` is now implemented for the vertical slice only.

---

## Sprint 1 foundations — under code version 0.1.0 (closed out 2026-07-24)

**Sprint 1 is complete** (GM-001 through GM-009 implemented and accepted; GM-010 closeout
applied 2026-07-24). Code version remained 0.1.0 through the closeout: the approved cumulative
archive `greenmachine-gm-008-r3.zip` freezes `src/` — including the package version constant —
byte-identical, and the GM-010 closeout is documentation-only by Product Owner ruling. Product
specification stays v6.3; no model configuration version has been published; the evaluation
record schema version in force is **1**.

### Code — Sprint 1 foundations (GM-001 … GM-009, closed out by GM-010, 2026-07-22 → 2026-07-24)

All Sprint 1 implementation tickets are complete, independently reviewed, and frozen. Accepted
revisions: GM-001 · GM-002-r2 · GM-003-r3 · GM-004-r1 · GM-005-r2 · GM-006-r2 · GM-007-r1 ·
GM-008-r3 · GM-009-r2.

**Deterministic domain contracts (GM-002).** The complete immutable typed vocabulary: eleven
scored components with the `attack_angle_quality` component/measurement split, `WindowProfile`,
`SampleStatus` separate from `MissingReason`, generic `provider_id` + `acquisition_method`
provenance, canonical game identity, full observation provenance — frozen, hashable, validated
at construction, with `domain` importing nothing internal (one recorded errors-only exception)
under AST-enforced boundaries.

**Determinism primitives (GM-005, ADR-0002 implemented).** Project-local Decimal context
(precision 28, `ROUND_HALF_EVEN`) with string/int-only construction; distinct half-open bucket
and inclusive event-range helpers; injected `Clock` protocol; canonical byte-identical
serialization with Decimals as base-10 strings; content-derived identifiers; CI static checks
against `Decimal(float)`, wall-clock reads, and randomness.

**Error taxonomy and structured logging (GM-009, ADR-0007).** Typed hierarchy rooted at
`GreenMachineError` with structured context; JSON logging carrying correlation fields;
architecture-enforced prohibition on broad exception handling.

**Configuration as data (GM-003).** Strict YAML loader into frozen typed objects — unknown and
missing keys are errors, all numerics parsed to Decimal from strings — with every MODEL_SPEC
§19 semantic invariant enforced as a load failure. Synthetic fixtures only: no production
model-configuration version has been published, and the synthetic test configuration is not a
production model configuration.

**Semantic configuration identity (GM-004).** Canonicalized semantic `config_hash` (stable
under comments, formatting, and key order; changed by any semantic edit), multi-version
loading, and a modified-after-use detection seal.

**Snapshot, result, and record contracts (GM-006, ADRs 0003/0004/0005 implemented).** Frozen
one-profile `InputSnapshot` with content-derived `snapshot_id`/`input_hash` behind a
module-private construction authority; pure `EvaluatedGradeResult` / `NotEvaluableGradeResult`
variants (type-level status impossibility) separated from the orchestration
`EvaluationEnvelope`; minimal `OutcomeRecord`; lossless canonical record serialization under
**evaluation schema version 1** with strict typed decoding and identity verification.

**Append-only persistence ports (GM-007, ADR-0006).** Separate snapshot, evaluation, and
outcome repositories exposing exactly `append`/`get`/`query`; typed duplicate and conflict
failures; linear supersession chains; chain-hashed `OutcomeRevision` correction history in the
persistence layer; deterministic query ordering; a reusable adapter contract suite.

**Golden-master and property-test infrastructure (GM-008, ADR-0008).** Directory-based
profile-specific golden cases as canonical GM-006 records with a strict manifest and lowercase
stable case ids; automatic confined discovery (symlink and root-escape rejection); an injected
`GoldenScorer` boundary with a clearly labeled test-only stub (no scoring logic); readable
field-level canonical diffs; per-case batch outcomes with deterministic execution-failure
rendering; the explicit targeted `scripts/update_goldens.py` as the only golden write path (no
pytest self-healing); deterministic Hypothesis configuration under **fixed seed 20260724**
(`database=None`, `deadline=None`, `max_examples=50`); and suite-wide network blocking —
TCP/UDP/resolver paths in the parent session, with every test-spawned Python child routed
through an explicit guarded bootstrap that survives competing `sitecustomize` modules.

**Sprint 1 closeout (GM-010, this entry).** Documentation and status reconciliation only:
CHANGELOG, README, sprint plan, architecture status, ADR index verification,
`docs/SPRINT_1_CLOSEOUT.md`, and documentation-integrity contract tests. No production
behavior changed.

### Accepted ADRs

0001 record architecture decisions · 0002 numeric and bucket-boundary policy · 0003 snapshot
and point-in-time policy · 0004 GradeResult vs. EvaluationEnvelope · 0005 window-profile
architecture · 0006 outcomes separate from evaluations · 0007 error handling and structured
logging · 0008 golden testing strategy. (The sprint plan's original
`0005-golden-testing-strategy` filename was superseded by Product Owner ruling — ADR numbers
are never reused, so the golden-testing decision is ADR-0008.)

### Real-data evidence (not production code)

The Savant feasibility spike (accepted r2, archive
`greenmachine-savant-feasibility-spike-r2.zip`) proved provider feasibility and mapped real
data into the frozen `InputSnapshot` contract without modifying it. It remains an isolated
experimental artifact outside production source.

### Not implemented at the close of Sprint 1 — the exact boundary as of this entry

At the Sprint 1 boundary no runtime scoring engine existed, and there was no production feature
calculation, provider ingestion, daily orchestration, reporting/CLI/dashboard behavior, weather
or park-factor ingestion, or durable storage adapter. No production model-configuration version
had been published, and no baseball threshold, allocation, or scoring behavior was implemented
in `src/`. `MODEL_SPEC.md` *does* contain approved specification rules and defaults — the 15%
qualifying pitch-usage default, the grade boundaries, the signal conditions, the 5°–20° Ideal
Attack Angle definition, the 75% strong-category rule — which engineering implements but never
invents; the synthetic test configuration under `tests/fixtures/` is not a production model
configuration. `scoring`, `features`, `ingestion`, `reporting`, and `cli` were all
docstring-only placeholder packages at this point. **GM-020 — a thin production ingestion
vertical slice — was the next implementation milestone**, entered only after the provider
architecture and baseball/data-semantics reviews and the Product Owner rulings recorded in
`docs/SPRINT_1_CLOSEOUT.md`; it is delivered in 0.2.0 above, which implements `ingestion`.

### Product specification — v6.3 "Foundation Clarifications" (2026-07-22)

**Snapshots**
- **One `InputSnapshot` represents exactly one `WindowProfile`** and may never contain or produce
  both. `RECENT_7D` snapshot → `RECENT_7D` GradeResult; `LONG_TERM_2Y` snapshot →
  `LONG_TERM_2Y` GradeResult.
- **One source capture may produce two independently frozen profile-specific snapshots**, sharing
  a `source_capture_id` but with distinct `snapshot_id`, `input_hash`, `window_profile`,
  `window_start`, `window_end`, and observations. Replaces the v6.2 wording "one snapshot may be
  graded under both profiles".
- Profile comparison occurs over the two independently stored `GradeResult`s.

**Scoring and numerics**
- **Point allocations are profile-invariant** (Q25). Profiles may differ in bucket thresholds,
  minimum samples, sample counts, and coverage — never in `max_points`, category maximums, total
  maximum, or grade cutoffs. Configuration validates one shared allocation structure.
- **Fractional points are allowed and expected** (Q26). Strong category remains
  `category_score >= category_max_points × 0.75`; a 3-point category is strong at 2.25, a 2-point
  category at 1.50.
- **No rounding before** bucket qualification, category aggregation, total aggregation, grade
  assignment, strong-category comparison, or signal assignment. Presentation rounding is separate.
- **Complete Decimal policy adopted**: Decimal for thresholds, values entering scoring, points,
  and totals; never constructed from a binary float; built from provider strings, configuration
  strings, or integers; project-local context at precision 28 with `ROUND_HALF_EVEN`; derived
  values unquantized; canonical serialization as deterministic base-10 strings. **ADR-0002 moved
  from Proposed to Accepted.**

**Attack Angle**
- Scored **component** `attack_angle_quality` separated from the **measurement** used to satisfy
  it: `ideal_attack_angle_pct` or `attack_angle_threshold_proxy`, mutually exclusive, one per
  evaluation. Form still has exactly three scored components; none was added.
- Buckets are **measurement-specific and profile-specific**. Ideal-percentage buckets may not be
  applied to the proxy unless explicitly configured for it.
- Display: "Ideal Attack Angle %" or "Attack Angle Proxy" according to the measurement used.

**Provenance**
- Savant-specific composite source labels replaced by generic **`provider_id`** +
  **`acquisition_method`** (`direct_aggregate`, `structured_extract`, `rendered_scrape`,
  `event_derived`, `configured_proxy`). User-facing labels are derived from the pair.
- Provider HTML column names, page-layout details, parser selectors, and endpoint-specific
  structures remain prohibited in domain and scoring models.
- The former `unavailable` source label is retired: unavailability is a `MissingReason`, not an
  acquisition method.

**Sample status**
- **`SampleStatus` (`SUFFICIENT` | `INSUFFICIENT`) and `MissingReason` are separate types.**
  `INSUFFICIENT` is no longer a missing reason.
- A valid value with an insufficient sample **is still scored**, carries
  `SampleStatus.INSUFFICIENT`, raises an advisory Validation Layer warning, and stays visible in
  the audit trail. Zero eligible events or an unavailable value is *missing*, which is different.
- Minimum-sample configuration governs the label and the warning; it does **not** gate scoring.

**Point-in-time**
- **Source eligibility outranks source priority.** A method is eligible only if it can produce the
  exact selected profile, the correct window bounds, using no observation after `as_of`. Choose
  the highest-priority *eligible* method, and record why each higher-priority method was
  ineligible. Event-level derivation may therefore be the highest eligible method for historical
  backtests.

**Configuration invariants** (MODEL_SPEC §19)
- Bucket points `>= 0` and `<= max_points`; the strongest qualifying bucket awards `max_points`.
- Monotonicity enforced at load: `higher_is_better` points never decrease, `lower_is_better`
  points never increase.
- Every in-domain value resolves to exactly one bucket; no gaps, no overlaps.
- `bucketed` and `binary` use **separate validated schema shapes**; binary components are not
  forced to declare continuous bucket ranges.
- Component maximums sum exactly to category maximums; category maximums sum exactly to 12;
  allocations identical across profiles.

**Signals, matchup, and identity**
- **Signal priority confirmed intentional** (Q27): `AVOID` → `STRONG_BET` → `LEAN` → `PASS`. A
  high grade may still receive `AVOID` under the Power Profile veto; the **override reason**
  (e.g. `power_profile_veto`) is required in the interface and the audit trail.
- **Pitch-usage denominator fixed** (Q28): 15% default, over all pitches thrown by the expected
  starting pitcher to batters using the evaluated hitter's relevant batting side, current season
  through `as_of`. Configuration-owned.
- **Canonical game identity fixed** (Q30): the official provider's game identifier is the
  canonical `game_id`, with no internal replacement; doubleheaders have separate official IDs;
  `slate_date` is the official scheduled MLB date, never derived from UTC; start times stored in
  UTC alongside venue-local time and venue timezone; suspended and resumed games retain their ID.
- **`OutcomeRecord` reconfirmed** as a minimal Sprint 1 schema boundary, structurally separate
  from `InputSnapshot`, `GradeResult`, and `EvaluationEnvelope`. No outcome ingestion in Sprint 1.

### Resolved

- **Q25** — allocations are profile-invariant
- **Q26** — fractional points allowed; strong category unchanged at 75%, compared without rounding
- **Q27** — `AVOID` priority is intentional and carries an override reason
- **Q28** — 15% pitch-usage default and its denominator
- **Q30** — canonical provider `game_id` and official `slate_date`

Closed questions are retained in `docs/OPEN_QUESTIONS.md`.

### Changed — documents

- `docs/MODEL_SPEC.md` — rewritten for v6.3; adds §2.1 profile-invariant allocations, §3.1
  fractional points, §4 numeric policy, §6.2 one-snapshot-one-profile, §7.2 game identity, §8.2
  sample status vs. missing, §9 component/measurement split, §10 provider provenance, §11.2
  source eligibility, §12.1 pitch-usage denominator, §16.1 signal override, §19 configuration
  invariants.
- `docs/ARCHITECTURE.md` — profile-specific snapshots and `source_capture_id`; Decimal-from-string
  constraint at the feature boundary; source eligibility (§7.1); generic provider boundary;
  measurement-specific buckets; config folder layout; risks R3, R4, R5, R10 revised; GM-005
  precondition marked fully satisfied.
- `docs/ENGINEERING_GUIDELINES.md` — D4 rewritten as the full Decimal policy; new W3a
  (one snapshot, one profile), W5 (profile-invariant allocations), S3/S3a (insufficient is scored),
  S4 (provenance fields), P6 (eligibility outranks priority), I1/I1a (generic provenance, values
  as strings), I8 (measurement exclusivity); new §9.2 numeric policy tests; golden-test coverage
  extended; review checklist and anti-patterns updated.
- `docs/GLOSSARY.md` — component/measurement terminology; `attack_angle_quality` with both
  measurements; `SampleStatus` vs. `MissingReason`; provenance section; numeric terms section;
  source capture and snapshot identity; canonical game identity.
- `docs/OPEN_QUESTIONS.md` — Q25–Q28 and Q30 closed and retained; Q11–Q14, Q21, Q23, Q29 amended
  for v6.3 scope.
- `docs/SPRINT_1_PLAN.md` — GM-001 marked complete; GM-002 rewritten for the component/measurement
  and provenance vocabulary; GM-003 for separate schema shapes and the §19 invariants; GM-005 for
  Decimal primitives; GM-006 for one-profile snapshots and `source_capture_id`; GM-007 for
  capture-level queries; GM-008 for two-snapshot golden cases.
- `docs/adr/0002-numeric-and-bucket-boundary-policy.md` — completed and **Accepted**.
- `docs/adr/0003-snapshot-and-point-in-time-policy.md` — profile-specific snapshots; source
  eligibility.
- `docs/adr/0005-window-profile-architecture.md` — one snapshot per profile; Q25 closed;
  alternatives extended.
- `docs/adr/README.md` — ADR-0002 status updated to Accepted.
- `README.md` — snapshot wording, Attack Angle Quality section, v6.3 lineage.

### Not included in the v6.3 amendment itself

The v6.3 amendment was documentation and specification only; at its date (2026-07-22) no
production code beyond GM-001 existed. The Sprint 1 implementation that followed it is
recorded in the "Code — Sprint 1 foundations" section above.

---

## [0.1.1] — 2026-07-22 — v6.2 correction and specification pass

Documentation and specification only. **No production code added.**

### Product specification

- **Adopted GreenMachine Model Specification v6.2** as the product-specification lineage,
  formally separated from code SemVer, model configuration SemVer, and evaluation schema version.

### Added

- **`docs/MODEL_SPEC.md`** — new authoritative baseball and grading specification: category
  maximums summing to 12, score aggregation rules, scoring methods, window profiles, sample
  types, missing-data policy, Ideal Attack Angle definition and source hierarchy, Validation
  Layer semantics, pitcher selection rules, environment logic, grades, evaluation status, signal
  engine, point-in-time correctness, immutability and outcomes, configuration governance, and
  audit requirements.
- **`docs/GLOSSARY.md`** — exact definitions for every scored metric, validation input, window
  profile, sample type, missing reason, grading term, and architecture term. Unresolved formulas
  are explicitly marked as Product Owner decisions.
- **`docs/OPEN_QUESTIONS.md`** — live register with ID, status, owner, blocking status, tickets
  affected, and decision date on closure.
- **ADR set proposed** — 0001 record architecture decisions · 0002 numeric and bucket-boundary
  policy · 0003 snapshot and point-in-time policy · 0004 GradeResult vs. EvaluationEnvelope ·
  0005 window-profile architecture · 0006 outcomes separate from evaluations · 0007 error
  handling and logging.

### Changed — grading model

- **Last-14-Days retired.** Replaced by two separate, selectable evaluation profiles.
- **Added `RECENT_7D`** — "Recent — Last 7 Days", the primary short-term view.
- **Added `LONG_TERM_2Y`** — "Long-Term — Rolling 2 Years", the stable underlying-skill view.
- **Automatic season fallback retired** in favor of explicit profiles. Cross-window substitution
  is now prohibited; there is no silent fallback of any kind between profiles.
- **Generic Attack Angle replaced by `ideal_attack_angle_pct`** (Ideal Attack Angle %).
- **Adopted Baseball Savant's official 5°–20° inclusive definition**, replacing the previously
  discussed custom 14°–24° range. Raw average attack angle must no longer be scored as a
  monotonic higher-is-better metric.
- **Added the Savant source hierarchy** — `savant_direct`, `savant_structured_extract`,
  `savant_leaderboard_scrape`, `savant_event_derived`, `configured_threshold_proxy`,
  `unavailable` — with full provenance requirements and a prohibition on labeling proxy values as
  Savant's metric.
- **Confirmed category maximums** (Power Profile 3, Pitcher Matchup 3, Form 2, Pull Power 2,
  Environment 2; total 12) and sum-based aggregation with no averaging, rescaling, or dynamic
  normalization.
- **Documented the grade contract** — S `[10,12]`, A `[8,10)`, B `[6,8)`, C `[4,6)`, D `[0,4)`,
  assigned from the internal deterministic score before presentation rounding.
- **Documented the signal engine** — `AVOID` → `STRONG_BET` → `LEAN` → `PASS` in strict priority
  order, with "strong category" defined as ≥ 75% of a category's configured maximum.
- **Documented `EVALUATED` vs. `NOT_EVALUABLE`**, with `NOT_EVALUABLE` explicitly distinct from
  Grade D and receiving no score and no signal.
- Confirmed removal of Chase Rate, Zone Contact %, and Whiff Rate from Form; these are not to be
  reintroduced.
- Confirmed profile-invariant components: Pitcher Matchup (season), Park (rolling 3 years),
  Weather (grading-time forecast).

### Resolved

- **Q1 — Category numbers are category maximum points**, total 12, with sum-based aggregation.
- **Q2 — Evaluation unit** is one batter, one game, versus the expected starting pitcher, one
  frozen snapshot, one window profile.
- **Q3 — Output contract**: score 0–12, grades S/A/B/C/D, status and signal contracts as above.
- **Q4 — Validation Layer is advisory only** — no points, no cap, no veto, no reweighting.
- Also closed: Q5 (missing-data policy), Q6 (weather is the grading-time forecast), Q8 (backtest
  ground truth is ≥1 home run in the evaluated game), Q10 (local single-user Streamlit target).

### Changed — engineering documentation

- **`README.md`** — dual profiles, toggle and comparison purpose, Ideal Attack Angle %, grade and
  signal contracts, four version streams, updated phase roadmap.
- **`docs/PHILOSOPHY.md`** — product identity and predictive-edge wording, configuration
  governance, v6.2 lineage, separate recent and long-term research views, point-in-time
  correctness as a first-class principle.
- **`docs/ARCHITECTURE.md`** — resolved Q1–Q4 recorded with architectural impact; window-profile
  architecture; profile-specific configuration; `GradeResult` vs. `EvaluationEnvelope`; Savant
  adapter boundary; point-in-time event filtering; outcome separation; technology dependency
  rules; corrected sprint dependencies; risk register updated (profile leakage, dual boundary
  conventions, Savant source fragility, signal-rule interactions added).
- **`docs/ENGINEERING_GUIDELINES.md`** — no silent cross-window fallback; sample-type rules;
  point-in-time correctness rules; ingestion, scraper, and parser expectations; profile-specific
  golden tests; configuration governance; mandatory explicit Ideal Attack Angle boundary tests at
  5° and 20°; architecture import-boundary tests.
- **`docs/SPRINT_1_PLAN.md`** — corrected dependency graph and blocked-by table; window-profile
  fields throughout; `GradeResult`/`EvaluationEnvelope`/`InputSnapshot`/`OutcomeRecord` contracts;
  new schema requirements; Savant adapter explicitly deferred to GM-020; explicit prohibition on
  inventing model thresholds.

### Fixed — sprint dependency corrections

- GM-004 corrected to depend on GM-003.
- GM-007 corrected to depend on GM-006.
- GM-008 corrected to depend on GM-003, GM-005, and GM-006.
- Recorded that GM-005, GM-009, and GM-010 require GM-001's scaffolding, so **only GM-001 is
  startable at t=0**.
- Recorded that GM-005's numeric-policy precondition is satisfied by the approved half-open
  `[lower, upper)` convention.

### Model configuration

No model configuration version published. Final metric point allocations, bucket thresholds for
both profiles, minimum sample sizes, park and wind thresholds, and the attack-angle proxy
definition remain open Product Owner decisions (Q11–Q22). **Engineering has not invented any
production threshold.**

### Evaluation schema

No schema version published. Contracts are specified but not implemented.

### Not included

No production code, placeholder implementations, grading engine, bucket scoring, signal
execution, Savant adapter, database code, or UI.

---

## [0.1.0] — 2026-07-21 — Documentation baseline

Initial Phase 1 engineering discovery. **No executable code.**

### Added

- `README.md`, `docs/PHILOSOPHY.md`, `docs/ARCHITECTURE.md`,
  `docs/ENGINEERING_GUIDELINES.md`, `docs/SPRINT_1_PLAN.md`, `CHANGELOG.md`.
- Proposed layered architecture with a pure grading core wrapped in adapters; recommended folder
  structure; ranked engineering risks; technical-debt watch list; ten open questions.
- Sprint 1 broken into tickets GM-001 through GM-010 with goals, files, dependencies, acceptance
  criteria, and required tests.

### Superseded by 0.1.1

- Last-14-days validation window
- Generic Attack Angle metric
- Unresolved category-number semantics (Q1–Q4)
- Original sprint dependency table

---

## Model configuration version history

| Model configuration version | Date | Change | Notes |
|---|---|---|---|
| — | — | — | None published. First version will be `v0.1.0`, definable once Q11–Q16 and Q25 are answered. |
