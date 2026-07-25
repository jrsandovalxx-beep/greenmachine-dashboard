# GreenMachine — Session Handoff (source of truth for a fresh Claude Code session)

Written 2026-07-24, after GM-007-r1 and the Savant feasibility spike r2 were
both approved and frozen. Verified against the working tree on that date; the
tree is byte-identical to `greenmachine-gm-007-r1.zip` (this handoff is the one
post-freeze, documentation-only addition and is not inside that archive).
GM-008 has not started. GM-020 production ingestion has not started.

---

## 1. Product objective and zero-black-box policy

GreenMachine is a deterministic MLB home-run grading platform. One evaluation
unit is: **one batter, one game, versus the expected starting pitcher, one
frozen input snapshot, one window profile**. Output: an internal Decimal score
0–12, letter grade S/A/B/C/D, terminal status `EVALUATED | NOT_EVALUABLE`, and
a betting signal resolved in strict priority order.

Zero-black-box: every number derives from explicit, versioned, configured rules
— no ML model, no opaque weights. A stored evaluation must be able to prove,
years later, exactly which inputs and which rules produced it (content-hashed
snapshots + semantic config hash + complete ordered audit derivation). The
value proposition is trustworthy explanation; anything unexplainable is a
defect.

## 2. Frozen scoring model (specification v6.3)

- **Aggregation (Q1):** metric score = highest qualifying bucket's points;
  category = sum of metrics; total = sum of categories (max 12). No averaging,
  rescaling, or dynamic normalization. Spec allocation: Power Profile 3,
  Pitcher Matchup 3, Form 2, Pull Power 2, Environment 2 (Park 1 / Weather 1).
  Grade cutoffs spec 4/6/8/10 with S = `[10, 12]` terminal-closed. All
  thresholds live in configuration, never code.
- **Eleven components**; `attack_angle_quality` is the only one with two
  mutually exclusive measurements (`ideal_attack_angle_pct`,
  `attack_angle_threshold_proxy`); every other component uses
  `measurement_id=None`. Retired Form metrics (chase rate, zone-contact %,
  whiff rate) must never return as scored components.
- **Signals (Q3/Q27):** AVOID → STRONG_BET → LEAN → PASS, first match wins;
  AVOID may override a high grade and carries a stable override reason code;
  the fallback is exactly one unconditional `always` PASS rule.
- **Profiles (ADR-0005, Q25):** `RECENT_7D` and `LONG_TERM_2Y`, never blended,
  never substituted; allocations are profile-invariant; buckets and sample
  minimums may differ per profile.
- **Numerics (ADR-0002):** Decimal only (precision 28, ROUND_HALF_EVEN,
  project-local context); Decimals from strings/ints, never floats; scoring
  buckets half-open `[lower, upper)` with terminal closed; externally defined
  inclusive ranges (Savant Ideal Attack Angle **[5, 20] inclusive**) use a
  deliberately separate helper.
- **Samples (§8):** zero, insufficient, and missing are distinct; insufficient
  is present and scored with an advisory warning — never converted to missing.
- **Point-in-time (ADR-0003):** nothing dated/retrieved after `as_of` enters an
  evaluation; weather is grading-time forecast only; acquisition fallback is
  allowed, cross-window fallback never; strong category = category score ≥
  `max × 0.75` in Decimal, no rounding (Q26); 15% pitch-usage put-away screen
  (Q28); canonical provider `game_id` and official `slate_date` (Q30).

## 3. Completed and frozen tickets

| Ticket | Delivers | Final pass |
|---|---|---|
| GM-001 | scaffold, docs, ADR skeleton (pre-session) | — |
| GM-002 | domain vocabulary (enums, values, entities, observations, results) | r2 |
| GM-005 | determinism primitives (numeric, clock, canonical serialization, ids) | r2 |
| GM-009 | error taxonomy rooted at `GreenMachineError` + structured logging | r2 |
| GM-003 | config schema + strict YAML loader + §19 semantic invariants | r3 |
| GM-004 | semantic `config_hash`, versioned configs, registry, use seal | r1 |
| GM-006 | InputSnapshot, GradeResult variants, EvaluationEnvelope, OutcomeRecord, canonical record serialization, `Sha256Digest` | r2 |
| GM-007 | append-only persistence ports, in-memory adapters, `OutcomeRevision`, reusable contract suite | r1 |
| Spike | isolated Savant real-data feasibility experiment | r2 |

