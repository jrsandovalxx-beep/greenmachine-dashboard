# GreenMachine

A deterministic and transparent MLB home-run evaluation and research platform.

> GreenMachine is not a probabilistic or machine-learning prediction model. It is a
> deterministic evaluation instrument whose rules are assessed empirically through
> point-in-time-correct backtesting and simulation.

**GreenMachine intentionally separates evaluation from decision-making.** The platform's
responsibility ends after producing a transparent, deterministic, auditable evaluation. Any
wagering, fantasy, DFS, or other downstream decision belongs entirely to the user and is
outside the scope of GreenMachine. It produces **no automated recommendation and no decision
output** of any kind.

**Product specification:** GreenMachine Model Specification **v6.3 — Foundation Clarifications**
**Code version:** 0.2.0
**Phase:** Foundations **complete** (Sprint 1, GM-001 through GM-010, closed out 2026-07-24);
**GM-020** delivered a thin production ingestion vertical slice; **GM-030** added a Streamlit
manual-review prototype over approved archived runs; **GM-040** added the operator workflow; and
**GM-041 implements the deterministic production grading engine**.

**No production model configuration has been approved yet.** Q11 through Q16 remain open
Product Owner decisions, so every executable configuration in this repository is a loudly
disclaimed synthetic fixture, and every sample score is a synthetic demonstration that says
nothing about any hitter.

---

## What it produces

For one hitter in one game against the expected starting pitcher, GreenMachine evaluates
**12 points** across five categories and preserves the full derivation.

| Category | Max points | Scored components |
|---|---:|---|
| Power Profile | 3 | Exit Velocity, Barrel %, Hard Hit % |
| Pitcher Matchup | 3 | Pitch Mix Pressure, Put-Away Pitch Exploitation |
| Form | 2 | Sweet Spot %, **Attack Angle Quality**, Bat Speed |
| Pull Power | 2 | Pull % on Air Balls |
| Environment | 2 | Park (1), Weather (1) |

**Tiers:** S `[10–12]` · A `[8–10)` · B `[6–8)` · C `[4–6)` · D `[0–4)`

The grading engine's output is exactly and only:

1. **Total Score**
2. **Tier**
3. **Component Breakdown** — per-component and per-category scores
4. **Audit Trail** — the ordered derivation
5. **Warnings** — for example insufficient-sample findings
6. **Fallbacks** — provenance of any fallback actually used

There is no automated recommendation, no decision output, and no betting classification of any
kind. Specification v6.3 originally defined such an engine; GM-041 removed it in full by
Product Owner ruling, and it will not return.

A separate **Validation Layer** (window-matched wOBA, Relief Vulnerability, Bullpen Notes,
sample and coverage warnings, fallback context) sits beside the score as **advisory context
only** — it awards no points and cannot cap, veto, or alter a score or tier.

When required data is unavailable after all approved fallbacks, the result is
**`NOT_EVALUABLE`** — not a low tier, and never a manufactured partial score.

---

## Two research views

A single source capture produces two **independently frozen, profile-specific snapshots**, each
evaluated on its own:

| Profile | Display name | Question it answers |
|---|---|---|
| `RECENT_7D` | **Recent — Last 7 Days** | Is this hitter doing it right now? |
| `LONG_TERM_2Y` | **Long-Term — Rolling 2 Years** | Is this hitter actually this good? |

One snapshot represents exactly one profile and can never produce both. The two snapshots share
a `source_capture_id` that links them to the same collection operation, but they have distinct
identities, window bounds, and observations, and comparison happens over the two independently
stored results. The profiles are never averaged, blended, or silently substituted for one
another, and there is no automatic season fallback. **Window agreement is research context
only** — whether it carries any predictive information is a question for backtesting, which is
exactly what the platform is for.

Because 7-day and 2-year distributions differ, bucket thresholds and minimum-sample
requirements are configurable **per profile**.

---

## Attack Angle Quality

Form's third component is **Attack Angle Quality**, satisfied by exactly one of two mutually
exclusive measurements:

- **Ideal Attack Angle %** — Baseball Savant's measure: the share of tracked contact events whose
  attack angle falls between **5° and 20°, inclusive**
- **Attack Angle Proxy** — a separately named, configuration-defined stand-in used only when no
  eligible Savant measurement exists

The two are never scored together, averaged, or blended, and the proxy is never presented under
Savant's name or scored with Savant's buckets. Raw average attack angle is deliberately *not*
scored as a higher-is-better metric.

Every observation preserves its `provider_id` and `acquisition_method` — direct aggregate,
structured extract, rendered scrape, event derivation, or configured proxy — so the variants stay
distinguishable in backtesting. Acquisition priority is **subordinate to point-in-time
correctness**: a method is used only if it can reproduce the exact window at the evaluation's
`as_of`, so a backtest may legitimately resolve through a lower-priority method than today's
slate does.

---

## Core guarantees

- **Deterministic** — identical inputs and configuration always produce identical output
- **Explainable** — every evaluation ships with its derivation: window, sample, raw value,
  bucket, points, category subtotal, and the cutoff that applied
