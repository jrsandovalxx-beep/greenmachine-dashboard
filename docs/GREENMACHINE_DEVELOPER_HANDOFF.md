# GREENMACHINE — DEVELOPER HANDOFF (canonical engineering reference)

Audience: a senior engineer (or a fresh Claude conversation) continuing
development. This is the technical handoff, not a user summary. When this
document and the code disagree, the code and its tests win — update this file.

Last updated: 2026-07-25 (revision 3), on
`feature/gm041-production-grading-engine`. **GM-041 is RESUMED and in
progress**, with all WIP committed, the full suite green, and every gate
clean; it is **blocked on one Product Owner ruling** — the §5 signal-removal
contract amendment. See §12 for the exact current state and §16 for the
revision history. The approved product-identity rulings are in §1a/§5 and the
approved GM-042 Record Book scope in §13.

---

## 1. PROJECT OVERVIEW

GreenMachine is a deterministic MLB home-run research platform for a single
Product Owner. For one slate date, one game, and one manually selected hitter
against the expected starting pitcher, it captures raw provider data,
normalizes it into provider-neutral records, freezes the result into immutable
`InputSnapshot`s (one per window profile), and presents everything for manual
review in a Streamlit console. The grading model scores 12 points across five
categories and is being implemented as a pure, config-driven engine.

Core philosophy (each point is architecture-enforced by tests, not aspiration):

- **Deterministic** — same bytes in, same bytes out. Fixed Decimal policy
  (precision 28, ROUND_HALF_EVEN, strings/ints only — never floats), injected
  clocks, no randomness, no UUIDs, `PYTHONHASHSEED`/timezone/cwd-independent.
- **Transparent / zero black-box AI** — no ML anywhere. Every behavior derives
  from explicit, versioned, human-readable rules; changing a threshold means
  changing configuration data, never Python.
- **Auditable** — every derived value carries provenance (provider,
  acquisition method, timing, fallback records); every grading step will carry
  an ordered `AuditEntry` derivation; exclusions are counted, never silent.
- **Immutable evidence** — published run bundles are never overwritten;
  refreshes are new bundles; the only additive artifact is the once-only
  replay report.
- **Replayable** — any bundle regenerates both snapshots byte-identically
  offline from its own archived bytes (self-contained: digest-pinned inputs).
- **Provider-independent grading** — provider wire vocabulary is confined to
  `ingestion/{mlb,savant}/{client,parser}.py`; domain and scoring see only the
  neutral frozen contracts.

## 1a. PROJECT IDENTITY (approved 2026-07-25 — binding on all future work)

**GreenMachine is an evaluation platform, not a betting advisor.** It
evaluates baseball data; the user makes every decision. This is a Product
Owner ruling, not a tone preference:

- GreenMachine intentionally does **NOT** tell the user what to bet. It never
  produces a wager, stake, pick, or recommendation of any kind.
- **Betting classifications are removed from all future scope.** No future
  work may reference or implement `LEAN`, `AVOID`, `PASS`, `STRONG_BET`, or
  any equivalent betting classification. (These appeared in MODEL_SPEC v6.3's
  signal engine; §5 records the required reconciliation.)
- The grading engine's outputs are exactly and only:
  1. **Total Score**
  2. **Tier** (S/A/B/C/D)
  3. **Component Breakdown** (per-component and per-category scores)
  4. **Audit Trail** (the ordered derivation)
  5. **Warnings** (e.g. insufficient-sample findings)
  6. **Fallbacks** (provenance of any fallback actually used)
- Wording discipline everywhere (UI, exports, reports, docs): describe data
  and derivations, never advice. The existing manual-review worksheet already
  conforms (user-entered scores, arithmetic total, tier, verbatim disclaimer).

## 2. CURRENT PROJECT STATUS

Version is **0.2.0** throughout. All milestones below are independently
reviewed and **FROZEN** unless marked otherwise.

| Milestone | Status | One-line summary |
|---|---|---|
| Sprint 1 (GM-001…GM-010, +r-passes) | FROZEN | Domain contracts, config system, determinism primitives, persistence ports, golden/property harness, closeout docs |
| GM-020 (+r1, r2) | FROZEN (baseline `greenmachine-gm-020-r2.zip`, sha256 `232b8a4d…d957`) | Thin production ingestion vertical slice |
| GM-030 (+r1, r2) | FROZEN / deployed | Streamlit manual-review prototype + console hub + deployment readiness |
| GM-040 | Delivered, pending independent review | Operator workflow over the unchanged pipeline + live Ohtani evidence |
| GM-040-HF1 | Delivered hotfix | `-e .` in requirements.txt so Community Cloud installs the project |
| GM-041 | **IN PROGRESS** (this branch; see §12) — suite green, gates clean, blocked on the §5 PO ruling | First production deterministic grading engine (pure, config-driven) |