## 4. Latest approved archive identities (both approved and frozen)

- **Production repository:** `greenmachine-gm-007-r1.zip` — SHA-256
  `2634ccddc73719ec268c6e57c8c07853816813c488191a632af03b98691f5690`
  (139 files, 357,190 bytes; cumulative — contains every frozen ticket).
- **Real-data experiment:** `greenmachine-savant-feasibility-spike-r2.zip` —
  SHA-256
  `91c980ee8b9dd28d20c239581033b458e8b467d36cd4ed49c1612a876c462c1c`
  (58 files, 2,283,243 bytes; isolated workspace, never merged into
  production).

Earlier per-ticket archives are superseded by the cumulative production
archive and are retained on disk for audit only.

## 5. Current repository and test status (verified 2026-07-24)

- Working tree byte-identical to `greenmachine-gm-007-r1.zip`; only this
  handoff file is additional. No git repository exists.
- `pytest -q`: **2296 passed**. `ruff check` / `ruff format --check`: clean.
  `mypy --strict src/`: no issues in 41 source files.
- Suite sizes (each verified live): domain 595 · evaluation 53 · config 393 ·
  persistence 56 · repository contract (integration) 68 · architecture 727.
- Package version `0.1.0`; Python floor `>=3.11` (validated on 3.13/3.14);
  runtime deps PyYAML + pydantic v2 (config package only).
- Populated packages: `domain`, `common`, `config`, `evaluation`,
  `persistence`. Docstring-only placeholders: `scoring`, `features`,
  `ingestion`, `reporting`, `cli`.

## 6. Architecture rulings that must not be reopened

All seven ADRs are **Accepted**. Binding rulings:

1. **ADR-0002** Decimal policy; separate inclusive-range helper.
2. **ADR-0003** the frozen profile-specific `InputSnapshot` is the unit of
   reproducibility; source eligibility outranks priority; backtests read
   archives, never re-query.
3. **ADR-0004** `GradeResult` is pure (no time/id/version/hash/outcome);
   `EvaluationEnvelope` carries orchestration metadata; `evaluated_at` is
   injected, never read from a clock in the core.
4. **ADR-0005** one snapshot = one profile; profile carried, never inferred;
   profile-invariant allocations.
5. **ADR-0006 + frozen PO ruling:** outcomes fully separate; `OutcomeRecord`
   stays exactly {game_id, batter_id, hit_at_least_one_home_run}; correction
   history lives only in the persistence-layer `OutcomeRevision` with a
   chain-hashed content-derived `OutcomeRevisionId`.
6. **ADR-0007** typed errors under `GreenMachineError` with `ErrorContext`; no
   broad exception handling (architecture-enforced).
7. Content-derived identities: `snapshot_id`/`input_hash` from the canonical
   payload (namespace `input_snapshot`); semantic `config_hash` excludes only
   `model_configuration_version`; `source_digest` is a separate
   newline-normalized file fingerprint.
8. `InputSnapshot` construction is gated by a module-private authority — only
   `freeze_input_snapshot` and the verifying decode path create one; identity
   is verified on decode and before serialization.
9. Persistence is append-only: exactly `append`/`get`/`query`; duplicates and
   conflicts are typed failures; supersession chains are linear with
   preexisting parents; evaluation corrections must share game, batter, and
   window profile; deterministic query ordering with identity tie-breakers;
   outcome ordering by stored chain depth.
10. Domain imports nothing (single exception: `domain/errors.py` →
    `common.errors`); config is never written by application code; every layer
    boundary is enforced by AST-based architecture tests with meta-tests
    proving the guards bite.
11. §19 config invariants are load failures, never warnings.

## 7. Verified real-data findings (spike r2; limitations preserved)

