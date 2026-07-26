# GREENMACHINE — DEVELOPER HANDOFF (canonical engineering reference)

Audience: a senior engineer (or a fresh Claude conversation) continuing
development. This is the technical handoff, not a user summary. When this
document and the code disagree, the code and its tests win — update this file.

Last updated: 2026-07-25 (revision 11), on
`feature/gm041-5-stabilization-ux-review`. **GM-041 is APPROVED AND MERGED**
(`origin/main` at `28727fa`). **GM-041.5 — Stabilization & UX Review — is
COMPLETE and awaiting review**: the engine's evaluation is now visible in the
Streamlit console under a disclaimed non-production configuration.
The signal-removal amendment is implemented, snapshot/configuration coherence
is enforced, the sample evaluation is generated, all gates are green, and the
work sits on a branch grafted cleanly onto `origin/main`. See §12 for the
delivered state, §11a for the repository-history issue and its resolution, §9
for the deferred Windows archive line-ending risk, §0 for the standing
one-ticket rule, and §16 for the revision history.

---

## 0. STANDING PROCESS RULES (binding)

**One ticket at a time.** Exactly one ticket is active. While it is open, do
not perform repository restructuring, duplicate-tree cleanup, deployment
reorganization, unrelated configuration cleanup, or any other maintenance
work, and do not start the next ticket. Work you notice but must not do gets
recorded here (see §9 and §13), never done opportunistically.

**Evaluation is separate from decision-making** (§1a, `PHILOSOPHY.md` §1.1) —
permanent and binding on every future ticket.

**Never push to `main`; always work on a feature branch; open a PR and wait
for human approval.** Never merge. Never force-push or rewrite pushed history.

**A milestone is incomplete until this handoff is updated** and its revision
history extended.

---

## 1. PROJECT OVERVIEW

GreenMachine is a deterministic MLB home-run research platform for a single
Product Owner. For one slate date, one game, and one manually selected hitter
against the expected starting pitcher, it captures raw provider data,
normalizes it into provider-neutral records, freezes the result into immutable
`InputSnapshot`s (one per window profile), and presents everything for manual
review in a Streamlit console. The grading model scores 12 points across five
categories and **is implemented** (GM-041) as a pure, config-driven engine. The
Streamlit prototype does not yet render that engine's evaluation; surfacing it
belongs to GM-041.5.

Core philosophy (each point is architecture-enforced by tests, not aspiration):

- **Deterministic** — same bytes in, same bytes out. Fixed Decimal policy
  (precision 28, ROUND_HALF_EVEN, strings/ints only — never floats), injected
  clocks, no randomness, no UUIDs, `PYTHONHASHSEED`/timezone/cwd-independent.
- **Transparent / zero black-box AI** — no ML anywhere. Every behavior derives
  from explicit, versioned, human-readable rules; changing a threshold means
  changing configuration data, never Python.
- **Auditable** — every derived value carries provenance (provider,
  acquisition method, timing, fallback records); every grading step carries an
  ordered `AuditEntry` derivation; exclusions are counted, never silent.
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
| GM-041 | **APPROVED and MERGED** into `origin/main` (`28727fa`) | First production deterministic grading engine (pure, config-driven) + betting-classification removal |
| GM-041.5 | **COMPLETE, awaiting review** (this branch; see §12a) | Engine evaluation surfaced in the Streamlit console + UX stabilization |

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
`sample_status`, `fallback_used` — fallback provenance reaches the engine
through the observations, not through a field on the result),
`EvaluatedGradeResult`/`NotEvaluableGradeResult` (structurally exclusive;
evaluated REQUIRES component scores, category scores, total score, tier/grade,
a strictly-increasing `AuditEntry` derivation, and one SAMPLE_WARNINGS finding
per insufficient present sample — and carries **no** betting classification of
any kind), `GreenMachineConfig` (allocations profile-invariant;
bucketed/binary scoring per profile; grade cutoffs; missing-data rule per
component — and **no** signal rules),
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

**Signal-removal amendment — DELIVERED (rev 4, PO ruling 2026-07-25).** Every
betting classification is gone from the codebase: `Signal`, `signal`,
`signal_reason`, Strong Bet, Lean, Pass, Avoid, and the recommendation-engine
concept. What changed:

- **Domain.** The `Signal` enum was deleted; `EvaluatedGradeResult` no longer
  declares or validates `signal`/`signal_reason`. `NotEvaluableGradeResult` is
  unchanged apart from prose.
- **Evaluation schema v1, amended in place** (PO ruling: no v2). The evaluated
  record's field set no longer admits the two keys, and the evaluated /
  not-evaluable discriminator now keys on `grade`/`total_score` alone. No
  migration was required because no production evaluation record exists
  anywhere.
- **Configuration.** `signal_rules`, the whole `SignalRule`/`SignalClause`/
  `SignalCondition` family, and `strong_category_fraction` were removed from
  the schema, the §19 validation, the loader's discriminated-union table, and
  the package exports. §19 invariant 17 is retired. Every `config_hash` moves
  as a result, which is correct and expected — no production configuration
  version exists to invalidate.
- **Strong-category fraction: removed entirely** (PO ruling). It existed only
  to feed signal conditions and has no replacement metric.
- **Engine.** `_signal_for`, `_signal_reason`, and `_strong_categories` are
  gone; `score_snapshot` returns after grade assignment.
- **Docs.** `MODEL_SPEC.md` §16 is now "Evaluation output (betting
  classifications removed)" and carries the historical note; §3.1, §4, §15,
  §17, and §19 were reconciled. `OPEN_QUESTIONS.md` Q27 is marked
  **SUPERSEDED**, Q26 and Q3 are superseded in part. `GLOSSARY.md` lost the
  Signal, Signal-override, and Strong-category entries and the `Signal` row of
  the machine-checked vocabulary block. `ARCHITECTURE.md` (including risk R10,
  now retired), `ENGINEERING_GUIDELINES.md`, `PHILOSOPHY.md`, ADR-0002,
  ADR-0004, and `STREAMLIT_PROTOTYPE.md` were reconciled. `PHILOSOPHY.md`
  §1.1 records the permanent evaluation-versus-decision principle.
- **Goldens.** Regenerated through `scripts/update_goldens.py` (the only
  approved write path). Because a schema amendment makes the *existing*
  goldens unloadable, the script cannot read them to rewrite them; the two
  now-unknown keys were stripped as a bootstrap so the script could load the
  cases, and the committed bytes are the script's canonical output.
- **Not affected, as predicted and re-verified:** the ingestion pipeline, both
  evidence bundles, replay determinism, and the Streamlit UI.