**GM-020 — ingestion vertical slice.** Objective: one real game/hitter/pitcher
from live providers to two frozen snapshots with deterministic replay.
Implementation: injected transport/clock/sleeper; retry ≤3 no-jitter;
raw-bytes-first archival; strict fail-closed provider schema contracts;
R-only game-type policy with counted exclusions; half-open windows
`[slate−7, slate)` and `[slate−730, slate)`; exact-Decimal event-derived
metrics (barrel = bucket "6", hard-hit ≥95, sweet spot [8,32], IAA [5,20] over
ALL tracked attack-angle rows — swing-level, Pull Air = FB+LD denominator with
row-level stand and exact TAN(15°) geometry); content-derived identities
(`SourceCaptureId` from sorted participating (label, sha256) only; complete-
content `manifest_id`; narrow per-entry `capture_id`); coordinated snapshot
`as_of` = latest participating completion; IAA-only fallback provenance;
prospective timing proven from recorded instants; path-safe atomic
publication; idempotent replay report; strict manifest-v1 semantic contract on
replay; digest-pinned archived sample policy (replay accepts no substitute).
Validation: full-suite green across 5 hash seeds, two timezones, arbitrary
cwd, clean extraction; live prospective Devers bundle. Status: frozen.

**GM-030 — Streamlit manual-review prototype.** Objective: usability prototype
over approved archived runs. Implementation: `greenmachine.reporting` view
models + read-only loader (replay-verifies every run on load; strict display
adapters over audit reports); original console-style landing hub (five blades,
return-to-hub; original artwork, zero remote assets); data-status colors ONLY
(green/yellow/gray/blue/red = data state, never performance — no thresholds
exist); manual review worksheet (user-entered 0–3/0–3/0–2/0–2/0–2, arithmetic
total, frozen manual tier S10–12/A8–9/B6–7/C4–5/D0–3, canonical-state
construction, deterministic JSON/CSV exports, no clock reads); Whiff Rate has
no rendered surface (frozen ruling); pitcher-specific metrics deferred
(Matchup Context = identity/role only; ingredient report never parsed for UI).
r2 added deployment readiness: root `requirements.txt`, deployment-contract
tests, Community Cloud docs. Deployed at
`greenmachine-dashboard-jszumg6nphnppjesc8acng.streamlit.app` (repo
`jrsandovalxx-beep/greenmachine-dashboard`, branch `main`, entry
`streamlit_app.py`, Python 3.12, no secrets). Status: frozen.

**GM-040 — real-data operator slice.** Objective: prove one real
game/hitter/pitcher flows through the existing pipeline end-to-end.
Implementation: pure composition — `ingestion/operator.py` (explicit
`OperatorSelection` incl. projected/confirmed lineup status recorded ONLY in
the generated operator report; honest prospective vs retrospective-development
classification from recorded instants; expected-pitcher **cross-check** (never
an override — manifest v1 binds the pitcher capture to the feed resolution);
idempotent `publish_or_verify` (published / verified-existing / explicit
conflict)) + `scripts/run_gm040_real_slice.py`. Live evidence:
`evidence/gm020_vertical_slice/run_gm040_ohtani/` — Shohei Ohtani (660271),
Dodgers at Mets, gamePk 823600, expected pitcher Nolan McLean (690997,
cross-check matched), captured prospectively ~18h pre-game, replays
byte-identically. Also closed the unguarded `validation` placeholder.
Status: delivered, awaiting independent review; treat as baseline.

**GM-040-HF1.** Community Cloud crashed with `PackageNotFoundError` because
the host installs only `requirements.txt` and `src/greenmachine/__init__.py`
resolves `__version__` from installed metadata (a local `src/greenmachine.egg-info`
build artifact had masked this in every local smoke). Fix: `-e .` as the first
line of `requirements.txt` (the host installs the project itself);
`__init__.py` deliberately left in its frozen metadata-only form; deployment-
contract tests updated (self-install line + four bounded deps, drift-checked
against pyproject). Status: delivered.

## 3. CURRENT REPOSITORY ARCHITECTURE

