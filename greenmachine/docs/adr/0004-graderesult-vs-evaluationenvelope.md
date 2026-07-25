# ADR-0004 — GradeResult vs. EvaluationEnvelope

**Status:** Accepted
**Date:** 2026-07-22 · accepted on delivery of GM-006
**Implementing ticket:** GM-006

## Context

Every stored evaluation needs orchestration metadata: an identifier, `evaluated_at`, four version
values, two content hashes, provenance, and a supersession reference. But `evaluated_at` is a
clock read, and the grading core must never read a clock.

If grading output and orchestration metadata share one type, one of two bad things happens: the
core acquires a clock dependency, or the type is constructed in two places with half its fields
empty at each. Both destroy the determinism guarantee that everything else depends on.

## Decision

Two separate contracts.

**`GradeResult`** — the pure deterministic output of `(frozen EvaluationInput, model
configuration)`. Contains: evaluation status, selected window profile, metric observations,
bucket results, metric scores, category scores, total score, grade, signal, validation findings,
and the complete audit derivation. It contains **no timestamp, no identity, no version, and no
hash**.

**`EvaluationEnvelope`** — wraps a `GradeResult` and carries `evaluation_id`, `snapshot_id`,
`evaluated_at`, code version, model configuration version, product-specification version, schema
version, `config_hash`, `input_hash`, subject identity, pitcher role, provenance, and
`supersedes`.

`evaluated_at` is supplied by orchestration through an injected clock and placed on the envelope.
The core never generates it.

**Determinism scope, stated precisely:** `GradeResult` is byte-identical for identical inputs and
configuration, unconditionally. `EvaluationEnvelope` is byte-identical when inputs, configuration,
**and envelope metadata** are identical — which in practice means determinism tests on the
envelope use a `FixedClock`.

Type-level constraints: an `EVALUATED` result without a score, and a `NOT_EVALUABLE` result with
one, must both be unconstructable.

## Consequences

- The core keeps its purity guarantee by construction rather than by discipline
- Determinism tests can target `GradeResult` with no clock control at all — the strongest
  possible form of the test
- Two types instead of one, and readers must unwrap the envelope to reach the result
- Configuration comparison and profile comparison can diff `GradeResult` objects directly without
  filtering out timestamps and identifiers — a benefit that only becomes obvious later

## Alternatives considered

- **Single record with nullable metadata** — collapses the purity boundary; the core would need
  to know which fields it must leave empty
- **Metadata in a sidecar file** — same separation, worse ergonomics, easy to lose
- **Inject the clock into the core** — makes the core impure for no gain; the timestamp is not an
  input to any grading decision