- **Reproducible** — inputs are frozen and content-hashed at evaluation time
- **Point-in-time correct** — no observation dated after an evaluation's `as_of` can enter it;
  rolling windows are rebuilt from event timestamps, never from current aggregate tables
- **Auditable** — evaluations, snapshots, configurations, and outcomes are append-only;
  corrections supersede rather than overwrite
- **Governed** — a configuration change creates a new model version with Product Owner approval,
  validation, and golden-test review; it never alters what a previous version decided

Outcomes are stored separately from pregame evaluations, so hindsight cannot contaminate them.

AI assists software engineering. AI never participates in runtime evaluation.

---

## Built for the long game

Daily evaluation, historical replay, backtesting, simulation, configuration comparison, and
profile comparison are all different callers of one identical, pure evaluation core.

---

## Current status

**Implemented and frozen** — every piece below is fully tested, independently reviewed, and
covered by the accepted ADRs:

- the immutable **domain vocabulary** (components, measurements, profiles, sample status,
  provenance, game identity)
- **determinism primitives**: project-local Decimal policy, injected clock, canonical
  byte-identical serialization, content-derived identifiers
- the **typed error taxonomy** and structured logging baseline
- the **configuration system**: strict YAML loading into frozen typed objects with every
  MODEL_SPEC §19 invariant enforced at load, plus **semantic configuration hashing**
- the frozen **`InputSnapshot`** (one profile each, content-hashed identity) and the pure
  **`GradeResult`** variants, separated from the orchestration **`EvaluationEnvelope`**
- **append-only persistence ports** with in-memory adapters, outcome revision chains, and a
  reusable adapter contract suite
- the **golden-master and property-test harness**: profile-aware golden cases, deterministic
  Hypothesis configuration (fixed seed 20260724), and network blocking — socket and resolver
  entry points blocked in the parent pytest process, with every test-spawned Python interpreter
  launched through an explicit guarded bootstrap

**The grading engine — `scoring` (GM-041)** — is implemented: a pure function of
`(frozen InputSnapshot, loaded GreenMachineConfig)` with no I/O, clock, network, randomness, or
float anywhere in it. Half-open bucket resolution with a closed terminal bucket, binary
qualification over the reserved `observed_value` input, configured missing-data policy, exact
Decimal aggregation with no rounding, tier assignment from configured cutoffs, and an ordered
audit derivation explaining every awarded and withheld point. It refuses any snapshot whose
observation metadata disagrees with the configuration describing it, rather than reconciling
the two. A labeled synthetic sample over real archived snapshots lives at
[docs/samples/gm041_sample_evaluation.md](docs/samples/gm041_sample_evaluation.md).

**Implemented for the vertical slice only** — `ingestion` (GM-020): prospectively archived raw
provider responses, content-derived capture identity, fail-closed schema contracts,
regular-season-only half-open windows, event-derived metrics in exact Decimal, two
profile-specific snapshots from one capture, and deterministic offline replay. Full reference:
[docs/GM_020_VERTICAL_SLICE.md](docs/GM_020_VERTICAL_SLICE.md). It covers one game and one
hitter — not a slate. Sample minimums are injected, never defaulted (production minimums remain
**Q14**), and the pitch-matchup composites stay missing pending **Q15/Q16** rather than being
invented. **GM-040** adds the operator workflow over that unchanged pipeline
(`scripts/run_gm040_real_slice.py`): explicit real-data selections with projected/confirmed
lineup status, honest prospective vs. retrospective-development classification, an operator
report per bundle, and idempotent publication — one independent manifest-v1 bundle per hitter
(see [docs/GM_040_RUNBOOK.md](docs/GM_040_RUNBOOK.md)).

**Implemented as a usability prototype** — `reporting` + `streamlit_app.py` (GM-030, r1): a
manual-review dashboard over approved archived runs, opening on an original GreenMachine
console-style landing hub. Read-only replay-verified loading with strict display adapters for
audit reports, data-status colors only (no performance thresholds), user-entered manual scoring
with deterministic exports, Whiff Rate excluded by ruling, pitcher-specific metrics deferred, no
live capture, no recommendation. **The prototype does not yet render the production engine's
evaluation** — surfacing score, tier, breakdown, and audit trail in the interface belongs to the
later **GM-041.5 Stabilization & UX Review**. See
[docs/STREAMLIT_PROTOTYPE.md](docs/STREAMLIT_PROTOTYPE.md); launch with
`streamlit run streamlit_app.py` after `pip install -e ".[dev,ui]"`.

**Placeholder-only** (docstring packages with no behavior): `features` and `cli`. `scoring` is
**no longer a placeholder**. The exact remaining boundary: **no production model-configuration
version has been published**, and **no baseball threshold, allocation, or minimum is implemented
in `src/`** — every such number is configuration data. `MODEL_SPEC.md` *does* contain approved
specification rules and defaults — the 15% qualifying pitch-usage default, the tier boundaries,
the 5°–20° Ideal Attack Angle definition — which engineering implements but never invents; the
synthetic configurations under `tests/fixtures/` are not production model configurations.