```
streamlit_app.py        # ONLY module importing streamlit (composition root)
hub_theme.py            # static CSS/HTML asset for the console hub (no imports)
requirements.txt        # -e . + streamlit, PyYAML, pydantic, tzdata (bounded)
pyproject.toml          # version SSOT; extras: ui, dev
.streamlit/config.toml  # telemetry off, headless, focused errors
scripts/                # composition roots ONLY (SystemClock/UrllibTransport live here)
  run_gm020_vertical_slice.py   # capture/replay (GM-020 developer runner)
  run_gm040_real_slice.py       # operator capture/replay (use this one)
  build_release_archive.py      # deterministic, path-validated release zips
  update_goldens.py             # the ONLY golden write path
evidence/gm020_vertical_slice/  # approved immutable run bundles (see §4)
docs/                   # specs, ADRs, runbooks, this handoff
src/greenmachine/
  common/     # Decimal policy (numeric.py), Clock, canonical serialization,
              # deterministic_id, error root, logging
  domain/     # frozen vocabulary + contracts: InputSnapshot, observations,
              # GradeResult variants, results (Component/CategoryScore,
              # BucketHit, ValidationFinding), enums, envelope, outcome
  evaluation/ # freeze_input_snapshot, serialize_record/deserialize_* (schema v1),
              # identity verification
  config/     # GM-003 "rules as data": pydantic schema (GreenMachineConfig),
              # strict YAML loader, §19 semantic validation, GM-004 hashing/versioning
  persistence/# GM-007 append-only ports + in-memory adapters + contract suite
  ingestion/  # GM-020/040: capture, manifest, archive, events, metrics, mapping,
              # orchestration (run_capture/replay_run), operator, policy,
              # strict_json, transport; providers under mlb/ and savant/
  reporting/  # GM-030 view models, loader, formatting, manual_review
  scoring/    # GM-041 (this branch): pure config-driven engine + errors
  features/, cli/, validation/  # guarded docstring-only placeholders
tests/  unit/ integration/ architecture/ golden/ property/ fixtures/ network_guard/
```

Key classes/functions to know: `InputSnapshot` (one profile; content-derived
`snapshot_id`/`input_hash`; only `freeze_input_snapshot` + `deserialize_snapshot`
construct), `MetricObservation`/`MissingObservation` (full provenance,
`sample_status`, `fallback_used`), `EvaluatedGradeResult`/`NotEvaluableGradeResult`
(structurally exclusive; evaluated REQUIRES component+category scores, total,
grade, signal, signal_reason, one SAMPLE_WARNINGS finding per insufficient
present sample, and a strictly-increasing `AuditEntry` derivation),
`GreenMachineConfig` (allocations profile-invariant; bucketed/binary scoring
per profile; typed signal rules; missing-data rule per component),
`run_capture`/`replay_run` (orchestration), `execute_real_slice`/
`publish_or_verify` (operator), `discover_runs`/`load_dashboard` (reporting).

Data flow: operator script → `run_capture` (fetch→parse→normalize→map→manifest)
→ operator report appended → atomic publication → bundle on disk → replay
re-verifies everything → Streamlit loader renders → (GM-041) engine consumes
`InputSnapshot` + `GreenMachineConfig` → `GradeResult`.

## 4. DATA PIPELINE

**Capture** (`ingestion/orchestration.run_capture`): five labeled requests —
`mlb_schedule`, `mlb_game_feed`, `batter_events_recent_7d`,
`batter_events_long_term_2y`, `pitcher_events_season` (audit-only,
non-participating). Assembled entirely in memory; failures publish only
`failed_run/` evidence and never a manifest/snapshot.

**Normalization** (`events.py`, `savant/metrics.py`): identity checks per row,
duplicate collapse (identical→counted, conflict→fail), R-only with per-type
counts, half-open windows excluding the slate date and the selected game,
exact-Decimal metric computations with counted exclusions.

**InputSnapshot** (`mapping.py`): two per run (RECENT_7D, LONG_TERM_2Y),
shared `SourceCaptureId`, coordinated `as_of` = latest participating
completion, per-profile `source_as_of`/`retrieved_at`, EVENT_DERIVED
provenance, IAA-only `FallbackRecord`, injected `SampleMinimumPolicy`
(validation-only fixture; Q14 open), pitch composites/park missing
`SOURCE_UNAVAILABLE` (interim, documented), weather `WEATHER_UNAVAILABLE`.

**Evidence bundles** (immutable, self-contained):
```
manifest.json  raw/*  inputs/{sample_minimum_policy.json,replay_inputs.json}
snapshots/input_snapshot_{recent_7d,long_term_2y}.json
reports/{eligibility,normalization_*,schema,pull_audit_*,pitcher_ingredients,
         limitations,operator_report,replay}.json
OPERATOR_REPORT.md            # GM-040 runs
```
Current bundles: `prospective_run` (Devers/823196, GM-020-r2) and
`run_gm040_ohtani` (Ohtani/823600, GM-040). NEVER modify either.

**Replay** (`replay_run`): strict manifest contract (duplicate-JSON-key
rejection, exact field sets, per-entry capture_id + manifest_id verification,
v1 semantic contract incl. reconstructed-request equality and feed-resolved
pitcher check), raw digest verification, archived-policy digest pinning,
recorded-instant prospective re-validation, byte-identical snapshot
regeneration. Runner replay is repeatable (identical report → success without
rewrite; different → fail closed).

**Manual review** (`reporting/manual_review.py`): user-entered only;
canonical-state construction; deterministic exports with the verbatim
disclaimer; no clock reads; session-state only.

**Operator workflow**: see `docs/GM_040_RUNBOOK.md`. One independent v1 bundle
per hitter — that IS the multi-player model.

## 5. GRADING MODEL

Approved by MODEL_SPEC v6.3 (docs/MODEL_SPEC.md is authoritative; engineering
implements, never invents). 12 points, sum-based (no averaging/rescaling):