Historical notes explaining the removal are permitted throughout; production
implementation references are not.

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
`streamlit_app.py`; evidence ships in-repo. 3,665 tests green (rev 11) across
hash seeds 0/1/42; ruff + mypy --strict clean.

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
- **Repository history divergence** (§11a): local history and `origin/main`
  share no ancestor, and `main` carries a nested duplicate project tree.
  Resolved for GM-041 by the clean graft; the underlying duplication is
  **deferred to its own cleanup ticket**.
- `git push` works from this machine (Git Credential Manager is configured),
  but **`gh` is not installed**, so a pull request cannot be opened from here.
  Push the branch and open the PR through the GitHub web UI.
- **Decimal-context leak in scoring aggregation (FIXED at rev 8; recorded here
  because it is the sharpest determinism lesson in the project so far).** Both
  aggregation paths summed with a bare `total = total + points`, which evaluates
  under the **caller's mutable global Decimal context**, not the project one.
  ADR-0002 fixes precision 28 / ROUND_HALF_EVEN precisely so a score cannot
  depend on ambient state, and this bypassed it.

  Independently measured, then reproduced here, on the *same* synthetic snapshot
  and configuration:

  | Caller context | Total | Tier |
  |---|---|---|
  | normal | `11.55` | S |
  | precision 1, `ROUND_DOWN` | `7` | **B** |
  | precision 2, `ROUND_UP` | `12` | S |
  | precision 3, `ROUND_FLOOR` | `11.5` | S |

  A tier moved from S to B on identical inputs. Fixed by routing both paths
  through `greenmachine.common.numeric.add`. The process-global context is never
  modified. Regression coverage compares **every** output surface — component
  scores, category scores, total, tier, warnings, fallbacks, the ordered audit
  derivation, and the serialized bytes — across all four contexts, plus two
  tests proving the caller's precision, rounding, and traps survive a call
  untouched.

  **Lesson for anyone extending the engine:** never use a bare arithmetic
  operator on a `Decimal` in `src/`. Use the GM-005 primitives. The existing
  determinism guards did not catch this, because they scan for clock reads,
  randomness, floats, and `Decimal(float)` — not for context-sensitive
  operators. Tightening that guard is worthwhile future work.

- **Windows line-ending corruption of digest-pinned evidence (DEFERRED to
  repository cleanup — pre-existing on `main`, not introduced by GM-041).**
  `main` carries `.gitattributes` with `* text=auto`. On Windows, `core.eol`
  defaults to `native`, so **any** checkout — clone, `git archive`, worktree —
  rewrites files git classifies as text to CRLF. That includes the
  **digest-pinned evidence bundles**, whose bytes must not change.

  Measured at rev 5 on the GM-041 bundle:

  | Checkout | `raw/batter_events_recent_7d.csv` | Replay |
  |---|---|---|
  | git object / manifest pinned digest | `461d04a3…` | — |
  | fresh Windows clone (default `core.eol=native`) | `d957b9eb…` | **FAILS** |
  | fresh clone with `core.eol=lf` | `461d04a3…` | **passes** |
  | `git archive` on this host | `d957b9eb…` | **FAILS** |

  A default Windows clone fails replay with `SamplePolicyError` — the archived
  policy digest no longer matches what the capture recorded. **The repository
  is not corrupt**: the committed objects are byte-correct, and replay passes
  from any LF checkout and from the existing working tree (whose evidence files
  predate the `.gitattributes` and were never rewritten).

  Workaround in force for reviewers, documented in the review package:
  `git clone -c core.autocrlf=false -c core.eol=lf …`. Review artifacts ship as
  a **git bundle** (raw objects, no filtering) and `changed_files/` is populated
  with `git cat-file blob`, never `git archive`.

  The durable fix is an `-text` (binary) attribute for `evidence/**` so the
  pinned bytes are never converted on any platform. That edits `.gitattributes`,
  which the Product Owner placed **out of scope for GM-041**, so it is assigned
  to the repository-cleanup ticket. It should be treated as that ticket's
  highest-priority item: today a Windows contributor cloning fresh cannot
  reproduce replay.

- The orphaned `greenmachine-dashboard` gitlink blocks checkout of a
  mainline-based branch until moved aside (§11a). Cleanup ticket.
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

## 11a. REPOSITORY HISTORY — DIVERGENCE AND CLEAN GRAFT (rev 4)

**The problem.** The local repository and GitHub `main` have **no common
ancestor**. `main` was built largely by web-UI uploads (its history contains
commits named "Add files via upload", "Full Integration", "patch"), while the
local history is rooted at the GM-040 baseline `8de28f7`, which does not exist
on `main` at all. `git merge-base HEAD origin/main` returns nothing.

`main` also carries a **complete duplicate copy of the project nested under
`greenmachine/`**, in addition to the real project at its root, plus a
`.gitattributes` (`* text=auto`) that the local root lacks.

Consequently a PR from the original `feature/gm041-production-grading-engine`
branch read as **293 files changed, 3,126 insertions, 64,874 deletions** —
almost all of it proposing to delete `main`'s nested duplicate.

**The resolution (PO ruling 2026-07-25): clean graft/replay.**
`feature/gm041-production-grading-engine-mainline` branches directly from
`origin/main` and replays only the intentional GM-041 delta.

Deliberately **not** carried across, and preserved as `main` has them:
`.gitattributes`, the nested `greenmachine/` directory, the deployment
structure, `.claude/settings.local.json` (machine-local), the `.gitignore`
`*.zip` addition, and the root `GREENMACHINE_HANDOFF.md`. Repository cleanup —
including whether the nested duplicate should exist at all — is **deferred to
its own future ticket** and must not be done inside a feature ticket (§0).

The original branch remains pushed as an **archival/reference branch**. Do not
force-push or rewrite it.

### Which tree is canonical (binding)

**The repository-root project is the current canonical implementation.** Everything
at the root — `src/`, `tests/`, `docs/`, `scripts/`, `evidence/`,
`streamlit_app.py` — is the live system.

**The nested `greenmachine/` tree on `main` is a preserved, NONCANONICAL
duplicate.** It arrived through web-UI uploads, contains stale historical
implementation content, and is retained only because deleting it is repository
cleanup rather than feature work. It must **not** be used for:

- development or any code change;
- code review or reading "the current implementation";
- deployment decisions (Community Cloud serves the root project); or
- interpreting product status, completeness, or which features exist.

A reviewer or contributor who reads the nested tree will draw wrong conclusions
about what GreenMachine currently does. Removing or reconciling it remains a
**separate repository-cleanup ticket** (§13), not part of any feature ticket.

**Consequences for anyone working here:**
- Branch from `origin/main`, never from the archival branch.
- `main`'s `.gitignore` does not ignore `*.zip`, and the working tree contains
  release archives. **Never `git add -A`** on a mainline-based branch; stage
  explicit paths.
