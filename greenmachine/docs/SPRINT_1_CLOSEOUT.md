# Sprint 1 — Closeout and Acceptance Record

**Closed:** 2026-07-24 (GM-010)
**Specification version:** v6.3 — Foundation Clarifications · **Code version:** 0.1.0
**Evaluation record schema version:** 1 · **Model configuration version:** none published

---

## Sprint objective

Build the deterministic, configuration-driven skeleton the grading engine will plug into — and
prove the determinism and boundary guarantees with automated tests before runtime grading
logic or a production model configuration exists (the recorded closeout interpretation of the
original sprint-goal wording). That objective is met: a CI-enforced suite fails if the system
becomes non-deterministic, if an import boundary is breached, or if a value from one window
profile could reach the other. The exact boundary at closeout: **no production
model-configuration version has been published**, no runtime scoring engine exists, and **no
baseball threshold, allocation, or scoring behavior is implemented in `src/`**. `MODEL_SPEC.md`
*does* contain approved specification rules and defaults — the 15% qualifying pitch-usage
default, the grade boundaries, the signal conditions, the 5°–20° Ideal Attack Angle
definition, the 75% strong-category rule — which engineering implements but never invents;
the synthetic test configuration is not a production model configuration.

## Approved archive identities

| Archive | SHA-256 |
|---|---|
| `greenmachine-gm-008-r3.zip` (cumulative production repository) | `eaad3ec4fcf1e12d89924c45ff663d993a4e382c86234335997c93413ccb7ea0` |
| `greenmachine-savant-feasibility-spike-r2.zip` (isolated real-data experiment) | `91c980ee8b9dd28d20c239581033b458e8b467d36cd4ed49c1612a876c462c1c` |

GM-010 changes documentation and repository-contract tests only; `src/` and the nine committed
golden JSON files are byte-identical to `greenmachine-gm-008-r3.zip`.

## Completed tickets

| Ticket | Delivers | Accepted as |
|---|---|---|
| GM-001 | repository scaffolding, tooling, CI, docs skeleton | initial delivery |
| GM-002 | immutable domain vocabulary | r2 |
| GM-003 | configuration schema, strict loader, §19 invariants | r3 |
| GM-004 | semantic `config_hash`, versioning, use seal | r1 |
| GM-005 | determinism primitives (numeric, clock, serialization, ids) | r2 |
| GM-006 | `InputSnapshot`, `GradeResult` variants, `EvaluationEnvelope`, `OutcomeRecord`, canonical records | r2 |
| GM-007 | append-only persistence ports, in-memory adapters, `OutcomeRevision`, contract suite | r1 |
| GM-008 | golden-master and property-test framework | r3 |
| GM-009 | error taxonomy rooted at `GreenMachineError`, structured logging | r2 |
| GM-010 | Sprint 1 closeout and repository reconciliation | this record |
| Savant feasibility spike | isolated real-data experiment (separate archive, never merged) | r2 |

## Accepted ADRs

All eight are **Accepted**: 0001 record architecture decisions · 0002 numeric and
bucket-boundary policy · 0003 snapshot and point-in-time policy · 0004 GradeResult vs.
EvaluationEnvelope · 0005 window-profile architecture · 0006 outcomes separate from
evaluations · 0007 error handling and structured logging · 0008 golden testing strategy.
The golden-testing ADR is **0008** by Product Owner ruling (the sprint plan's original 0005
filename predated ADR-0005's assignment to the window-profile architecture; ADR numbers are
never reused).

## Implemented contract boundaries

- **Domain** imports nothing internal (single recorded exception: `domain/errors.py` →
  `common.errors`); no I/O, clock, randomness, or third-party modelling types; all vocabulary
  frozen, hashable, and construction-validated.
- **Numerics** (ADR-0002): Decimal only, constructed from strings/integers under a
  project-local context (precision 28, `ROUND_HALF_EVEN`); half-open scoring buckets and the
  inclusive Savant attack-angle predicate live in deliberately separate helpers.