| Category | Max | Components |
|---|---|---|
| Power Profile | 3 | exit_velocity, barrel_pct, hard_hit_pct |
| Pitcher Matchup | 3 | pitch_mix_pressure, put_away_pitch_exploitation |
| Form (Recent Form) | 2 | sweet_spot_pct, attack_angle_quality, bat_speed |
| Pull Power | 2 | pull_pct_air_balls |
| Environment | 2 | park, weather |

Tiers from the internal unrounded total: S [10,12] · A [8,10) · B [6,8) ·
C [4,6) · D [0,4). Fractional points expected (Q26); allocations
profile-invariant (Q25); buckets/minimum samples ARE profile- and
measurement-specific. `attack_angle_quality` is one component satisfied by
exactly one measurement (`ideal_attack_angle_pct` or
`attack_angle_threshold_proxy`).

**Engine outputs (approved 2026-07-25, supersedes the v6.3 signal engine):**
Total Score · Tier · Component Breakdown · Audit Trail · Warnings ·
Fallbacks — and nothing else. The former signal engine (AVOID → STRONG_BET →
LEAN → PASS, Q27's override-reason rule, and the Power Profile veto as a
*signal* mechanism) is **removed from all future scope** per §1a.

**Required reconciliation — BLOCKED ON A PO RULING (rev 3).** None of it is
coded. The blast radius below was measured against the repository at rev 3, so
the ruling can be made with the real cost in view:

- **Docs.** `docs/MODEL_SPEC.md` §16/§16.1 (the signal engine and its override)
  plus the §15 and §17 sentences that reference signals; the Q27 closure and
  the Q26 cross-reference in `docs/OPEN_QUESTIONS.md`; `docs/GLOSSARY.md` §
  vocabulary (bound in lockstep by `tests/unit/domain/test_glossary_drift.py`,
  which asserts both the `Signal` members and their documented priority
  order); passing references in `ARCHITECTURE.md`, `PHILOSOPHY.md`,
  `ENGINEERING_GUIDELINES.md`, ADR-0002 and ADR-0004.
- **Frozen domain contract.** `EvaluatedGradeResult` REQUIRES `signal` and
  `signal_reason` (both validated in `__post_init__`); `Signal` is a domain
  enum. `NotEvaluableGradeResult` only mentions signals in prose.
- **Frozen evaluation schema v1.** `evaluation/serialization.py` pins the
  evaluated record's exact field set including `signal`/`signal_reason`, and
  rejects those keys on a not-evaluable record. Removing them changes the
  serialized shape, so the ruling must also say whether
  `RECORD_SCHEMA_VERSION` stays 1 (amended in place — nothing durable has been
  written yet, since no evaluation is persisted anywhere) or becomes 2.
- **Config contract.** `AllocationConfig.signal_rules` is required
  (`min_length=1`) with the typed `SignalRule`/`SignalClause`/`SignalCondition`
  family, and §19 validation enforces one rule per `Signal`, the
  AVOID→STRONG_BET→LEAN→PASS priority order, and a terminal always-rule.
  Removal changes the semantic `config_hash` of every configuration.
- **Goldens and fixtures.** Two of the three golden cases embed
  `signal`/`signal_reason` (regeneration only via `scripts/update_goldens.py`
  under this ticket); `tests/golden/stub_scorer.py`, the evaluation fixtures,
  and roughly a dozen config/domain/golden test modules assert on signals.
- **Not affected:** the ingestion pipeline, both evidence bundles, replay, and
  the Streamlit UI. No rendered surface displays a signal today, and no
  `GradeResult` is stored in any bundle — so replay determinism and the
  archived evidence are untouched by this amendment.
- **Open PO sub-question (do not decide silently).** The "strong category"
  fraction (0.75 in the spec, compared unrounded) exists **only** to feed
  signal conditions — confirmed: `_strong_categories` in the engine is its
  sole behavioral consumer in `src`, and its only consumer is `_signal_for`.
  Options: (a) keep it as a pure audit-trail annotation under the §1a Audit
  Trail output, (b) keep it as a per-category annotation in the Component
  Breakdown, or (c) remove it from the engine and the configuration schema.
  Engineering recommends (a): it is descriptive, not advisory, so it survives
  §1a, and it preserves an explanatory step in the derivation at no cost.

Threshold philosophy: **all numeric rules are configuration data**
(`GreenMachineConfig`): bucket boundaries half-open with a closed terminal
bucket at the domain max; §19 invariants enforced at load (monotonic points,
no gaps/overlaps, allocations sum exactly, strongest bucket awards
max_points); scoring numerics are quoted YAML strings → exact Decimals.
Auditability: every result must carry its ordered `AuditEntry` derivation.

**Pending / open PO decisions (DO NOT INVENT):** Q11 (per-component
max_points), Q12/Q13 (production bucket thresholds per profile), Q14
(production sample minimums), Q15/Q16 (pitch-matchup formulas — components
currently missing in snapshots). Consequently **no production
model-configuration version exists**; every executable configuration in the
repo is synthetic, disclaimed, and validation-only.