The Sprint 1 acceptance record lives at
[docs/SPRINT_1_CLOSEOUT.md](docs/SPRINT_1_CLOSEOUT.md).

---

## Getting started

```bash
python -m pip install -e ".[dev]"
```

Run the complete verification suite:

```bash
pytest -q
ruff format --check .
ruff check .
mypy --strict src/
```

The test suite is fully local and deterministic: network-capable socket and resolver entry
points are blocked in the parent pytest Python process, every test-spawned Python interpreter
runs through an explicit guarded bootstrap that installs the same blocks (non-Python
subprocess execution remains permitted and is not covered by the Python socket guard), no
test depends on the current date, and every fixture is visibly synthetic. See
[tests/README.md](tests/README.md) for the golden-case workflow.

---

## Documentation

| Document | Owns |
|---|---|
| [GREENMACHINE_DEVELOPER_HANDOFF.md](docs/GREENMACHINE_DEVELOPER_HANDOFF.md) | **Canonical engineering handoff — current state, roadmap, known issues** |
| [MODEL_SPEC.md](docs/MODEL_SPEC.md) | **Authoritative baseball and evaluation specification (v6.3)** |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Engineering structure, layering, risks, implementation status |
| [PHILOSOPHY.md](docs/PHILOSOPHY.md) | Why GreenMachine exists and what is non-negotiable |
| [ENGINEERING_GUIDELINES.md](docs/ENGINEERING_GUIDELINES.md) | Standards, determinism rules, testing strategy |
| [GLOSSARY.md](docs/GLOSSARY.md) | Exact metric, profile, and status definitions |
| [OPEN_QUESTIONS.md](docs/OPEN_QUESTIONS.md) | Live register of unresolved decisions |
| [SPRINT_1_PLAN.md](docs/SPRINT_1_PLAN.md) | Sprint 1 tickets — **complete**, all accepted |
| [SPRINT_1_CLOSEOUT.md](docs/SPRINT_1_CLOSEOUT.md) | Sprint 1 acceptance record |
| [docs/adr/](docs/adr/) | Architecture Decision Records — ADRs 0001–0008, all **Accepted** |
| [CHANGELOG.md](CHANGELOG.md) | Specification, code, configuration, and schema history |

`MODEL_SPEC.md` owns product behavior. `ARCHITECTURE.md` owns engineering structure. The two are
never mixed. Historical documents — the CHANGELOG, the Sprint 1 records, and revision histories —
deliberately retain accurate references to superseded designs, including the removed v6.3 signal
engine.

---

## Versioning

Four independent streams, all recorded on every stored evaluation:

| Stream | Current | Changes when |
|---|---|---|
| Product specification | v6.3 | Baseball/product specification changes |
| Code | 0.2.0 | Software changes |
| Model configuration | not yet published | Thresholds, allocations, buckets, or cutoffs change |
| Evaluation schema | 1 | Persisted record formats change |

---

## Roadmap

The **approved post-Sprint-1 sequence**, which supersedes the original phase ordering below.
One ticket is active at a time; the next is not started until the previous is reviewed and
closed.

1. Sprint 1 / GM-010 closeout *(complete)*
2. **GM-020** — thin production ingestion vertical slice *(complete)*
3. **GM-030** — Streamlit manual-review prototype *(complete)*
4. **GM-040** — real-data operator slice *(complete)*
5. **GM-041 — production grading engine** *(complete, in review)*
6. **GM-041.5 — Stabilization & UX Review** — including rendering the engine's evaluation in
   the interface
7. **GM-042 — Record Book & Performance Analytics**

Beyond the sequence above, and unscheduled: Product Owner resolution of Q11–Q16 producing the
first production model configuration; evaluation persistence wiring; full-slate expansion
(needs a manifest v2 ruling); and repository cleanup.

Original phase plan (historical; ordering superseded by the sequence above):

- **Phase 1 — Discovery & specification** *(complete)*
- **Phase 2 — Foundations** (Sprint 1): domain contracts, configuration system, determinism
  primitives, persistence ports, test harness *(complete — closed out 2026-07-24)*
- **Phase 3 — Grading core**: bucket scoring, aggregation, tiers, Validation Layer
- **Phase 4 — Data & persistence**: ingestion adapters incl. Savant, point-in-time snapshots,
  durable store, outcome capture
- **Phase 5 — Research tooling**: replay, backtesting, configuration and profile comparison
- **Phase 6 — Interface**: local single-user Streamlit research dashboard over stored evaluations

---

## Team

**Product Owner** — baseball philosophy, metric selection, windows, scoring philosophy,
threshold approval, product priorities, final architectural approval.

**Principal Software Engineer** — implementation quality, testing, technical recommendations,
maintainability, documentation, engineering risk identification.

Baseball logic is never changed without Product Owner approval.
