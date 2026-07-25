# ADR-0002 — Numeric and bucket-boundary policy

**Status:** Accepted
**Date:** 2026-07-22 (proposed) · 2026-07-22 (accepted under specification v6.3)
**Implementing ticket:** GM-005

## Context

Determinism fails at boundaries and in accumulation. Three concrete hazards:

1. A metric value of exactly `95.0` against a bucket edge of `95.0` must resolve the same way
   on every platform and every library version.
2. A total of `7.9999999` against a grade cutoff of `8` must not depend on accumulation order.
   Specification v6.3 allows **fractional points**, so totals are now sums of non-integer
   values and this hazard is no longer theoretical.
3. Binary floating point cannot represent common decimal thresholds exactly. `0.1 + 0.2` is not
   `0.3`; a category maximum of `2` scored as `0.75 + 0.75 + 0.5` may or may not compare equal
   to `2`. Under v6.3 a "strong category" test compares against `category_max × 0.75` — with
   binary floats, `2.25` versus a summed `2.25` is a coin flip.

GreenMachine additionally has **two different interval conventions** that must coexist:

- **Scoring buckets**, whose boundaries are ours to define
- **The Ideal Attack Angle event predicate**, which is Baseball Savant's published definition —
  an attack angle from 5° **through** 20°, inclusive at both ends (MODEL_SPEC §9.2)

Implementing both with one helper would silently corrupt one of them.

## Decision

### Numeric representation

- **Decimal** is used for thresholds, metric values entering scoring, point values, category
  totals, and total scores.
- **A Decimal is never constructed from a binary float.** `Decimal(0.1)` is prohibited.
- Decimals are constructed from **provider strings**, **configuration strings**, or
  **integers**. This is a constraint on ingestion as much as on scoring: numeric fields
  destined for scoring leave an adapter as strings, not as parsed floats. A value that has
  been through `float` once has already lost the guarantee.
- All grading arithmetic runs under a **project-local Decimal context** with **precision 28**
  and **`ROUND_HALF_EVEN`**. The context is local, never a mutation of the global context, so
  it cannot be disturbed by another library.
- Derived ratios and percentages are computed under that declared context.
- Derived values are **not quantized** before scoring.
- **No rounding occurs before** bucket qualification, category aggregation, total aggregation,
  grade assignment, strong-category comparison, or signal assignment.
- **Presentation rounding happens outside the grading core** and never feeds back into it.
- **Canonical serialization emits Decimals as deterministic base-10 strings**, never binary
  floats. A round trip through JSON must not change a value.

### Interval conventions

- **Scoring intervals are half-open `[lower, upper)`.** A value equal to a shared boundary
  belongs to the **upper** bucket. The terminal bucket is **closed** at the domain maximum.
- **Grade cutoffs follow the same rule:** D `[0,4)`, C `[4,6)`, B `[6,8)`, A `[8,10)`,
  S `[10,12]`.
- **Event-level eligibility predicates defined by an external source use a separate, distinctly
  named inclusive-range helper.** The 5°–20° attack-angle rule uses this helper, in `features`,
  and never the bucket helper.

The two helpers are deliberately separate implementations. A test asserts they disagree at a
shared boundary input, so they can never be silently unified.

## Consequences

- Fractional allocations, `× 0.75` strong-category tests, and 12-point totals all compare
  exactly. `2.25 >= 2.25` is true because both are the same Decimal, not because a tolerance
  happened to absorb the error.
- No epsilon comparisons anywhere in the grading path. If a tolerance ever appears in a review,
  it is a sign that a float leaked in.
- Determinism holds across platforms, Python builds, and library versions, because Decimal
  semantics are specified rather than hardware-dependent.
- **Cost, accepted:** ingestion and feature assembly become fussier. pandas reads numeric CSV
  columns as `float64` by default, so any column feeding scoring must be read with a string
  dtype and converted deliberately. This is the most likely place the policy will be violated
  by accident, and it is worth an explicit test at the adapter boundary.
- Decimal arithmetic is slower than float. Irrelevant here: a slate is small, and correctness
  dominates.
- Two interval conventions in one system remains a comprehension hazard, mitigated by naming,
  layer separation, mandatory boundary tests at 5.0 and 20.0, and this record.
- Config authors must understand that a bucket's upper edge belongs to the next bucket.
- Slight duplication between the two interval helpers is accepted deliberately; deduplicating
  them would be the bug.

## Alternatives considered

- **Binary floats with epsilon comparisons** — the default, and incompatible with exact
  fractional allocations. The tolerance itself becomes an undocumented threshold, and the
  correct epsilon differs between a 0.25-point bucket and a 12-point total.
- **Integer-scaled arithmetic** (store points as hundredths) — genuinely deterministic and
  fast, and it was the leading alternative once fractional allocations were approved in v6.3.
  Rejected because the scale factor becomes an implicit global constant that every threshold
  author must remember, configuration files stop being readable as baseball values, and
  percentages and ratios still need a rational representation somewhere. Decimal keeps
  configuration in the units the Product Owner writes.
- **`fractions.Fraction`** — exact for ratios, but produces unbounded denominators through
  repeated division and serializes poorly.
- **One inclusive interval convention everywhere** — would misrepresent Savant's published
  definition or create overlapping buckets.
- **Configurable interval convention per metric** — maximum flexibility, maximum chance of two
  metrics silently disagreeing; rejected as over-engineering with a correctness cost.