## 6. ARCHITECTURAL DECISIONS

(ADRs live in docs/adr/; all eight Accepted.)

- **Immutable evidence** — trust comes from bytes that cannot change;
  publication is atomic + path-validated; conflicts fail, never overwrite.
- **Replay determinism** — the acceptance test of the whole system; no clock,
  network, cwd, hash-seed, or timezone may influence a replay (ADR-0002/0003).
- **Provider independence** — wire vocabulary AST-confined to client/parser
  modules; grading consumes only neutral contracts (v6.3 provenance model:
  generic provider_id + acquisition_method; eligibility outranks priority).
- **Config-driven thresholds** — "rules as data" (ARCHITECTURE §4.2): a
  threshold change is a data change with a semantic `config_hash` (GM-004),
  never a code change; source-side guards reject component-name-beside-number.
- **Pure grading engine** — `GradeResult` = f(frozen snapshot, configuration);
  no time, id, hash, or outcome on the result (ADR-0004); outcomes are a
  separate append-only record (ADR-0006).
- **pandas stays outside grading** — grading is exact-Decimal arithmetic on
  small frozen records; pandas' float coercion and index magic would break
  ADR-0002 determinism. (pandas is permitted only ingestion/features side if
  ever needed; currently nothing in src imports it.)
- **No network in tests, ever** — suite-wide socket/resolver guard + guarded
  child bootstrap for every spawned Python; the app performs zero calls
  (telemetry disabled); live capture is script-triggered only.
- **Auditability required** — long-horizon evaluation research demands the
  derivation be inspectable years later: counted exclusions, provenance,
  audit entries, operator reports, replay reports.
- Other: append-only persistence with supersession chains (GM-007); goldens
  write only via `scripts/update_goldens.py`; Hypothesis fixed seed 20260724;
  strict JSON (duplicate keys rejected) for every GreenMachine-owned document.

## 7. COMPLETED FEATURES (production-ready)

Everything in §2 marked frozen: ingestion pipeline + replay; operator
workflow; Streamlit console (deployed; run selector auto-discovers bundles
under `evidence/gm020_vertical_slice/`); manual review + exports; release
tooling. Deployment: push to `main` → Community Cloud auto-redeploys;
requirements install `-e .` + four bounded deps; no secrets; entry
`streamlit_app.py`; evidence ships in-repo. 3,504 tests green (rev 3) across
hash seeds; ruff + mypy --strict clean.

## 8. DEFERRED FEATURES (all explicitly ruled out of past tickets)

- **Today's Slate / full-slate aggregation** — blocked on manifest-v1's
  one-hitter shape (a slate = N independent bundles today); a slate bundle
  needs an approved manifest v2 ruling.
- **Pitchers to Target / bullpen analysis** — PO deferred all pitcher-specific
  metrics (incl. any Whiff Rate surface) to a dedicated future tab/tag;
  no bullpen capture exists in manifest v1.
- **Record Book / outcomes / any database** — now the approved **GM-042**
  (§13), but blocked behind GM-041 completion and a durable-storage ruling
  (ports + in-memory adapters are ready); nothing to record until grading +
  outcome ingestion exist.
- **Dashboard redesign** — waits on PO usability notes from the prototype.
- **Weather / park expansion** — no approved source (components stay missing).
- **Betting classifications and betting advice — permanently out, not
  deferred** (§1a): no Lean/Avoid/Pass/Strong-Bet or equivalent will ever be
  implemented; no odds tracking, no CLV, no stake/pick/recommendation
  surface. Architecture guards already ban several of these strings; keep
  the guards.

## 9. KNOWN ISSUES / TECHNICAL DEBT

- `src/greenmachine.egg-info/` appears locally after editable installs; it is
  gitignored/excluded from releases but once masked the HF1 bug — delete it
  when testing uninstalled behavior.
- Overview shows the venue-local first pitch rendered as UTC (snapshot decode
  normalizes datetimes) — cosmetic; queued for the UI-refinement ticket.
- Team/opponent names, pitcher handedness, hitter batting side are not in the
  neutral archive (displayed as "not recorded").
- First load of a run replays fully (~seconds), then caches per session.
- Pitch composites/park use interim `SOURCE_UNAVAILABLE`; a derivation-pending
  MissingReason is an open vocabulary question.
- GitHub `main` may lag local (local is authoritative); HF1 required `main`
  sync — verify deployment alignment when touching requirements/entry files.
  As of rev 3 this machine has **no GitHub access at all**: no `gh`, no
  credentials, no local `main` branch, and `git ls-remote origin` times out.
  Nothing on this branch has ever been pushed; the operator must push and open
  the PR. Treat the local repository as authoritative until that changes.
- Windows dev box: symlink tests skip; `sendmsg` guard test skips.

## 10. DEVELOPMENT RULES (standing; most are test-enforced)