- **Configuration**: strict typed loading, no escaping dictionaries, every MODEL_SPEC §19
  invariant a load failure; semantic `config_hash` invariant under formatting and changed by
  any semantic edit; no write path to configuration from application code.
- **Records** (ADRs 0003/0004): one `InputSnapshot` = one `WindowProfile`, content-derived
  `snapshot_id`/`input_hash` behind a module-private construction authority, identity verified
  on decode; pure `EvaluatedGradeResult`/`NotEvaluableGradeResult` (type-level status
  impossibility) separated from the orchestration `EvaluationEnvelope`; canonical
  serialization under record schema version 1.
- **Profiles** (ADR-0005): allocations profile-invariant; buckets and minimums profile- and
  measurement-specific; cross-window substitution structurally unexpressed.
- **Persistence** (ADR-0006): three append-only repositories (`append`/`get`/`query` only),
  typed conflicts, linear supersession, chain-hashed `OutcomeRevision`, deterministic query
  ordering, reusable adapter contract suite; outcomes structurally separate from evaluations.
- **Errors/logging** (ADR-0007): typed hierarchy with structured context; no broad exception
  handling (architecture-enforced); logging observational only.
- **Test harness** (ADR-0008): profile-aware golden cases as canonical records; injected
  `GoldenScorer` boundary (stub only — no scoring logic); explicit targeted regeneration as
  the sole golden write path; fixed Hypothesis seed 20260724; suite-wide network blocking in
  the parent session and, via an explicit guarded bootstrap, in every test-spawned Python
  child; case-root confinement; deterministic execution-failure rendering.

## Test and quality gates (verified at closeout, repository and clean extraction)

| Gate | Result |
|---|---|
| `pytest -q` (working tree) | at GM-010 review: **2,818 passed, 4 skipped** · after the GM-010-r1 precision corrections (12 documentation regressions added): **2,830 passed, 4 skipped** |
| `pytest -q` (clean archive extraction) | at GM-010 review: **2,817 passed, 4 skipped** · after GM-010-r1: **2,829 passed, 4 skipped** |
| `pytest -q tests/unit/docs` | at GM-010 review: working tree **46** · clean archive **45** — after GM-010-r1: working tree **58** · clean archive **57** |
| Skips (both environments) | the 3 platform-gated directory-symlink tests and `sendmsg` (unavailable on Windows), each with platform-independent counterparts |
| `ruff format --check .` / `ruff check .` | clean |
| `mypy --strict src/` | no issues in 41 source files |
| PYTHONHASHSEED 0 / 1 / 7 / 123 / 424242 (golden + property suites) | identical results per seed |
| Determinism | byte-identical canonical serialization across processes; golden and hash-stability probes run in fresh guarded interpreters |
| Hypothesis | profile `greenmachine-ci`, fixed seed 20260724, `database=None`, `deadline=None`, `max_examples=50` |

**The one-test difference, precisely:** `GREENMACHINE_HANDOFF.md` is a permitted
working-tree-only file that is excluded from release archives by convention. The Markdown
link-resolution test parametrizes over the Markdown files present in the tree it runs in, so
the working tree carries exactly one additional link-resolution case (46 vs. 45 in the focused
documentation suite; 2,818 vs. 2,817 overall). No test requires the handoff to exist, and both
environments pass every collected test.

## Intentionally deferred production capabilities (future work, not Sprint 1)

Production Savant ingestion · MLB schedule/game/probable-pitcher ingestion · prospective
raw-response archiving · schema-drift detection · retry and rate-limit behavior · weather
forecast ingestion · park-factor source · scoring-engine implementation · feature assembly ·
daily orchestration · dashboard integration · **Overall Pull%** as a report/context metric ·
**Pitchers to Target** · **Bullpens to Target**.

Bullpen backlog detail (recorded Product Owner scope): displayed metrics HR/9, ERA, Barrel%
Allowed; tags *Weak vs LHB*, *Weak vs RHB*, *Overworked Bullpen*, *HR-Prone Bullpen*; the
consolidation rule *Overworked Bullpen + HR-Prone Bullpen → Bullpen to Target*; reliever
availability estimated transparently from recent usage, never claimed as certain without an
official source.

