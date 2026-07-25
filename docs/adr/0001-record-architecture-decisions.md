# ADR-0001 — Record architecture decisions

**Status:** Accepted
**Date:** 2026-07-22
**Implementing ticket:** GM-010

## Context

GreenMachine is intended to be maintained for years, with two clearly separated roles and a
grading model whose configuration will change many times. Decisions that are expensive to
reverse — storage format, numeric policy, identity strategy, layer boundaries — will otherwise
survive only as tribal knowledge or as code that nobody dares change because nobody remembers
why it is that way.

The project's core value is that a grading decision can be explained years later. The same
standard should apply to engineering decisions.

## Decision

We record architecture decisions as numbered Markdown files in `docs/adr/`, using the template
in `TEMPLATE.md`, with required sections Context / Decision / Consequences / Status.

Records are append-only. A decision that is later reversed gets a new ADR; the old one is marked
`Superseded by ADR-XXXX` and retained. An ADR is required for any decision that would be
expensive to reverse or that a future engineer would reasonably question.

ADRs record **engineering** decisions only. Baseball and product behavior lives in
`MODEL_SPEC.md`.

## Consequences

- The reasoning behind expensive decisions survives personnel and time
- Review has something concrete to check a design against
- Small cost per decision, and a discipline cost: the temptation is to skip the ADR and just
  write the code
- Automated tests verify ADR structure and status validity, so the format cannot silently rot

## Alternatives considered

- **Wiki or external doc tool** — drifts from the code, not versioned with it, not reviewable in
  a pull request
- **Comments in code** — invisible when the code is deleted, and cannot capture rejected
  alternatives
- **No formal record** — the default, and the reason most projects cannot explain themselves