1. Never modify frozen evidence bundles or committed goldens (goldens change
   only via `scripts/update_goldens.py` under an explicit ticket).
2. Never break replay determinism: no clock/network/randomness/float in
   behavior paths; Decimal from strings/ints only; canonical serialization.
3. Never introduce hidden logic — every rule is configuration or spec-cited
   code with an audit trail; no silent defaults, no broad excepts, fail closed.
4. Never hardcode thresholds/allocations/minimums in src (guards scan for it);
   never invent values for open questions Q11–Q16 — synthetic fixtures must be
   loudly disclaimed and live under tests/fixtures.
5. Always maintain auditability (counted exclusions, provenance, AuditEntry).
6. Frozen contracts (domain/evaluation schema v1, manifest v1 labels+semantics,
   metric definitions, error taxonomy) change only via explicit PO ticket.
7. Streamlit only in `streamlit_app.py`; transports/clocks only in `scripts/`;
   ingestion never imports reporting; reporting never imports scoring/clients.
8. All work on feature branches; never push directly to `main`; never
   force-push or rewrite history; PRs merge only after human review.
9. Run the full gate before any delivery: pytest -q, ruff format --check,
   ruff check, mypy --strict src, plus replay verification of shipped evidence.

## 11. GITHUB WORKFLOW

Repo `jrsandovalxx-beep/greenmachine-dashboard` (private), branch `main` ==
deployed baseline. Flow: `git checkout -b feature/<ticket-slug>` → commit
(imperative messages, ticket-prefixed, e.g. `GM-041: …`) → push the feature
branch → open PR to `main` → human (PO) review → merge → Streamlit Community
Cloud auto-redeploys `main`. Agents must never merge, force-push, or delete
evidence. Note: this development machine currently has NO GitHub
credentials/`gh` — if pushing fails, commit locally and hand the operator
exact push/PR commands.

## 12. CURRENT MILESTONE — GM-041 (this branch) — **IN PROGRESS**

**Objective:** first production deterministic grading engine.
**Deliverables (unchanged except outputs):** `src/greenmachine/scoring/`
engine consuming frozen `InputSnapshot`s + `GreenMachineConfig`, producing
`EvaluatedGradeResult` / `NotEvaluableGradeResult` with a complete ordered
audit derivation (every awarded AND unawarded point explained) and
SAMPLE_WARNINGS findings. Per §1a the outputs are exactly: Total Score,
Tier, Component Breakdown, Audit Trail, Warnings, Fallbacks — **no signal of
any kind**. Unit+integration tests over a disclaimed synthetic configuration;
a sample evaluation of the real `run_gm040_ohtani` bundle under that
synthetic config; guard updates (scoring leaves the placeholder list);
handoff + docs.
**Out of scope:** Today's Slate, bullpens, Record Book, betting
classifications of any kind (§1a — permanent), dashboard redesign,
historical calibration, persistence wiring, and any production configuration
values.
**Success criteria:** full suite + gates green; GM-040 evidence still replays
byte-identically; engine is pure (no I/O, clock, network, pandas, floats);
identical inputs give byte-identical serialized results; sample Ohtani
evaluation generated and clearly labeled synthetic/non-production.

### Exact state on `feature/gm041-production-grading-engine` (rev 3)

Nothing is uncommitted. The rev-2 working tree was committed verbatim in
`4542b22` before any change, so the paused state stays inspectable, and the
corrections landed on top in `17ed58f`.

Committed engine (unchanged since rev 2 except a typing annotation):
- `src/greenmachine/scoring/engine.py` — `score_snapshot`, bucket resolution,
  binary qualification, missing-data handling, aggregation, grade, strong
  categories, signal, audit derivation. **Written before the §1a signal
  ruling; its signal handling is exactly what the §5 amendment removes.**
- `src/greenmachine/scoring/errors.py` (`ScoringError`, `ScoringConfigError`,
  `ScoringInputError`); `__init__.py` re-exports the engine and the errors.
  NOTE: the `__init__` docstring's first line still says "…grades, and
  signals" — reword during the §5 reconciliation.

Committed test material:
- `tests/unit/scoring/test_engine.py` — 23 tests, all passing.
- `tests/fixtures/config/valid/gm041_engine_synthetic.yaml` — loudly
  disclaimed synthetic config (deliberately wrong-for-baseball: category split
  2.8/3.1/2.1/2.2/1.8, grade table 3.7/5.9/8.1/9.8, strong fraction 0.66) so
  it can never be mistaken for the approved model.
- `tests/fixtures/evaluations/gm041_engine_snapshots.py` — frozen RECENT_7D
  snapshot builders over the fixture's eleven components, with per-test
  control of values/missing/insufficient/absent/measurement.
- `tests/architecture/test_scoring_boundaries.py` — **new**; replaces the
  placeholder guards with purity guards (approved-import set, no third party,
  no I/O or non-deterministic stdlib, no clock, no randomness, no float in
  either spelling, no numeric literal beyond the additive identity), each with
  meta-tests proving it bites. `scoring` was removed from the placeholder
  lists in `tests/architecture/test_ingestion_boundaries.py` and
  `tests/unit/docs/test_documentation_integrity.py`.

