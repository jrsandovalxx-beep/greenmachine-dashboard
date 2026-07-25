# Architecture Decision Records

An ADR records a decision that is expensive to reverse, together with the context that produced
it and the consequences accepted along with it.

## Rules

- One decision per record, numbered sequentially and never renumbered
- Records are **append-only**: a superseded ADR is marked `Superseded by ADR-XXXX`, never edited
  away or deleted
- Required sections: **Context**, **Decision**, **Consequences**, **Status**
- Valid `Status` values: `Proposed`, `Accepted`, `Superseded by ADR-XXXX`, `Rejected`
- Baseball rules never belong in an ADR. Product behavior lives in `MODEL_SPEC.md`; ADRs record
  engineering decisions only

## Index

| ADR | Title | Status |
|---|---|---|
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | Accepted |
| [0002](0002-numeric-and-bucket-boundary-policy.md) | Numeric and bucket-boundary policy | **Accepted** |
| [0003](0003-snapshot-and-point-in-time-policy.md) | Snapshot and point-in-time policy | **Accepted** |
| [0004](0004-graderesult-vs-evaluationenvelope.md) | GradeResult vs. EvaluationEnvelope | **Accepted** |
| [0005](0005-window-profile-architecture.md) | Window-profile architecture | **Accepted** |
| [0006](0006-outcomes-separate-from-evaluations.md) | Outcomes separate from evaluations | **Accepted** |
| [0007](0007-error-handling-and-logging.md) | Error handling and structured logging | **Accepted** |
| [0008](0008-golden-testing-strategy.md) | Golden testing strategy | **Accepted** |

ADR-0002 was accepted under specification v6.3, ahead of its implementing ticket, because GM-005
cannot be implemented without the complete numeric policy. ADR-0007 was accepted on delivery of
GM-009, which implements the typed hierarchy rooted at `GreenMachineError`, the structured logging
baseline, and the architecture rule that rejects broad exception handling. ADRs 0003, 0004, and
0005 were accepted on delivery of GM-006, which implements the frozen `InputSnapshot` with
content-derived identity, the pure `GradeResult` variants separated from the `EvaluationEnvelope`,
and the single-profile-per-snapshot architecture. ADR-0006 was accepted on delivery of GM-007,
which adds the separate append-only outcome repository and the persistence-only `OutcomeRevision`
correction chain while `OutcomeRecord` itself stays the minimal domain contract. ADRs 0003 and
0005 were amended under v6.3. ADR-0008 was accepted on delivery of GM-008, which implements the
profile-aware golden harness, the deliberate golden-update script, the deterministic Hypothesis
profile, and the suite-wide network block; the Sprint plan's original `0005-golden-testing-strategy`
filename was superseded by Product Owner ruling because ADR numbers are never reused.