- The local tree carries `greenmachine-dashboard` as an orphaned gitlink
  (mode 160000, no `.gitmodules`, contents just `.git` and `.gitattributes`)
  while `main` tracks it as ordinary files. Checking out a mainline-based
  branch fails until that directory is moved aside. It is cruft, but removing
  it is cleanup and therefore its own ticket.
- The full suite reports **one fewer test** on a mainline-based branch than on
  the archival branch (3,503 rather than 3,504 at graft time) because `main`
  has no root `GREENMACHINE_HANDOFF.md` and the documentation suite
  parameterizes over root markdown files. Adding or removing any markdown file
  under `docs/` or the root moves the count by design.

---

## 12. PREVIOUS MILESTONE — GM-041 — **APPROVED AND MERGED**

**Branch:** `feature/gm041-production-grading-engine-mainline` (grafted onto
`origin/main`; see §11a).

**Objective:** the first production deterministic grading engine, plus the
Product-Owner-ruled removal of every betting classification.

**Delivered:**
- `src/greenmachine/scoring/` — `engine.py` (`score_snapshot`: bucket
  resolution, binary qualification, missing-data handling, category and total
  aggregation, grade assignment, ordered audit derivation), `errors.py`
  (`ScoringError`, `ScoringConfigError`, `ScoringInputError`), `__init__.py`.
  Pure: no I/O, clock, network, randomness, pandas, or float.
- **Decimal-context independence (rev 8):** both aggregation paths sum through
  `greenmachine.common.numeric.add`, which runs under the **project-local**
  Decimal context (precision 28, ROUND_HALF_EVEN). A bare `a + b` uses the
  caller's mutable global context, so ambient precision and rounding leaked
  into the score and the tier — see §9 for the measured divergence. The engine
  borrows the project context and never mutates the process-global one.
  `greenmachine.common.numeric` is on the scoring import allowlist **by
  module**, never as the whole `common` package; a meta-test proves the
  approved module passes while its siblings stay rejected.
- **Scoring-boundary invariant (rev 7):** every applicable component must be
  represented by **exactly one observation state**, counted across
  `present_observations` *and* `missing_observations` together. Two present,
  two missing, one of each, or none are all refused with a typed
  `ScoringInputError` naming the component, the present and missing counts, and
  the measurement ids involved — **before** any scoring or missing-data
  handling runs. This matters for `attack_angle_quality`, whose two
  measurements are mutually exclusive (MODEL_SPEC §9.1) yet can both appear on
  a structurally valid snapshot. Nothing is mutated, discarded, or
  prioritised.
- Engine output is exactly the six §1a items: Total Score, Tier, Component
  Breakdown, Audit Trail, Warnings, Fallbacks.
- The signal-removal amendment across domain, evaluation schema v1,
  configuration, engine, tests, goldens, and documentation (§5).
- `tests/unit/scoring/test_engine.py` — 24 tests over the disclaimed synthetic
  configuration, including a guard asserting the result carries no betting
  classification in any field or serialized byte.
- `tests/architecture/test_scoring_boundaries.py` — purity guards (approved
  imports, no third party, no I/O or non-deterministic stdlib, no clock, no
  randomness, no float in either spelling, no numeric literal beyond the
  additive identity), each with a meta-test proving it bites. `scoring` left
  the placeholder lists in `test_ingestion_boundaries.py` and
  `test_documentation_integrity.py`.
- `config/nonproduction/gm041_engine_synthetic.yaml` and
  `tests/fixtures/evaluations/gm041_engine_snapshots.py`.
- `scripts/generate_gm041_sample_evaluation.py` → `docs/samples/` (§12a).

**Verified:** full suite **3,499 passed / 5 skipped** (Windows platform skips
only) across `PYTHONHASHSEED` 0, 1, and 42; `ruff format --check .`,
`ruff check .`, `mypy --strict src` all clean; **both** evidence bundles
(`prospective_run`, `run_gm040_ohtani`) still replay byte-identically.

**Out of scope (unchanged):** Today's Slate, bullpens, Record Book, betting
classifications of any kind (permanent), dashboard redesign, historical
calibration, persistence wiring, production configuration values, and — per §0
and §11a — all repository cleanup.

### 12a. The sample evaluation

`scripts/generate_gm041_sample_evaluation.py` runs the real engine over the
real archived Ohtani snapshots under the disclaimed synthetic configuration and
writes `docs/samples/gm041_sample_evaluation.{json,md}`. It reads the evidence
bundle and never writes to it, reads no clock, and is byte-identical on rerun
(verified).

Under the synthetic configuration the RECENT_7D profile totals **5.15 (tier
C)** and LONG_TERM_2Y totals **7.1 (tier B)**, each with a 20-entry audit
trail. The four components the GM-020 pipeline cannot yet supply —
`pitch_mix_pressure`, `put_away_pitch_exploitation`, `park`, `weather` — take
`record_missing` zeros with their reason on the record, and the
`attack_angle_quality` fallback provenance is surfaced. **These numbers are
demonstration only and say nothing about the hitter.**

## 12a. CURRENT MILESTONE — GM-041.5 — **COMPLETE, AWAITING REVIEW**

**Branch:** `feature/gm041-5-stabilization-ux-review`, from `origin/main`
`28727fa`.

**Objective:** surface the GM-041 deterministic engine's evaluation in the
existing Streamlit console while stabilizing the experience — without turning
the console into anything that advises.

**Delivered:**

- **Engine Evaluation screen** (sixth hub destination, after Manual Review).
  Renders the six approved outputs — Total Score, Tier, Component Breakdown,
  Audit Trail, Warnings, Fallbacks — for either window profile of an approved
  archived run. Every category and component appears in deterministic order with
  exact Decimal text (never `float`), missing components show their recorded
  reason, the audit trail renders all entries with contiguous sequence numbering,
  and fallback provenance lists every higher-priority ineligible method with its
  reason. A `NotEvaluableGradeResult` renders as a distinct terminal state with
  no total and no tier — never as zero or tier D.
- **Synthetic-configuration disclosure.** Every displayed score runs under
  `config/nonproduction/gm041_engine_synthetic.yaml`. The screen states this at
  the top, beside the total and tier (including as metric help text), and again
  below the result, and shows the version identifier, semantic `config_hash`,
  and source digest.
- **`reporting.load_verified_run`** returning a frozen `VerifiedRun`
  (`dashboard`, `recent_snapshot`, `long_term_snapshot`) from exactly one
  replay-verification pass, each snapshot deserialized once. `__post_init__`
  refuses a swapped profile, a reused snapshot, and snapshots crossed in from a
  different run. `load_dashboard` delegates to it and is unchanged for callers.
- **Configuration relocated byte-for-byte** out of `tests/fixtures/` (§12b).
- **Lazy configuration load.** The file is read only when the Evaluation screen
  opens, so a missing, unreadable, or invalid configuration renders a focused
  *Evaluation unavailable* error — never *Archived run could not be verified* —
  with the typed error category, no partial result, no traceback, no absolute
  path, and every other screen still working.