The two rev-2 failures were **test-side expectation defects, not engine
defects**, and are fixed: one asserted a lower-case `MissingReason` (members
are upper case by frozen design); the other drove an enabled fuzzy policy
through the loader, which §19 validation rejects first, so the engine guard
was unreachable — it is now split into the loader refusal and the engine
refusal as two independent tests. Rev 2 §14 also understated the failure count
as two: the placeholder guards were failing as well, since `scoring` had
gained behavior.

Verified at rev 3: full suite **3504 passed, 5 skipped** (Windows platform
skips only); `ruff format --check .`, `ruff check .`, `mypy --strict src` all
clean; both evidence bundles (`prospective_run`, `run_gm040_ohtani`) still
replay byte-identically.

**Remaining work, in order:** (1) **BLOCKED — the §5 signal-removal contract
amendment needs a PO ruling** (spec + frozen domain/serialization contracts +
config schema, with ruling text; see §5 for the measured blast radius);
(2) align the engine to the six §1a outputs once ruled; (3) the sample Ohtani
evaluation under the synthetic config; (4) full gates and PR.

## 13. FUTURE ROADMAP

**GM-042 — Record Book & Performance Analytics (APPROVED 2026-07-25).**
The Record Book measures **GreenMachine's historical performance — not
sportsbook market efficiency**. Approved scope:

- Season Summary
- Daily Results
- Unit Tracker
- ROI Summary
- Performance Analytics
- Model Calibration
- Historical Archive
- Revision History

Explicitly **excluded** from GM-042 (PO ruling): Average Odds, Closing Line
Value (CLV), Average Confidence Tier.

GM-042 prerequisites the next conversation should surface to the PO early:
GM-041 complete (there is nothing to record without evaluations); an
outcome-ingestion definition (Q8 fixed ground truth = ≥1 HR in the evaluated
game; the `OutcomeRecord` contract and GM-007 append-only ports with
supersession/revision chains already exist); a durable-storage ruling (no
database exists or is currently permitted); and a PO definition of "unit"
for the Unit Tracker / ROI Summary consistent with §1a (GreenMachine records
the user's own results and the model's calibration — it still never advises).

**After GM-042 (recommended, unnumbered until the PO assigns tickets):**
- PO resolves Q11–Q14 → first production model-configuration version
  (data-only ticket) + golden regeneration under the real engine.
- Evaluation persistence wiring (envelope + GM-007 ports; durable adapter
  per the GM-042 storage ruling) so evaluations are stored/queryable.
- UI: evaluation view in the console (score/tier/breakdown/audit display
  per §1a) + PO usability-driven refinements.
- Q15/Q16 pitcher-composite formulas → pitcher capture becomes participating
  where ruled; unlocks Pitcher Matchup scoring for real.
- Slate operations (manifest v2 ruling) → Today's Slate.
- Pitchers to Target/bullpens — gated on an explicit PO specification.

## 14. QUICK START (new conversation checklist)

1. Read this file, then `CLAUDE.md`-equivalents: `docs/MODEL_SPEC.md` (rules),
   `docs/ARCHITECTURE.md`, `docs/OPEN_QUESTIONS.md` (what NOT to invent),
   `docs/GM_040_RUNBOOK.md`.
2. `python -m pip install -e ".[dev,ui]"` in a venv (Python 3.11+).
3. `python -m pytest -q` — expect fully green (3504 passed as of rev 3, plus
   five Windows platform skips). The rev-2 GM-041 failures are fixed; any
   failure now is a real regression.
4. Gates: `ruff format --check .` · `ruff check .` · `mypy --strict src`.
5. Verify evidence: `python scripts/run_gm040_real_slice.py replay --run-dir
   evidence/gm020_vertical_slice/run_gm040_ohtani` → "replay OK".
6. UI: `streamlit run streamlit_app.py`.
7. Branch from `main`, follow §10/§11, never touch `evidence/` or goldens.
8. Check the CHANGELOG `[Unreleased]` section for anything newer than this doc.

## 15. APPENDIX

**Paths:** entry `streamlit_app.py`; theme `hub_theme.py`; engine
`src/greenmachine/scoring/`; operator `src/greenmachine/ingestion/operator.py`;
orchestration `src/greenmachine/ingestion/orchestration.py`; evidence root
`evidence/gm020_vertical_slice/` (bundles: `prospective_run`,
`run_gm040_ohtani`); goldens `tests/golden/cases/`; synthetic sample policy
`tests/fixtures/ingestion/gm020_nonproduction_sample_policy.json`; synthetic
engine config (GM-041, committed at rev 3)
`tests/fixtures/config/valid/gm041_engine_synthetic.yaml` with snapshot
builders in `tests/fixtures/evaluations/gm041_engine_snapshots.py`; scoring
purity guards `tests/architecture/test_scoring_boundaries.py`.

