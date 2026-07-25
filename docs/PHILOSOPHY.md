# GreenMachine — Philosophy

**Specification lineage:** GreenMachine Model Specification **v6.2**
**Status:** Approved 2026-07-22
**Owner:** Product Owner (baseball philosophy) · Principal Engineer (engineering interpretation)

This document records *why* GreenMachine exists and what must never be traded away.
Engineering decisions are judged against it. If a design conflicts with anything here, the
design is wrong.

Baseball and grading behavior is specified in `MODEL_SPEC.md`. Engineering structure is
specified in `ARCHITECTURE.md`. This document holds the reasoning behind both.

---

## 1. Product identity

GreenMachine is a **deterministic and transparent MLB home-run grading and research platform**.

It is **not**:

- A machine-learning model
- A probabilistic model
- An AI prediction runtime
- A black-box scoring system

Its purpose is to **identify, research, backtest, and validate potentially predictive home-run
edges through fully explainable rules**.

> **GreenMachine is not a probabilistic or machine-learning prediction model. It is a
> deterministic grading instrument whose rules and potential edges are evaluated empirically
> through point-in-time-correct backtesting and simulation.**

AI assists software engineering. AI never participates in runtime grading.

### 1.1 Evaluation is separate from decision-making (permanent, binding)

> **GreenMachine intentionally separates evaluation from decision-making.**
>
> The platform's responsibility ends after producing a transparent, deterministic, auditable
> evaluation. Any wagering, fantasy, DFS, or other downstream decision belongs entirely to the
> user and is outside the scope of GreenMachine.

This is a permanent product principle, not a phase. It has concrete consequences that no future
ticket may reverse:

- The grading engine's output is exactly and only **Total Score, Tier, Component Breakdown,
  Audit Trail, Warnings, and Fallbacks**.
- No betting classification may exist in any form — no signal, signal reason, strong bet, lean,
  pass, avoid, betting recommendation, recommendation engine, or equivalent. Specification v6.3
  defined such an engine; GM-041 removed it in full by Product Owner ruling.
- Wording discipline applies everywhere — interface, exports, reports, and documentation
  describe data and derivations, never advice.

Historical notes explaining the removal are permitted. Production implementation references
are not.

---

## 2. The problem we are solving

Most home-run tooling is a black box. When it is wrong, nobody can say why. When it is right,
nobody can say which part did the work.

GreenMachine takes the opposite position: a home-run opportunity should be graded from named,
observable baseball inputs with human-authored thresholds, and the reasoning should survive
being read back years later.

The consequence is that **edge is not asserted, it is measured**. A rule earns its place in the
model by surviving point-in-time-correct backtesting, not by seeming reasonable. The grading
instrument exists so that research has something stable to measure against.

---

## 3. Guiding principles

### 3.1 Determinism
Same inputs + same configuration ⇒ byte-identical output. Always. No sampling, no randomness,
no wall-clock reads inside grading, no reliance on undefined ordering, no unmanaged
floating-point drift.

### 3.2 Explainability
A grade is not a number. It is a number **plus the full derivation**: which metrics were used,
over which window, from which sample, with what raw values, landing in which buckets, awarding
what points, and under which configuration. Explanation is a first-class output artifact.

### 3.3 Reproducibility
Any historical evaluation can be re-derived exactly. This requires more than deterministic
code — it requires that **inputs are frozen at grading time**. Providers revise their numbers;
weather forecasts become observations; rolling windows keep moving. Reproducibility means we
snapshot what we saw, not that we can re-fetch it.

### 3.4 Point-in-time correctness
No event or observation dated after an evaluation's `as_of` may enter that evaluation. Rolling
windows are reconstructed from event timestamps, never recomputed from current aggregate
tables. A backtest that leaks the future is worse than no backtest, because it is convincing.

### 3.5 Auditability
Every stored evaluation is immutable and append-only. History is never overwritten,
recomputed in place, or silently migrated. Corrections are new records that supersede old ones,
and the supersession is itself part of the record.

### 3.6 Configuration governance
Thresholds, bucket boundaries, allocations, and cutoffs are **data**, not code.
But configuration is **part of the model**, not a scratchpad. Changing a threshold must not
require changing Python — and must still require a new model configuration version, Product
Owner approval, strict schema and semantic validation, golden-test review, historical
comparison where applicable, changelog documentation, and preservation of the previous version.
Once a configuration has produced an evaluation, it is immutable.

A baseball rule change and a code implementation change are different events, and are versioned
separately.

### 3.7 Explicit states over convenient nulls
Missing data, insufficient sample, and zero are three different conditions. Collapsing them is
the most common way an honest-looking model becomes quietly wrong. Every one of them is modeled
explicitly and travels through to the output.

### 3.8 Separate views, never blended
The recent view and the long-term view answer different baseball questions. They are separate
evaluation profiles that may disagree — and that disagreement is itself research signal. They
are never averaged, blended, or silently substituted for one another.

### 3.9 Objective metrics, not learned weights
Scoring uses named baseball measurements with human-authored bucketing. No ML, no fitted
coefficients, no black-box components in the grading path.

---

## 4. Two research views

v6.2 retires the previous Last-14-Days design and the automatic season fallback that went with
it. In their place are two selectable evaluation profiles:

| Profile | Display name | Question it answers |
|---|---|---|
| `RECENT_7D` | Recent — Last 7 Days | *Is this hitter doing it right now?* |
| `LONG_TERM_2Y` | Long-Term — Rolling 2 Years | *Is this hitter actually this good?* |

The same snapshot may produce one grade under each profile. The dashboard will eventually let
the user toggle and compare side by side.

**Window agreement** — whether the two views concur — is research context only. It is not a
scored category, a point adjustment, or a veto. Whether agreement carries
signal is exactly the kind of question the platform exists to answer empirically, and it will
be answered by backtesting, not by assumption.

Because 7-day and 2-year distributions differ, configuration supports profile-specific buckets
and profile-specific minimum-sample requirements without Python changes.

---

## 5. What GreenMachine should become

Today: a daily grader with two research views.

By deliberate design from day one:

1. **Daily grading** — graded, explained opportunities for a slate
2. **Historical replay** — re-run any past date with the exact configuration and inputs used
   at the time, reproducing the original output
3. **Backtesting** — run a configuration across a long historical span with point-in-time
   correct inputs
4. **Simulation** — run hypothetical configurations against historical inputs
5. **Configuration comparison** — grade the same inputs under two model versions and diff both
   the outcomes and the reasoning
6. **Long-term edge research** — determine which categories, metrics, buckets, and window
   profiles actually carried signal

**The engineering consequence:** every capability above is a different *caller* of one identical
grading core. The core must be a pure function of `(frozen inputs, configuration)`. Anything
that makes it impure — a database read, a network call, a `datetime.now()` — permanently
forecloses one of the six. This remains the single most important engineering constraint in the
project.

---

## 6. Non-goals

- Predicting outcomes with machine learning
- Optimizing accuracy at the expense of explainability
- Real-time or low-latency grading; a slate is small and correctness dominates
- Manufacturing a score when required data is unavailable — that is `NOT_EVALUABLE`, by design
- A general-purpose sports analytics framework

---

## 7. Ownership

**Product Owner controls:** baseball philosophy, metric selection, windows, scoring philosophy,
threshold approval, product priorities, final architectural approval.

**Principal Software Engineer controls:** implementation quality, testing, technical
recommendations, maintainability, documentation, engineering risk identification.

Baseball logic is never changed without Product Owner approval. Ambiguity is escalated to
`OPEN_QUESTIONS.md`, never resolved by invention.
