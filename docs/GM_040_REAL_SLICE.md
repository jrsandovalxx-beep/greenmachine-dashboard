# GM-040 — Prospective Real-Data Vertical Slice (implementation report)

**Status:** implemented as pure composition over the frozen GM-020 pipeline.
Version stays 0.2.0. Operator workflow: [GM_040_RUNBOOK.md](GM_040_RUNBOOK.md).

## What GM-040 is

Proof that one real MLB game, one manually selected hitter, and one expected
starting pitcher flow through the **existing** capture → raw archive →
verification → normalization → mapping → deterministic replay → Streamlit
review path. It is not a slate, scoring, persistence, or UI-redesign ticket.

## Reuse-first outcome

GM-040 changed **zero** lines of capture, archive, replay, metric, mapping,
snapshot, or dashboard behavior. The audit confirmed the GM-020 pipeline and
GM-030 viewer already satisfy the objective end-to-end; the only genuinely
missing extension points were operator-facing, added in one new module
([`ingestion/operator.py`](../src/greenmachine/ingestion/operator.py)) plus a
script composition root
([`scripts/run_gm040_real_slice.py`](../scripts/run_gm040_real_slice.py)):

1. **Operator selection** — explicit slate date, gamePk, hitter MLBAM id,
   projected/confirmed lineup status, capture mode, optional pitcher
   cross-check, optional note. Invalid values fail closed; nothing is
   guessed.
2. **Lineup status surface** — no compatible frozen surface exists (status is
   not part of any manifest-v1 identity, snapshot, or archived report), so
   per ruling it is recorded in the generated **operator report** only:
   `reports/operator_report.json` + `OPERATOR_REPORT.md`, appended to the
   file plan *before* the existing atomic publication. Identities are
   provably untouched (a GM-040 bundle replays byte-identically).
3. **Honest timing classification** — from recorded manifest instants only:
   `prospective` restates the timing the frozen GM-020 contract already
   proved; `retrospective-development` (explicit `--capture-mode
   retrospective` permission) is clearly distinguished, never rejected when
   useful, and **never represented as a locked pregame prediction** — even
   when its timestamps precede the scheduled start, the report says exactly
   that.
4. **Expected-pitcher cross-check** — manifest v1's semantic contract binds
   the pitcher capture to the *feed-resolved* pitcher, so an
   operator-supplied MLBAM id is verification only: a mismatch fails closed
   before anything is published. An unresolvable feed remains a fail-closed
   eligibility outcome; v1 has no override, by design.
5. **Idempotent publication** — `publish_or_verify`: a new directory
   publishes atomically; an existing byte-identical bundle (the once-only
   replay report being the sole permitted extra) returns
   `verified-existing` without writing; any true content conflict fails
   explicitly. Content-derived identities (`SourceCaptureId`,
   `manifest_id`, snapshot ids) are deterministic for identical
   participating content by the frozen GM-020 construction.

## Ticket-vs-frozen-contract tensions, resolved

- *Operator-supplied pitcher "when it cannot be resolved safely"* collides
  with the frozen v1 rule that the pitcher request equals the feed
  resolution. Resolution: cross-check only (above); locked ruling 2 wins.
- *"Do not add Overall Pull Percentage"* — it already exists as approved
  audit-only context (GM-020 ruling; GM-030-r1 blue card). Interpreted as
  "no new surface"; the frozen baseline behavior is preserved unchanged.
- *Idempotency vs. immutable publication* — resolved by compare-then-verify
  around the unchanged `publish_bundle`; nothing is ever overwritten.

## Multi-player model

Exactly what manifest v1 supports and ruling 2 requires: **independent
one-hitter v1 bundles**, one per selection, each independently verified,
replayable, and visible in the existing run selector. The live evidence
demonstrates it: two independent real prospective bundles side by side
(Devers/823196 from GM-020, Ohtani/823600 from GM-040), discovered together
with no dashboard-code change.

## Guard closed

The `validation` package placeholder identified in the readiness memo is now
enforced alongside `scoring`/`features`/`cli` in both placeholder guards.

## Deferred (explicitly not implemented)

Full slate aggregation and slate navigation, Dashboard rankings, Pitchers /
Bullpens to Target, bullpen capture, Record Book, outcomes, any database,
weather, park-factor changes, UI redesign, scheduled/background jobs, and
all scoring behavior (no score, tier, recommendation, ranking, or betting
claim exists anywhere in a GM-040 artifact).