- **Direct Baseball Savant CSV** (`statcast_search/csv`) is the leading
  production event-data candidate: 119 columns including event-level
  `bat_speed`/`swing_length`/`attack_angle`, multi-player lookups, inclusive
  date bounds, permissive robots.
- **MLB Stats API** is the leading schedule / game ID / venue / game-status /
  probable-pitcher candidate (schedule + live feed verified live).
- **pybaseball 2.2.7** is suitable for exploration, not unattended production
  (hidden `hfGT=R|PO|S|` game-type template, `timeout=None`, no retry policy,
  DataFrame re-serialization). Its hidden template caused a scope difference;
  after scope matching the reconciled event sets matched **exactly** (zero key
  differences).
- Unfiltered Savant requests return **all game types** (a 2026 All-Star Game
  leaked into a seven-day window); production must filter `game_type`
  explicitly.
- Real provider data **maps into the frozen `InputSnapshot` contract** through
  the unmodified factory: six real snapshots (3 hitters × 2 profiles) with
  present / insufficient / missing / fallback / method-ineligibility states all
  exercised. **No GM-006 or GM-007 frozen-contract blocker was found.**
- `RECENT_7D` and `LONG_TERM_2Y` remain separate and share one coordinated
  **content-derived** `SourceCaptureId`; per-hitter provenance; byte-identical
  regeneration across environments.
- All results are **retrospective reconstructions**, not archived pregame
  point-in-time captures; production requires **prospective raw-response
  archiving** (the spike manifest — sanitized URL pattern, parameters,
  retrieval instant, SHA-256 — is the working prototype of that contract).
- **Weather stays missing** unless a genuine grading-time forecast is captured;
  observed weather is structurally unrepresentable as input.
- **Bat speed and attack angle exist but have coverage limitations**: tracked
  on roughly 37–42% of pitches (swing-conditional), fields exist for 2024+
  only, and the official Ideal-Attack-Angle leaderboard route is unresolved
  (the verified bat-tracking leaderboard has no attack-angle column) — the
  event-derived fallback was exercised with recorded ineligibility.
- **Official barrel classification is `launch_speed_angle == 6`**; hard-hit is
  `launch_speed >= 95`; sweet-spot is launch angle `[8, 32]`.
- **Pull classification must use row-level `stand`** (all three sampled hitters
  bat left; a player-level default is wrong and is banned), with exact-Decimal
  geometry against a fixed tan(15°) constant. **Pull Air% remains provisional**
  (tested under fly-only / fly+line / fly+line+popup denominators).
  **Overall Pull% across all eligible BBE** was tested separately and remains
  **report-only**.

## 8. Product Owner decisions and deferred backlog (record only — not implemented)

1. **Overall Pull%** — test and retain separately from Pull Air%; initially
   dashboard/context only; do not alter the frozen score until calibration.
2. **Pitchers to Target** — future dedicated tab and relevant player/matchup
   tag; deferred until the basics are complete.
3. **Bullpens to Target** — future dedicated tab and hitter/matchup tag.
   Display metrics: HR/9, ERA, Barrel% Allowed. Tags: Weak vs LHB, Weak vs
   RHB, Overworked Bullpen, HR-Prone Bullpen. Consolidation: Overworked
   Bullpen + HR-Prone Bullpen → **Bullpen to Target**. Reliever availability is
   estimated transparently from recent usage; never claim certainty without an
   official source.
4. **Weather** — initial documented candidates: **Open-Meteo** and **NWS**.
   Ballpark Pal may be considered only through officially supported API
   access. Do not pursue Doink Sports outreach. Never substitute historical
   observed weather for a pregame forecast.
5. **Provider pre-work before GM-020** (from the spike plan): Savant access
   strategy (explicit game_type, pacing/retry/timeout, honest UA); statsapi
   adapter strategy; raw-capture manifest contract; schema-drift
   fingerprinting; IAA acquisition route; park-factor source; weather-forecast
   source.

## 9. Unresolved product decisions