**How the layering survives.** `streamlit_app.py` is the only place the three
layers meet: `reporting` returns verified domain snapshots, `config` loads the
disclaimed configuration, and the pure `scoring.score_snapshot` combines them.
`reporting` imports neither `scoring` nor `config`, proven by guards.

**Caching.** One `@st.cache_resource` boundary for the verified run, keyed on
run name and resolved directory — the same boundary as before, so replay
verification is never skipped. Scoring itself is pure and cheap and runs on each
rerun, which avoids a second cache whose key could omit something.

**Expected values under the synthetic configuration** (deterministic, asserted):

| Bundle | RECENT_7D | LONG_TERM_2Y |
|---|---|---|
| `prospective_run` (Devers) | `2.9` / D | `4.55` / C |
| `run_gm040_ohtani` (Ohtani) | `5.15` / C | `7.1` / B |

Twenty ordered audit entries per profile. **All synthetic demonstrations.**

**Verified:** 3,665 passed / 5 skipped across hash seeds 0/1/42; all gates
clean; both evidence bundles replay byte-identically; the committed sample JSON
and Markdown are byte-identical at `960a0106…` and `af804228…`.

### 12b. The non-production configuration location

Moved byte-for-byte from `tests/fixtures/config/valid/` to the single canonical
path `config/nonproduction/gm041_engine_synthetic.yaml`, so the deployed
application never reads an executable configuration out of the test tree. **No
second copy exists.** Verified unchanged across the move:

| Property | Value |
|---|---|
| source digest | `51dac8cccfbba66d69a9dd6b744f4f077ecb1a37bdbaf7185242f0c224a5ece5` |
| semantic `config_hash` | `4502a00bc2f44deb9f79cae5f5439f49fe4e9dac3d2c7f169576013a9fc636a4` |
| version identifier | `gm041-engine-synthetic-0` |

The GM-003 location guards now permit `config/nonproduction/` alongside
`tests/fixtures/`, and additionally require every configuration there to
announce itself as synthetic and non-production. `GREENMACHINE_SYNTHETIC_CONFIG`
overrides the path for tests and deployment, mirroring the existing
`GREENMACHINE_EVIDENCE_ROOT`.

### 12c. Standing statements this milestone makes explicit

- Evaluations are now **visible in Streamlit**.
- The configuration behind them is **synthetic and non-production**; no
  production model configuration exists while Q11–Q16 remain open.
- **Live game capture is still command-line only.** The dashboard displays
  already-published evidence bundles and never captures.
- **No automated recommendation or decision output exists**, anywhere.
- The Manual Review worksheet stays separate; nothing automated is written into
  it, and there is no copy-to-worksheet control.

### 12d. Manual Review state, and why parity was not enough (rev 10)

**The defect.** Streamlit discards a widget-owned `session_state` key when its
widget is not rendered on the current run. The worksheet used widget keys as its
**only** storage, so opening any other screen destroyed the reviewer's scores,
rationales, notes, and timestamp — and with them the export bytes.

**Why rev 9 was wrong to leave it.** Rev 9 shipped a test asserting the
evaluation screen behaved *like* Overview and Data Audit, and recorded the loss
as a pre-existing characteristic. That was accurate but insufficient: the Phase B
requirement was that entering the evaluation, changing profile, or navigating
away must not modify any worksheet field or export byte. A parity test documents
the defect instead of guarding the requirement. The parity test is deleted.

**The correction.** Two namespaces with one direction of flow:

| Namespace | Owner | Lifetime |
|---|---|---|
| `review_state::<run>::<field>` | the application | durable; no widget binds it |
| `review_widget::<run>::<field>` | Streamlit | transient; discarded when unrendered |

Widgets hydrate **from** the durable record when the screen renders (only when
the widget key is absent, so a mid-interaction value is never clobbered), and an
`on_change` callback copies the widget value **into** it while the key still
exists. `ManualReview` and both exports are built from the durable record alone —
never from a widget key. Keys are namespaced per run, so each archived run keeps
its own worksheet and gets it back on return. Nothing persists outside session
state; nothing is written to evidence; no clock is read.

`tests/integration/reporting/test_manual_review_persistence.py` proves it
through **real widget interactions**: fill every field, walk the hub, Overview,
Data Audit, and both evaluation profiles, return, and assert every visible value
and both export payloads are unchanged — then switch runs and back to prove
isolation and restoration.

### 12e. Safe failure presentation (rev 10)

**The defect.** `_render_evaluation_unavailable()` printed `failure.message`
directly. A typed configuration failure carries engineer-facing text naming the
absolute path it tried to read, together with raw `OSError` prose — so an
unreadable configuration leaked a filesystem path and a username to the screen.

**The correction.** A deterministic adapter maps the stable `error_type` to one
fixed, user-safe sentence, covering `ConfigParseError`, `ConfigSchemaError`,
`ConfigSemanticError`, `ConfigVersionError`, `ConfigIntegrityError`,
`SourceModifiedError`, `SourceUnavailableError`, `ScoringConfigError`,
`ScoringInputError`, and generic `ScoringError`, with a generic fallback so an
unrecognised category is safe by construction rather than by remembering to add
an entry. The screen shows the category and that sentence — never
`failure.message`, never `failure.context.file_path`, never a traceback. The
typed error object is passed whole and left unmutated.

Tests assert that neither a Windows-style nor a POSIX-style sensitive path, nor
any identifying segment of either, appears anywhere in rendered text. The
Windows path is assembled from parts in the test source, because the release
packaging guard rightly refuses a literal machine-local path in a shipped file.

### 12f. Terminal-branch coverage (rev 10)

Both archived bundles evaluate successfully, so the not-evaluable and
typed-failure branches had no coverage. They are now reached by patching the
public scoring boundary before the app module imports it — a test seam, undone
by `monkeypatch`, with **no production environment switch**.

`NotEvaluableGradeResult` is asserted to render `NOT EVALUABLE` with no Total
Score metric, no Tier metric, and no substituted zero or tier D; every
unavailable required input, its measurement id where present, its missing
reason, and every attempted method and reason; and its audit trail, warnings,
and fallbacks from its carried observations. `ScoringInputError`,
`ScoringConfigError`, and generic `ScoringError` each render *Evaluation
unavailable* with the stable category, no partial result of any kind, no
mislabelling of the archived run as corrupt, and every other screen still usable
afterwards.

### 12g. Archived-run failure safety (rev 11)

§12e made the *Evaluation* failure path safe. The **archived-run** path — the
error shown when a run cannot be verified or loaded — was still unsafe, in two
independent ways.