**Configuration files:** `pyproject.toml` (version SSOT, extras, tool config),
`requirements.txt` (deployment; `-e .` first), `.streamlit/config.toml`,
`.gitignore`, `.pre-commit-config.yaml`.

**Commands:**
```bash
python -m pip install -e ".[dev,ui]"          # dev setup
python -m pytest -q                            # full suite
python -m ruff format --check . && python -m ruff check .
python -m mypy --strict src
streamlit run streamlit_app.py                 # local UI
python scripts/run_gm040_real_slice.py capture --slate-date YYYY-MM-DD \
  --game-pk N --batter-id N --lineup-status projected \
  --output-dir evidence/gm020_vertical_slice/run_gm040_<name> \
  --sample-policy tests/fixtures/ingestion/gm020_nonproduction_sample_policy.json \
  --capture-mode prospective                   # live capture (real network)
python scripts/run_gm040_real_slice.py replay --run-dir <bundle>
python scripts/build_release_archive.py --output <name>.zip
```

**Developer notes:** PowerShell mangles UTF-8 on `-replace` file rewrites —
use the Write/Edit tooling for source files. AppTest (`streamlit.testing.v1`)
drives the UI in-process under the network guard. `SteppingClock`/
`FakeTransport` in `tests/fixtures/ingestion/synthetic_provider_fixtures.py`
are the capture-test workhorses. Exit codes for runners: 0 ok · 2 typed error
· 3 not published · 4 replay mismatch.

## 16. REVISION HISTORY

| Rev | Date | Commit / branch | Changes |
|---|---|---|---|
| 1 | 2026-07-25 | `ab095d0` on `feature/gm041-production-grading-engine` | Initial canonical handoff: project overview, frozen milestone status through GM-040+HF1, architecture, pipeline, grading model per MODEL_SPEC v6.3 (including the signal engine as then specified), ADRs, deferred features, debt, development rules, GitHub workflow, GM-041 plan, roadmap, quick start, appendix. |
| 3 | 2026-07-25 | this commit, same branch | **GM-041 RESUMED.** The rev-2 working tree was committed verbatim (`4542b22`) so the paused state stays inspectable, then corrected (`17ed58f`). Both rev-2 failures were diagnosed as **test-side expectation defects, not engine defects** (a lower-case `MissingReason` assertion; a fuzzy-policy test whose config the §19 loader rejects first, making the engine guard unreachable — now split into the loader refusal and the engine refusal). Rev 2 §14 understated the failure count as two: the two placeholder guards were failing as well, because `scoring` had gained behavior. Those guards are retired — `scoring` leaves the placeholder lists in `test_ingestion_boundaries.py` and `test_documentation_integrity.py`, replaced by the new `tests/architecture/test_scoring_boundaries.py`, which enforces the §12 purity criteria structurally (approved imports, no third party, no I/O, no clock, no randomness, no float, no embedded numeric threshold) with meta-tests. Gate fixes on the WIP: `_OPERATORS` annotated (four `no-any-return` errors clear under `mypy --strict`), one en dash removed for RUF002, `ruff format` applied. §5 now carries the **measured** blast radius of the pending signal-removal amendment (docs, domain contract, evaluation schema v1 with the explicit v1-vs-v2 question, config schema and `config_hash`, goldens; ingestion/replay/evidence/UI confirmed unaffected) and scopes the strong-category sub-question with a recommendation. §12 rewritten as the current in-progress state; §2/§3/§7/§9/§14/§15 refreshed against the repository. Verified: 3504 passed / 5 skipped, all gates clean, both evidence bundles replay byte-identically. |
| 2 | 2026-07-25 | `3ac1c7d`, same branch | **GM-041 officially PAUSED** with its exact in-progress state recorded (§12: committed engine/errors modules, uncommitted `__init__` diff, three untracked test/fixture files, 20/22 tests passing with the two named failures, resumption order). Recorded the approved product-identity rulings (§1a): GreenMachine is an evaluation platform, not a betting advisor; betting classifications (Lean/Avoid/Pass/Strong-Bet) removed from all future scope; engine outputs restricted to Total Score, Tier, Component Breakdown, Audit Trail, Warnings, Fallbacks; the user makes the decision. §5 rewritten accordingly with the required MODEL_SPEC §16 / `EvaluatedGradeResult` / config signal-rule reconciliation steps and the open strong-category question. §8 reframed betting items as permanently out. §13 replaced with the approved **GM-042 Record Book & Performance Analytics** scope (Season Summary, Daily Results, Unit Tracker, ROI Summary, Performance Analytics, Model Calibration, Historical Archive, Revision History; explicitly excluding Average Odds, CLV, Average Confidence Tier — the Record Book measures GreenMachine's historical performance, not sportsbook market efficiency) plus unnumbered follow-ons. Appendix fixture paths corrected; quick-start updated for the pause. |