1. Final Pull Air denominator.
2. Whether Overall Pull% eventually becomes a modifier or stays informational.
3. Production game-type policy (All-Star/exhibition inclusion).
4. Metric-specific minimum sample thresholds.
5. Official-versus-derived metric precedence.
6. Historical bat-tracking coverage policy (2024+ fields vs two-year windows).
7. Opener/bulk-pitcher treatment.
8. Prospective raw-source retention policy.
9. Park-factor source.
10. Weather forecast source.
11. Official Ideal Attack Angle acquisition route.
12. Whether a derivation-pending missing reason is needed in the vocabulary.

## 10. Next ticket

**GM-008 — Golden Master and Property-Test Framework** (not started; no
evidence-based blocker). Scope per `docs/SPRINT_1_PLAN.md`: Hypothesis with
pinned profiles and deterministic seeds; a golden-record runner over the frozen
serialization (`tests/golden/runner.py`, `scripts/update_goldens.py`) using
synthetic fixtures only; CI fails on golden drift with an explicit regeneration
workflow; architecture guards keep Hypothesis out of production code.

## 11. Recommended sequence to the first production real-data vertical slice

Recommendation only — each step is its own reviewed ticket:

1. **GM-008** golden/property framework (hardens everything that follows).
2. **Provider rulings** (§8.5 + §9 items 1–5): game-type policy, sample
   thresholds, denominators, source precedence — cheap decisions that unblock
   ingestion design.
3. **GM-020a** raw-capture service + manifest contract (promote the spike
   manifest shape; prospective, scheduled, raw bytes + digests).
4. **GM-020c** MLB Stats API schedule/context adapter (game IDs, venues,
   probable pitchers, official slate dates).
5. **GM-020b** Savant event parser/normalizer to domain observations behind the
   no-DataFrame boundary (explicit game_type filter, schema-drift fingerprint).
6. **GM-020d** feature assembly: archived captures → both profile windows →
   frozen `InputSnapshot`s via the GM-006 factory.
7. **Scoring engine** (Sprint-2 tickets): bucket resolution, aggregation, grade
   assignment, signal evaluation over frozen snapshots + validated config.
8. **Evaluation orchestration**: envelope assembly with injected clock,
   append-only persistence writes, supersession on corrections.
9. **First vertical slice**: one real slate end-to-end — prospective capture →
   frozen snapshots → scored `GradeResult` → stored `EvaluationEnvelope` →
   minimal report — with park/weather still missing-tolerant, followed by
   outcome recording via `OutcomeRevision` after the games complete.

## 12. Roles

- **Claude Code** — implementation and tests: exactly one ticket at a time
  against frozen sources of truth; validates locally and in a clean
  extraction; delivers a repository ZIP per pass; never reopens approved
  rulings; reports (not fixes) defects found in frozen dependencies.
- **ChatGPT** — independent ZIP review and acceptance; its correction tickets
  are binding scope.
- **Grok** — baseball/statistical definitions and provider feasibility
  research.
- **Gemini** — architecture and contract critique, and acceptance
  cross-checking.
- Grok/Gemini input is research, never authoritative specification — verify
  independently before relying on it, and **explicitly flag when Grok or
  Gemini input would add value** to a task. The human Product Owner is the
  final authority; rulings arrive through ticket text.

## 13. Read first, fresh session

1. This file.
2. `docs/MODEL_SPEC.md` (the baseball model; §19 invariants) and
   `docs/GLOSSARY.md`.
3. `docs/ARCHITECTURE.md` (layering, four version streams, §4.8 persistence).
4. `docs/ENGINEERING_GUIDELINES.md` (determinism rules, append-only history).
5. `docs/adr/README.md` and ADRs 0001–0007 (all Accepted).
6. `docs/SPRINT_1_PLAN.md` — the GM-008 section before starting it.
7. In `greenmachine-savant-feasibility-spike-r2.zip`:
   `artifacts/reports/next_steps.md`, `source_recommendation.md`,
   `endpoint_inventory.md`, `point_in_time_limitations.md`,
   `contract_mapping.md`.
8. Code entry points: `src/greenmachine/domain/__init__.py`,
   `src/greenmachine/evaluation/serialization.py`,
   `src/greenmachine/config/__init__.py`,
   `src/greenmachine/persistence/__init__.py`, and
   `tests/integration/repository_contracts.py` (the reusable adapter
   contract).