**Defect 1: the renderer printed `failure.message`.** A path-bearing
`DashboardLoadError` therefore put the whole private filesystem path on the
screen. Same class of defect as §12e, different renderer; fixing one did not fix
the other, which is why the guard below is now stated as a property rather than
as a check on two function names.

**Defect 2: an `OSError` was never converted.** A run directory is ordinary
filesystem state: a file can be unreadable, or can disappear between the moment
`discover_runs` sees the run and the moment a read wants it. Those arrive as
`OSError` subclasses, and `OSError` is **not** a `GreenMachineError`. The
application catches `GreenMachineError` and nothing wider — deliberately, per
ADR-0007 — so a `PermissionError` or a racing `FileNotFoundError` travelled
straight out of the loader and onto the screen as a raw traceback, carrying the
absolute path it failed on. The reporting layer's own `bundle_reader` calls
`Path.read_bytes()` directly, so this was reachable from four places: opening the
bundle, replay verification, the snapshot reads, and the report reads.

**Correction 1 — a safe archived-run presentation adapter.** Analogous to §12e
and now sharing its lookup. One `_safe_wording(failure, table, generic)` helper
holds the fallback rule in a single place, and each surface supplies its own
table:

| Surface | Table | Renderer |
|---|---|---|
| the archived RUN failed to verify or load | `_SAFE_ARCHIVED_RUN_WORDING` | `_render_focused_error` |
| the run verified, its EVALUATION failed | `_SAFE_FAILURE_WORDING` | `_render_evaluation_unavailable` |

The archived-run screen shows *Archived run could not be verified*, the selected
run **name** (a plain directory label the reviewer chose, never its path), the
stable `error_type`, one fixed safe sentence, and the instruction to select
another approved run. It never renders `failure.message`, `context.file_path`,
an exception string, raw `OSError` prose, an absolute path, a username, or a
traceback. The typed error is passed whole and left unmutated.

**Correction 2 — narrow `OSError` → `DashboardLoadError` conversion.**
`load_verified_run` is now a thin boundary around `_build_verified_run`:

```python
try:
    return _build_verified_run(handle)
except GreenMachineError:
    raise
except OSError as failure:
    raise DashboardLoadError(
        f"archived run files for run '{handle.name}' could not be read",
        ErrorContext(subject=handle.name),
    ) from failure
```

One outermost guard covers all four read sites, so a read added inside the loader
later is protected without anyone remembering to wrap it. The guard is
`except OSError`, never `except Exception`; a `GreenMachineError` raised inside
is re-raised **unchanged**, so no typed failure is relabelled by passing through;
the new message carries the run name and no path; the original exception stays on
`__cause__`, so engineering diagnosis loses nothing. Replay behaviour and the
fail-closed integrity checks are untouched — the conversion sits strictly outside
them and alters no verdict.

**Regressions.** `tests/unit/reporting/test_loader_filesystem_failures.py`
injects `PermissionError` and a post-discovery `FileNotFoundError`, both carrying
deliberately sensitive-looking paths, at each of the four read boundaries. It
asserts `DashboardLoadError` rather than the original `OSError`, no absolute path
in the message or the structured context, `__cause__` preserved, no partial
`VerifiedRun`, and — as a control, so the other assertions cannot pass for the
wrong reason — that the same injection seam loads a healthy run normally.

`tests/integration/reporting/test_archived_run_failure_states.py` exercises both
layers through the app: the renderer, by patching the public verified-run
boundary before the app imports it; and the conversion, by making the loader's
own reader raise a real `OSError` so the production path runs end to end. Only
one run is made to fail, so the suite also proves the other approved run stays
usable. Everything is injected rather than depending on filesystem permissions,
so it behaves identically on every platform.

One trap worth recording: the app caches one verification per run in
`st.cache_resource`, and that cache **outlives an `AppTest`**. Without clearing
it around each case, a run already verified by an earlier test in the same
process is served from cache, the injected failure never fires, and the suite
passes in isolation while quietly testing nothing in a full run. The fixture
clears it on the way in and on the way out.

**Anti-regression guard.** `test_no_error_renderer_prints_a_typed_failures_own_message`
is an AST check over `streamlit_app.py`, stated as a property of **every**
function that accepts a `GreenMachineError`: none may read `.message`,
`.context`, or `.args` off it, pass it to `str`/`repr` or a Streamlit call, or
interpolate it directly. A third failure screen added later is covered the day it
is written. Two meta-tests prove the guard catches the exact shape the archived-run
renderer used before this revision, and does not flag the correction.

**One stale sentence.** The hub said *"No live capture. No automated scoring."*
The second half stopped being true when the Engine Evaluation screen began
running the deterministic engine. It now reads *"No live capture. Engine
evaluations use a synthetic, non-production configuration."* — accurate, and
still free of recommendation or decision language.

---

## 13. FUTURE ROADMAP

**Agreed ticket sequence (PO, 2026-07-25).** One ticket is active at a time
(§0); the next is not started until the previous is reviewed and closed.

| Order | Ticket | Scope |
|---|---|---|
| 1 | **GM-041** | Production grading engine (this branch, awaiting review) |
| 2 | **GM-041.5** | Stabilization & UX Review |
| 3 | **GM-042** | Record Book & Performance Analytics |

GM-041.5 is documented here for sequencing only and **must not be started**
while GM-041 is open.

**GM-042 — Record Book & Performance Analytics (APPROVED 2026-07-25).**
The Record Book measures **GreenMachine's historical performance — not
sportsbook market efficiency**. Approved scope:

- Season Summary
- Daily Results
- Unit Tracker
- **Performance Summary** (ROI is one metric inside it, not a section of its
  own)
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
for the Unit Tracker / Performance Summary consistent with §1a (GreenMachine records
the user's own results and the model's calibration — it still never advises).

**Recommended next tickets (unnumbered until the PO assigns them):**
- **Repository cleanup** (§11a): reconcile the divergent histories, decide the
  fate of `main`'s nested `greenmachine/` duplicate, and settle `.gitattributes`
  and `.gitignore` drift. Deliberately excluded from GM-041. This ticket must
  also address the **Windows line-ending corruption of digest-pinned evidence**
  recorded in §9, which should be that ticket's highest-priority item.
- PO resolves Q11-Q14 → the first production model-configuration version
  (data-only ticket) + golden regeneration under the real engine.