### Approved post-Sprint-1 sequence

1. Sprint 1 / GM-010 closeout *(this record)*
2. Provider architecture and baseball/data-semantics review — Gemini architecture review,
   Grok baseball/provider-semantics review, and Product Owner rulings (the provider decisions
   listed under unresolved decisions below)
3. **GM-020 — thin production ingestion vertical slice**, the next implementation milestone.
   Current planning target: one selected slate, one game, one hitter, the expected pitcher;
   prospectively archived MLB/Savant raw responses; normalized provider-neutral records;
   separate `RECENT_7D` and `LONG_TERM_2Y` snapshots; deterministic offline replay. The final
   GM-020 ticket is frozen only after the reviews and rulings in step 2.
4. First real `RECENT_7D` and `LONG_TERM_2Y` snapshots
5. Grading-core implementation and real-data integration
6. Full-slate expansion

## Verified Savant-spike conclusions (evidence only; spike stays outside production source)

- Direct Baseball Savant CSV (`statcast_search/csv`) is the leading production event-data
  candidate (119 columns including event-level bat tracking; inclusive date bounds; permissive
  robots). The MLB Stats API is the leading schedule/game-identity/probable-pitcher candidate.
- pybaseball 2.2.7 is exploration-grade, not production-grade (hidden game-type template, no
  timeout/retry policy, DataFrame re-serialization); after scope matching, reconciled event
  sets matched exactly.
- Unfiltered Savant requests return all game types; production must filter `game_type`
  explicitly.
- Real provider data maps into the frozen `InputSnapshot` contract through the unmodified
  factory — no GM-006/GM-007 contract blocker was found; profile-specific snapshots share a
  content-derived `SourceCaptureId` with byte-identical regeneration across environments.
- All spike results are retrospective reconstructions; production requires prospective
  raw-response archiving (the spike manifest is the working prototype of that contract).
- Weather stays missing unless a genuine grading-time forecast is captured; bat-tracking
  fields exist for 2024+ with roughly 37–42% swing-conditional coverage; official barrel is
  `launch_speed_angle == 6`; pull classification must use row-level `stand`.

## Unresolved Product Owner decisions (carried forward, none resolved by GM-010)

1. Final Pull Air denominator.
2. Whether Overall Pull% eventually becomes a modifier or stays informational.
3. Production game-type policy (All-Star/exhibition inclusion).
4. Metric-specific minimum sample thresholds (Q14).
5. Official-versus-derived metric precedence.
6. Historical bat-tracking coverage policy (2024+ fields vs. two-year windows).
7. Opener and bulk-pitcher treatment.
8. Prospective raw-source retention policy.
9. Park-factor source (Q17).
10. Weather forecast source (candidates: Open-Meteo, NWS; Ballpark Pal only via officially
    supported API access; no Doink Sports outreach).
11. Official Ideal Attack Angle acquisition route (Q19).
12. Whether a derivation-pending missing reason is needed in the vocabulary.
13. Production configuration values remain open per `docs/OPEN_QUESTIONS.md` (Q11–Q16 block
    the first model configuration version).
14. Whether a follow-up ticket should authorize `CONTRIBUTING.md` (excluded from GM-010's
    permitted change set; the Definition of Done and review checklist live in
    `docs/ENGINEERING_GUIDELINES.md` §12–13).
15. Release versioning: the original Sprint 1 target of 0.2.0 was not applied during the
    documentation-only GM-010 closeout and the code remained 0.1.0 at that closeout; when and
    how the next code version is assigned requires an explicit ruling in the future ticket
    that changes code — no version was pre-assigned to GM-020 or any other ticket at closeout.
    (Resolved after this closeout: the GM-020 ticket carried exactly such a ruling, moving the
    code to 0.2.0.)

No defaults were chosen silently; every item above requires an explicit ruling delivered
through ticket text.
