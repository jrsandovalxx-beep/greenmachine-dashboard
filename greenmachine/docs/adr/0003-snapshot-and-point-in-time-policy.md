# ADR-0003 — Snapshot and point-in-time policy

**Status:** Accepted
**Date:** 2026-07-22 · amended under specification v6.3 · accepted on delivery of GM-006
**Implementing ticket:** GM-006

## Context

Deterministic code over drifting inputs is still non-reproducible. Three concrete failure modes:

- **Weather** is a forecast at grading time and an observation afterward
- **Providers revise data**; season-to-date aggregates move daily
- **Rolling windows** computed from a current aggregate table leak future data into backtests

Any of these breaks replay and quietly inflates backtest results — the most dangerous kind of
bug, because the output still looks plausible.

## Decision

**The unit of reproducibility is the frozen `InputSnapshot`, not the code.**

- **One `InputSnapshot` represents exactly one `WindowProfile`.** A snapshot may never contain
  or produce both profiles. One source capture may produce two independently frozen
  profile-specific snapshots, sharing a `source_capture_id` but with distinct `snapshot_id`,
  `input_hash`, `window_profile`, `window_start`, `window_end`, and observations (ADR-0005)
- All inputs are assembled, frozen, and content-hashed before entering the grading core
- The core is structurally unable to fetch anything: no I/O, no network, no provider imports,
  enforced by import-boundary tests
- For an evaluation with `as_of` = T, no event or observation dated after T may enter it — for
  any metric, under any profile, including pitcher season data and weather
- Weather is the grading-time forecast frozen at or before T; observed weather never enters an
  evaluation
- Rolling windows are reconstructed from **event timestamps**, never recomputed from a current
  aggregate table
- Partial coverage is preserved and visible: requested period, actual period, coverage status,
  source availability, sample count
- The point-in-time filter is a pure function of `(events, as_of, profile)`, unit-tested with
  events exactly at T and at both window edges
- Backtests read archived snapshots; a backtest that re-queries a provider is not a backtest

**Source eligibility outranks source priority.** An acquisition method is *eligible* only if it
can produce the exact selected profile, the correct `window_start` and `window_end`, using no
observation after T. Feature assembly selects the highest-priority **eligible** method, not the
highest-priority available one, and records why each higher-priority method was ineligible.

The practical consequence is that the same component may legitimately resolve through different
acquisition methods for today's slate and for a 2023 backtest: a current leaderboard aggregate
can satisfy today's seven-day window but cannot reproduce a historical `as_of` window, so
event-level derivation may be the highest eligible method for historical evaluations. Source
priority is a preference; point-in-time correctness is a constraint, and constraints win.

## Consequences

- Replay, backtesting, simulation, and configuration comparison all become possible from one
  mechanism
- Storage cost grows with the number of snapshots, and roughly doubles again because each
  profile is frozen separately; accepted, and cheap relative to the guarantee
- Backtests and today's slate may resolve the same component through different acquisition
  methods. That is correct behaviour, but it means research must be able to segment results by
  `acquisition_method`, which is why the field is preserved on every observation
- Feature assembly is more work than reading an aggregate table, and event-level history must be
  retained
- A bug in the point-in-time filter is now a single, testable, high-value target rather than a
  diffuse property of the system

## Alternatives considered

- **Re-fetch on replay** — simplest, and silently wrong the moment a provider revises data or a
  forecast becomes an observation
- **Snapshot only volatile inputs** — requires correctly predicting which inputs are volatile;
  the failure mode is silent
- **Trust provider "as-of" endpoints** — not universally available, and not verifiable by us