- Evaluation persistence wiring, so evaluations are stored and queryable.

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
3. `python -m pytest -q` — expect fully green (3,665 passed as of rev 11, plus
   five Windows platform skips). Any failure is a real regression.
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
engine config (GM-041)
`config/nonproduction/gm041_engine_synthetic.yaml` with snapshot
builders in `tests/fixtures/evaluations/gm041_engine_snapshots.py`; scoring
purity guards `tests/architecture/test_scoring_boundaries.py`; sample
evaluation `docs/samples/gm041_sample_evaluation.{json,md}` generated by
`scripts/generate_gm041_sample_evaluation.py`.

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
python scripts/generate_gm041_sample_evaluation.py   # synthetic sample eval
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
| 11 | 2026-07-25 | this commit, on `feature/gm041-5-stabilization-ux-review` | **GM-041.5 archived-run failure safety** (§12g). Two independent defects on the archived-run error path, both real. (1) **Raw-message disclosure.** `_render_focused_error()` printed `failure.message`, so a path-bearing `DashboardLoadError` rendered the full private filesystem path — the same class of defect §12e fixed for the Evaluation screen, in the other renderer. A safe archived-run presentation adapter now shows the fixed heading, the selected run **name**, the stable `error_type`, and one fixed safe sentence from a nine-category table with a generic fallback; never the message, the context file path, an exception string, raw `OSError` prose, an absolute path, a username, or a traceback. Both adapters now share one `_safe_wording` lookup, so the fallback rule exists in exactly one place. (2) **Uncaught `OSError`.** A `PermissionError` or a racing `FileNotFoundError` from bundle reading, replay verification, a snapshot read, or a report read escaped the loader as a raw traceback, because `OSError` is not a `GreenMachineError` and the app catches nothing wider. `load_verified_run` is now a thin boundary around `_build_verified_run` with a narrow `except OSError` that re-raises any `GreenMachineError` unchanged, carries the run name and no path, and preserves `__cause__`; `except Exception` is not used and no integrity verdict changes. New regressions: a loader unit suite injecting both `OSError` kinds at all four read boundaries with sensitive-looking paths (plus a control proving the seam still loads a healthy run), and an AppTest suite driving both the renderer and the real end-to-end conversion while proving a second approved run stays usable. An AST anti-regression guard now forbids **any** function taking a `GreenMachineError` from rendering it raw, with meta-tests proving the guard catches the exact prior shape. The hub's stale *No automated scoring* claim is corrected. Verified: 3,665 passed / 5 skipped across hash seeds 0/1/42, all gates clean, both bundles replay byte-identically, sample JSON and Markdown byte-identical at `960a0106…` and `af804228…`, configuration source digest and semantic hash unchanged, the four synthetic scores unchanged, and evidence and goldens byte-identical to `origin/main`. No frozen contract changed. |
| 10 | 2026-07-25 | this commit, on `feature/gm041-5-stabilization-ux-review` | **GM-041.5 review corrections.** (1) **Manual Review state loss fixed** (§12d). Streamlit discards widget-owned session keys when their widgets are not rendered, and the worksheet used widget keys as its only storage — so navigating anywhere destroyed the reviewer's scores, rationales, notes, timestamp, and export bytes. Rev 9 shipped a *parity* test asserting the evaluation screen behaved like Overview, which documented the defect instead of guarding the requirement; that test is deleted. The correction introduces a durable `review_state::<run>::<field>` namespace that no widget owns, hydrated into transient `review_widget::` keys on render and written back by `on_change`, with `ManualReview` and both exports built from the durable record alone and every run namespaced separately. Fourteen new AppTest cases drive **real widget interactions**, walk the hub plus Overview, Data Audit, and both evaluation profiles, and assert every visible value and both export payloads are byte-identical on return, plus per-run isolation and restoration. (2) **Absolute-path disclosure fixed** (§12e). The failure renderer printed `failure.message`, which for a configuration failure names the absolute path it tried to read. A deterministic adapter now maps the stable `error_type` to one fixed user-safe sentence across ten categories with a safe generic fallback; the screen never renders the message, the context file path, or a traceback, and the typed error is left unmutated. Tests assert neither a Windows-style nor a POSIX-style sensitive path nor any identifying segment appears in rendered text, including the unreadable-configuration case, injected rather than depending on filesystem permissions so it stays cross-platform. (3) **Terminal branches covered** (§12f): `NotEvaluableGradeResult` and `ScoringInputError`/`ScoringConfigError`/`ScoringError` are exercised by patching the public scoring boundary before the app imports it — a test seam, not a production switch. (4) Page title and sidebar caption no longer describe the console as manual-review-only; `VerifiedRun` and `load_verified_run` added to `dashboard_loader.__all__`. Verified: 3,623 passed / 5 skipped across hash seeds 0/1/42, all gates clean, both evidence bundles replay byte-identically, sample JSON and Markdown byte-identical at `960a0106…` and `af804228…`, configuration identity unchanged, the four synthetic scores unchanged, and evidence and goldens byte-identical to `origin/main`. No frozen contract changed. |
| 9 | 2026-07-25 | this commit, on `feature/gm041-5-stabilization-ux-review` | **GM-041.5 Stabilization & UX Review.** GM-041 was approved and merged (`origin/main` `28727fa`); this branch starts there. Added the **Engine Evaluation** screen as the sixth hub destination, rendering the GM-041 engine's six outputs — Total Score, Tier, Component Breakdown, Audit Trail, Warnings, Fallbacks — for either window profile of an approved archived run, with evaluated and not-evaluable rendering as structurally distinct states (a not-evaluable result never becomes zero or tier D). Added `reporting.load_verified_run` returning a frozen `VerifiedRun` (view models plus both frozen snapshots) from exactly one replay pass with each snapshot deserialized once, validating profile placement, distinct identities, and identity coherence with the dashboard header; `load_dashboard` delegates to it unchanged. This is what keeps `reporting` free of `scoring` and `config` imports while the composition root scores — proven by new architecture guards. Relocated the disclaimed synthetic configuration **byte-for-byte** to `config/nonproduction/gm041_engine_synthetic.yaml` with no second copy, verified identical by source digest, semantic `config_hash`, and version identifier (§12b); the GM-003 location guards now permit that directory and additionally require every configuration there to announce itself non-production. Configuration is loaded lazily on entering the screen, so a missing or invalid file renders a focused *Evaluation unavailable* error with the typed category — never *Archived run could not be verified* — with no partial result, no traceback, no absolute path, and every other screen still working. Documentation updated across README, `STREAMLIT_PROTOTYPE.md`, and the CHANGELOG to state that evaluations are visible, the configuration is synthetic and non-production, live capture remains command-line only, the dashboard displays already-published bundles, no production configuration exists while Q11–Q16 are open, and no automated recommendation or decision output exists. Recorded a pre-existing UX finding in §12d (Streamlit resets unrendered widget state, so worksheet entries do not survive navigation through *any* screen) and asserted parity rather than pinning a guarantee the app never made. Verified: 3,581 passed / 5 skipped across hash seeds 0/1/42, all gates clean, both evidence bundles replay byte-identically, committed sample JSON and Markdown byte-identical at `960a0106…` and `af804228…`. No frozen contract changed. |
| 8 | 2026-07-25 | this commit, on `feature/gm041-production-grading-engine-mainline` | **GM-041 Decimal-context determinism correction.** Both scoring aggregation paths summed with a bare `total = total + points`, which evaluates under the **caller's mutable global Decimal context** rather than the project-local one — a direct ADR-0002 violation. Reproduced before fixing on the same synthetic snapshot and configuration: normal context `11.55` / tier S; precision 1 with `ROUND_DOWN` → `7` / tier **B**; precision 2 with `ROUND_UP` → `12` / tier S; precision 3 with `ROUND_FLOOR` → `11.5` / tier S. A tier moved from S to B on identical inputs. Both paths now sum through `greenmachine.common.numeric.add`, which runs under the project context (precision 28, ROUND_HALF_EVEN); the process-global context is never modified or replaced. The scoring architecture allowlist gained `greenmachine.common.numeric` **by module**, deliberately not `greenmachine.common` as a package, with meta-tests proving the approved module passes while the clock, serialization, and identifier siblings stay rejected and that the allowlist entry is module-scoped. Fifteen new tests: the normal result pinned at exactly `11.55` / S; three hostile contexts each compared against the baseline across component scores, category scores, total, tier, warnings, fallbacks, the ordered audit derivation, whole-record equality, and serialized bytes; the same three pinned by value; and two proving `score_snapshot()` leaves the caller's precision, rounding, and traps untouched — including when the caller's context is already unusual. Also corrected the stale `Present-observation resolution` heading in `engine.py` to describe resolution across both collections. **No serialized output changed**: the goldens are untouched and the committed sample files remain byte-identical at `960a0106…` (JSON) and `af804228…` (Markdown). Verified at this commit: 3,499 passed / 5 skipped across hash seeds 0/1/42, all gates clean, both evidence bundles replay byte-identically from a clean clone, sample generation byte-identical across two external-directory runs. Frozen domain contracts, evaluation schema v1, evidence bundles, Q11–Q16, `.gitattributes`, and the nested noncanonical tree are all untouched; the Windows line-ending defect (§9) remains deferred. |
| 7 | 2026-07-25 | this commit, on `feature/gm041-production-grading-engine-mainline` | **GM-041 scoring-ambiguity correction (final independent review).** The engine rejected two PRESENT observations for one component but not two MISSING ones, nor one present plus one missing: `_missing_for_component()` returned the first match and the present path took precedence without consulting the missing collection. Reproduced before fixing — a snapshot carrying a present `ideal_attack_angle_pct` **and** a missing `attack_angle_threshold_proxy` scored 11.55 / tier S while the missing record was silently unscored yet still travelled on the returned result, with only one attack-angle entry in the audit derivation. That breaks both the fail-closed rule and the complete-audit requirement. Fixed by replacing `_present_for_component`/`_missing_for_component` with a single `_resolve_observation()` that collects matches across **both** collections and requires exactly one total, raising a typed `ScoringInputError` naming the component id, the present count, the missing count, and the measurement ids represented. The pre-existing zero-match refusal is folded into the same resolver, so the guard runs before scoring or missing-data handling and nothing is selected, prioritised, mutated, or discarded. Enforced at the scoring boundary only — the frozen domain contracts are unchanged. Nine new engine tests cover two present variants, two missing variants, both present-plus-missing orientations, order reversal of two missing records (proving first-match independence), single present ideal and single present proxy still scoring through their own measurement-specific buckets (ideal threshold 50, proxy threshold 60), a single missing record still following its configured missing-data policy, and the absence of any partial result or observation mutation on refusal. Engine module documentation states the invariant. The committed sample evaluation is byte-unchanged, as expected — the correction does not alter any valid input. Verified at this commit: 3,484 passed / 5 skipped across hash seeds 0/1/42, all gates clean, both evidence bundles replay byte-identically from a clean clone. `.gitattributes` untouched; the Windows line-ending defect (§9) remains deferred. |
| 6 | 2026-07-25 | this commit, on `feature/gm041-production-grading-engine-mainline` | **GM-041 documentation correction.** The canonical root `README.md` was stale in every current-facing claim and is rewritten: it had said the grading engine is not implemented, that GreenMachine assigns "a grade and a signal", that `STRONG_BET`/`LEAN`/`PASS`/`AVOID` are outputs, that validation may alter a grade or signal, that the audit output includes "the signal rule that fired", that `scoring` is placeholder-only, that Phase 3 includes a signal engine, and that model-configuration changes include signals. It now states that GM-041 implements the deterministic production grading engine; that no production model configuration is approved and every executable configuration and sample score is synthetic; that the output is exactly Total Score, Tier, Component Breakdown, Audit Trail, Warnings, and Fallbacks; that GreenMachine produces no automated recommendation or decision output and separates evaluation from decision-making; that `features` and `cli` remain placeholders while `scoring` is implemented; that the Streamlit prototype does not yet render the production engine's evaluation, which belongs to GM-041.5; and the sequence GM-041 → GM-041.5 → GM-042. Betting-oriented wording such as "potential edges" was replaced with neutral research language. §1 of this handoff dropped its stale future tense ("is being implemented", "will carry"). §11a gained a binding **"Which tree is canonical"** statement: the repository-root project is the current canonical implementation, and the nested `greenmachine/` tree is a preserved, noncanonical duplicate holding stale historical content that must not be used for development, review, deployment decisions, or product-status interpretation — removing it stays a separate repository-cleanup ticket. A new `tests/unit/docs/test_readme_currency.py` protects the root README against regression on each retired claim and asserts the separation-of-concerns statements, scoped to the canonical README only so historical documents and the preserved duplicate are untouched. No source behavior changed; `.gitattributes` was not modified and the Windows evidence line-ending defect (§9) remains deferred. Verified at this commit: 3,475 passed / 5 skipped across hash seeds 0/1/42, all gates clean, both evidence bundles replay byte-identically from a clean clone. |
| 5 | 2026-07-25 | this commit, on `feature/gm041-production-grading-engine-mainline` | **GM-041 independent-review corrections.** (1) **Snapshot/configuration coherence** is now enforced before scoring: a present observation must match the configured `sample_type` and `minimum_sample_required`, and a missing observation must match the configured `sample_type`, or a typed `ScoringInputError` naming the component, both values, and the field fails the evaluation closed. The snapshot's `SampleStatus` was computed against the minimum stored on the observation, so accepting a different configured minimum would have made warnings and audit text disagree with the snapshot; the engine refuses rather than recalculating, mutating, or replacing snapshot metadata. Six focused tests cover both mismatch directions, both sample-type mismatches, the coherent path, and warning derivation after the checks. (2) **Retired betting terminology removed from current runtime and user-facing strings** in `streamlit_app.py`, `ingestion/orchestration.py`, the sample generator, and `STREAMLIT_PROTOTYPE.md`, replaced with neutral wording ("no automated recommendation", "no decision output", "evaluation only"); generic non-betting uses of "signal" (the strict-JSON parser's internal signal) are deliberately kept. (3) **Handoff corrected**: §3 no longer claims `EvaluatedGradeResult` requires `signal`/`signal_reason` or that `GreenMachineConfig` carries typed signal rules, and now describes the delivered contracts including fallback provenance reaching the engine through the observations; §13 renames ROI Summary to **Performance Summary** with ROI as one metric inside it, and records the agreed sequence GM-041 → GM-041.5 (Stabilization & UX Review) → GM-042. (4) **Sample outputs reconciled**: an evaluated profile now carries exactly the six approved keys, `evaluation_status` is no longer emitted as a seventh, and the four top-level fields are documented as sample provenance metadata; `EvaluationStatus` and `NotEvaluableGradeResult` are unchanged in the domain. (5) **External `--output` fixed**: the generator wrote both files and then crashed on `Path.relative_to`; display paths are now repository-relative when possible and resolved-absolute otherwise. (6) Recorded, and deliberately **not** fixed, the **Windows line-ending corruption of digest-pinned evidence** (§9). Investigating the reviewer's `git archive` finding showed the defect is broader: `main`'s `.gitattributes` `* text=auto` plus Windows' native `core.eol` means *any* default Windows checkout CRLF-converts the pinned evidence bytes, so a fresh clone fails replay with `SamplePolicyError` (measured: `d957b9eb…` versus the pinned `461d04a3…`). The committed objects are correct and replay passes from any LF checkout, verified from a clean clone of the bundle with `core.eol=lf`. The durable fix is an `-text` attribute for `evidence/**`, which edits `.gitattributes` — out of scope for GM-041 by PO ruling — so it is assigned to repository cleanup as that ticket's highest-priority item. Review artifacts ship as a git bundle and `changed_files/` uses `git cat-file blob`. Verified: 3,448 passed / 5 skipped across hash seeds 0/1/42, all gates clean, both evidence bundles replay byte-identically from a clean clone of the bundle. |
| 4 | 2026-07-25 | this commit, on `feature/gm041-production-grading-engine-mainline` | **GM-041 COMPLETE, awaiting review.** Two Product Owner rulings implemented. (1) **Repository history**: the previous branch shared no ancestor with `origin/main`, so a PR from it proposed 279 deletions of `main`'s nested duplicate project tree. Resolved by the approved clean graft — a new branch from `origin/main` replaying only the intentional GM-041 delta, preserving `.gitattributes`, the nested `greenmachine/` directory, and the deployment structure, and excluding `.claude/settings.local.json` and incidental baseline drift. The old branch stays as an archival reference and is not rewritten. Recorded in the new §11a. (2) **Betting-classification removal**: `Signal`, `signal`, `signal_reason`, the configuration rule family, and the `strong_category_fraction` were removed from the domain contract, evaluation record schema v1 (amended in place, no v2), the configuration schema and §19 validation, the loader union table, the engine, the fixtures, and the tests; goldens regenerated through `scripts/update_goldens.py`; MODEL_SPEC §16 rewritten as an evaluation-output section with a historical note; Q27 marked SUPERSEDED and Q3/Q26 superseded in part; GLOSSARY, ARCHITECTURE (risk R10 retired), ENGINEERING_GUIDELINES, PHILOSOPHY, ADR-0002, ADR-0004, and STREAMLIT_PROTOTYPE reconciled. Added the permanent principle to `PHILOSOPHY.md` §1.1 and the new §0 standing process rules here, including the **one-ticket-at-a-time** rule. Added `scripts/generate_gm041_sample_evaluation.py` and the labeled synthetic Ohtani sample evaluation in `docs/samples/` (§12a), byte-identical on rerun. Verified: 3,433 passed / 5 skipped across hash seeds 0/1/42, all gates clean, both evidence bundles still replay byte-identically. |
| 3 | 2026-07-25 | `598ed65` on `feature/gm041-production-grading-engine` (archival) | **GM-041 RESUMED.** The rev-2 working tree was committed verbatim (`4542b22`) so the paused state stays inspectable, then corrected (`17ed58f`). Both rev-2 failures were diagnosed as **test-side expectation defects, not engine defects** (a lower-case `MissingReason` assertion; a fuzzy-policy test whose config the §19 loader rejects first, making the engine guard unreachable — now split into the loader refusal and the engine refusal). Rev 2 §14 understated the failure count as two: the two placeholder guards were failing as well, because `scoring` had gained behavior. Those guards are retired — `scoring` leaves the placeholder lists in `test_ingestion_boundaries.py` and `test_documentation_integrity.py`, replaced by the new `tests/architecture/test_scoring_boundaries.py`, which enforces the §12 purity criteria structurally (approved imports, no third party, no I/O, no clock, no randomness, no float, no embedded numeric threshold) with meta-tests. Gate fixes on the WIP: `_OPERATORS` annotated (four `no-any-return` errors clear under `mypy --strict`), one en dash removed for RUF002, `ruff format` applied. §5 now carries the **measured** blast radius of the pending signal-removal amendment (docs, domain contract, evaluation schema v1 with the explicit v1-vs-v2 question, config schema and `config_hash`, goldens; ingestion/replay/evidence/UI confirmed unaffected) and scopes the strong-category sub-question with a recommendation. §12 rewritten as the current in-progress state; §2/§3/§7/§9/§14/§15 refreshed against the repository. Verified: 3504 passed / 5 skipped, all gates clean, both evidence bundles replay byte-identically. |
| 2 | 2026-07-25 | `3ac1c7d`, same branch | **GM-041 officially PAUSED** with its exact in-progress state recorded (§12: committed engine/errors modules, uncommitted `__init__` diff, three untracked test/fixture files, 20/22 tests passing with the two named failures, resumption order). Recorded the approved product-identity rulings (§1a): GreenMachine is an evaluation platform, not a betting advisor; betting classifications (Lean/Avoid/Pass/Strong-Bet) removed from all future scope; engine outputs restricted to Total Score, Tier, Component Breakdown, Audit Trail, Warnings, Fallbacks; the user makes the decision. §5 rewritten accordingly with the required MODEL_SPEC §16 / `EvaluatedGradeResult` / config signal-rule reconciliation steps and the open strong-category question. §8 reframed betting items as permanently out. §13 replaced with the approved **GM-042 Record Book & Performance Analytics** scope (Season Summary, Daily Results, Unit Tracker, ROI Summary, Performance Analytics, Model Calibration, Historical Archive, Revision History; explicitly excluding Average Odds, CLV, Average Confidence Tier — the Record Book measures GreenMachine's historical performance, not sportsbook market efficiency) plus unnumbered follow-ons. Appendix fixture paths corrected; quick-start updated for the pause. |
