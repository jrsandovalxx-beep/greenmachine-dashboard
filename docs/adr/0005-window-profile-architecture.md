# ADR-0005 — Window-profile architecture

**Status:** Accepted
**Date:** 2026-07-22 · amended under specification v6.3 · accepted on delivery of GM-006
**Implementing ticket:** GM-002, GM-003, GM-006

## Context

Specification v6.2 retires the Last-14-Days window and its automatic season fallback, replacing
them with two selectable evaluation profiles: `RECENT_7D` (Last 7 Days) and `LONG_TERM_2Y`
(Rolling 2 Years). They answer different baseball questions — current form versus underlying
skill — and MODEL_SPEC §5.4 prohibits averaging, blending, silent substitution, and hybrid grades.

The engineering hazard is **profile leakage**: a two-year value quietly satisfying a seven-day
metric. This would be invisible in output, would inflate completeness, and would corrupt exactly
the comparison the platform exists to perform.

A second hazard is confusing two legitimately different things: an approved *component-level
acquisition* fallback (`direct_aggregate` → `event_derived` → `configured_proxy`) is allowed; a
*cross-window* fallback never is.

A third hazard, resolved by v6.3, was structural: earlier drafts said one snapshot could be
graded under both profiles. That would have made a snapshot's `input_hash` ambiguous — two
different window bounds and two different observation sets behind one identity — and it would
have put profile selection inside the core rather than upstream of it.

## Decision

**`WindowProfile` is a first-class domain dimension, carried rather than inferred.**

- A `WindowProfile` enum with exactly `RECENT_7D` and `LONG_TERM_2Y`, each carrying its display
  name
- Profile appears on: every `MetricObservation`, the `InputSnapshot` (with resolved
  `window_start` / `window_end`), the `GradeResult`, and evaluation identity
- The core validates profile consistency on entry and **raises** on mismatch rather than
  degrading
- **One `InputSnapshot` represents exactly one `WindowProfile`** and may never contain or
  produce both. `RECENT_7D` snapshot → `RECENT_7D` GradeResult; `LONG_TERM_2Y` snapshot →
  `LONG_TERM_2Y` GradeResult
- **One source capture may produce two independently frozen profile-specific snapshots.** They
  share a `source_capture_id` linking them to the same source-data collection operation, and
  differ in `snapshot_id`, `input_hash`, `window_profile`, `window_start`, `window_end`, and
  metric observations
- Profile comparison occurs in `reporting`, over two independently stored `GradeResult`s
- Configuration is addressable per profile for bucket sets and minimum-sample requirements, with
  no Python change required to add a profile-specific threshold
- The two fallback kinds are represented by **different fields** — `attack_angle_source` /
  `fallback_used` versus `window_profile` — so a cross-window substitution is hard to express by
  accident
- Window agreement is computed in `reporting` over two stored results and never enters the core
- Golden tests are profile-specific; coverage requires both profiles from the same **source
  capture**, expressed as two profile-specific snapshots

**Point allocations are profile-invariant** (Q25, closed under v6.3). `RECENT_7D` and
`LONG_TERM_2Y` may differ in bucket thresholds, minimum sample requirements, actual sample
counts, and data coverage. They may not differ in component `max_points`, category maximums,
total maximum score, or grade cutoffs. Configuration therefore validates **one** allocation
structure shared by both profiles, rather than one per profile.

## Consequences

- Profile leakage becomes a raised error rather than a silent wrong answer
- Profile comparison research is supported by construction, not bolted on
- Configuration surface roughly doubles for windowed metrics, and authoring gets more error-prone
  — mitigated by load-time validation requiring a bucket set for every declared profile
- Storage roughly doubles when both profiles are graded — two snapshots as well as two results;
  accepted
- A profile-invariant allocation keeps cross-profile grade comparison meaningful: a difference
  between a recent and a long-term grade reflects the hitter, not a differently weighted scale
- Adding a third profile later is a configuration and enum change, not a redesign

## Alternatives considered

- **Profile as a loose parameter passed to the scorer** — simplest, and exactly how leakage
  happens; nothing in the stored output would prove which window a value came from
- **One evaluation holding both profiles' results** — invites averaging and complicates identity;
  MODEL_SPEC treats them as separate evaluations
- **One snapshot serving both profiles** — the v6.2 draft position, rejected in v6.3: it makes
  `input_hash` ambiguous, hides which window bounds produced a value, and moves profile
  selection into the core
- **Profile-specific allocations** — considered and rejected: two scales make a recent grade and
  a long-term grade incomparable, which defeats the purpose of running both
- **Separate config trees per profile** — duplicates metric definitions that genuinely are shared
  (method, direction, domain, sample type); rejected as a drift risk
