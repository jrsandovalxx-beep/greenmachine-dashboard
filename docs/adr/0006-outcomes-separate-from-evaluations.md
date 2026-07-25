# ADR-0006 — Outcomes stored separately from evaluations

**Status:** Accepted
**Date:** 2026-07-22 · GM-006 delivered the contract · accepted on delivery of GM-007
**Implementing ticket:** GM-006, GM-007

> **GM-006 status note.** The `OutcomeRecord` contract and the structural guarantee that no
> evaluation contract (`InputSnapshot`, either `GradeResult` variant, or `EvaluationEnvelope`) can
> carry an outcome field are implemented and tested.
>
> **GM-007 acceptance note.** The separate, append-only outcome repository this decision requires
> is implemented: `OutcomeRepository` (with its in-memory adapter) exposes only `append`, `get`,
> and `query`, and stores outcomes entirely apart from evaluations — no outcome write path into an
> evaluation exists, enforced by architecture tests. Corrections are append-only through the
> **persistence-only** `OutcomeRevision` wrapper (Product Owner ruling): a content-derived
> `outcome_revision_id`, an optional `supersedes` link forming a linear, subject-coherent,
> non-branching chain, and the frozen outcome. `OutcomeRecord` itself remains exactly the minimal
> domain contract — game, batter, one boolean — with no identity, supersession, or timestamp.

## Context

Backtesting requires knowing what actually happened — initially, whether the batter hit at least
one home run in the evaluated game. The obvious implementation is a nullable `outcome` field on
the evaluation record, filled in after the game.

That implementation is a hindsight-contamination machine. It makes a pregame record mutable,
gives every reader of an evaluation access to the future, and makes "was this evaluation written
before or after the game?" unanswerable from the data. It also violates the append-only guarantee
that replay and audit depend on.

## Decision

**Outcomes are a separate record type in a separate repository.**

- `OutcomeRecord` carries game and batter identity plus the outcome, and is stored independently
- **No outcome field exists on `GradeResult` or `EvaluationEnvelope`** — attaching one is
  structurally impossible, not merely discouraged
- Outcomes are append-only like everything else; a correction supersedes rather than overwrites
- Research joins evaluations to outcomes at analysis time, explicitly
- An outcome record never mutates the original pregame evaluation

Sprint 1 delivers the **contract and its structural tests only** — no outcome ingestion, no
additional outcome fields. The contract is in scope precisely because without it, nothing prevents
an outcome field being added to the envelope later, which is the failure this ADR exists to
prevent.

## Consequences

- Pregame evaluations remain permanently pregame; hindsight cannot leak backward
- Every research query pays an explicit join, which is a feature: the join is where the analyst
  states what they are comparing
- Odds, ROI data, and any future outcome-adjacent data have an obvious home outside evaluations
- Slightly more machinery than a nullable field, and a discipline the first "just add a column"
  request will test

## Alternatives considered

- **Nullable outcome field on the evaluation** — simplest and the reason this ADR exists
- **Outcome written into a superseding evaluation** — abuses supersession, which means "this
  evaluation was corrected", not "the game finished"
- **Denormalized research view materialized after each game** — acceptable later as a derived
  read model, but not as the system of record
