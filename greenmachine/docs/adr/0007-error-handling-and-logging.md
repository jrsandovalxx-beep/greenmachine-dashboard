# ADR-0007 — Error handling and structured logging

**Status:** Accepted
**Date:** 2026-07-22 (proposed) · 2026-07-22 (accepted on delivery of GM-009)
**Implementing ticket:** GM-009

## Context

GreenMachine's correctness depends on failing loudly. A swallowed exception, a default-to-zero,
or a partially parsed provider response produces a grade that looks right and is wrong — the
worst outcome for a system whose entire value proposition is trustworthy explanation.

Ingestion makes this acute: a Savant leaderboard column rename should stop the pipeline, not
quietly produce zeros for a metric.

Logging carries a second, subtler risk: anything that logs inside the grading core could, if
carelessly written, alter behavior or ordering.

## Decision

**Typed error hierarchy** rooted at `GreenMachineError`, with distinct branches for configuration,
data/input, domain-invariant, ingestion/source, and persistence failures. Every error carries
structured context — file, key path, metric, profile, subject — not just a message string. The
ingestion branch includes a schema-change error type that adapters must raise loudly.

**Prohibited:** bare `except Exception`, swallowed exceptions, defaulting missing data to zero,
and silently returning empty results from an adapter. The bare-except prohibition is enforced by a
CI lint rule, not by review attention.

**Structured logging** in key–value/JSON form, with records carrying `model_version`,
`config_hash`, `input_hash`, and `window_profile` where available, so any log line can be tied
back to a reproducible evaluation.

**Logging is observational only.** It never mutates state, never alters control flow, and the
grading core does not log in any way that could vary its output. Log level is configurable and
defaults to quiet.

## Consequences

- Failures are diagnosable from the record alone, without reproducing the run
- Provider schema changes stop the pipeline instead of corrupting a slate
- More error types to define and maintain, and more verbose raise sites
- Structured context must be threaded through call sites, which is mildly tedious and pays for
  itself the first time an evaluation fails in production

## Alternatives considered

- **Standard library exceptions with message strings** — cheap, and unparseable; context gets
  formatted into prose and lost
- **Result/Either return types throughout** — explicit but noisy in Python, and easy to ignore at
  the call site
- **Lenient ingestion with quality flags** — tempting for uptime, and precisely how zeros become
  grades; rejected in favor of `NOT_EVALUABLE`
