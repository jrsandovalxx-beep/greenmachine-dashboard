# ADR-0008 — Golden testing strategy

**Status:** Accepted
**Date:** 2026-07-24 (proposed) · 2026-07-24 (accepted on delivery of GM-008)
**Implementing ticket:** GM-008

*(The Sprint 1 plan originally listed this ADR as `0005-golden-testing-strategy.md`; ADR-0005
was assigned to the window-profile architecture on delivery of GM-006, and ADRs are never
renumbered, so the golden-testing decision is recorded here as ADR-0008 by Product Owner
ruling.)*

## Context

Every future scoring change must be an explicit, reviewable diff. The frozen GM-006 contracts
make a `GradeResult` byte-identical for identical inputs, and GM-005 makes serialization
canonical — but nothing yet turns "the score changed" into "a reviewer saw exactly which field
changed and approved it." That is the golden harness's job, and it must exist **before** the
scoring engine does, so the engine is born under test.

Two hazards shape the design. First, golden suites rot when updating them is easier than
reading them — a self-healing suite approves its own regressions. Second, GreenMachine's
profile rules (ADR-0005) are exactly the kind of invariant a lazily built fixture tree
violates silently: one shared snapshot graded under two profiles would pass tests while
breaking the model.

## Decision

**Directory-based, profile-specific golden cases.** A case is one directory under
`tests/golden/cases/` holding a strict five-field `case.json` manifest, one canonical
`InputSnapshot` record, and one canonical expected `GradeResult` record. The golden contract is
`InputSnapshot + config version reference -> GradeResult`. `case_id` is a documented lowercase
ASCII stable identifier (`^[a-z][a-z0-9_-]*$`), enforced at loading and at direct construction.
Discovery is automatic and ordered by `case_id`; adding a case requires no runner change, and a
discovered case is **confined to its resolved root** — symlinked case directories and any
directory resolving outside the root are rejected, at discovery and again at the update-script
write boundary. **One case represents exactly one `WindowProfile`**, declared in the manifest
and verified against both typed records; one source capture may produce two cases (recent and
long-term) whose snapshots share a `source_capture_id` but keep distinct `snapshot_id`,
`input_hash`, windows, and observations.

**Canonical records, not a second format.** Golden files are the exact GM-006
`serialize_record` wrappers, decoded through the approved strict deserializers with snapshot
identity verification. The harness defines no parallel schema.

**An injected scorer boundary.** The runner takes any callable
`(InputSnapshot, config_version_identifier) -> EvaluatedGradeResult | NotEvaluableGradeResult`
and rejects every other result shape and any profile substitution. `run_case` stays strict and
raises for a single invalid execution; the batch `run_cases` records each case's outcome —
pass, canonical differences, or an execution failure (exception class name and message) — and
executes every remaining case, so one case never hides another. **GM-008 implements no
scoring**: only a clearly labeled test-only stub under `tests/golden/stub_scorer.py`, which
selects fixed synthetic values by profile, never inspects a metric value, and emits exactly one
insufficient-sample advisory per distinct component as the frozen result contract requires. No
scorer is selected globally; there is no registry and no environment lookup.

**Readable field-level diffs.** A mismatch reports every difference with its exact canonical
field path and exact rendered values (`payload.total_score: expected "9.999" / actual
"1.111"`), including missing-key, unexpected-key, type-mismatch, value-mismatch, and
result-variant cases. Decimals render as canonical base-10 strings; no binary float and no
object repr participate.

**Deliberate regeneration only.** `scripts/update_goldens.py` is the single golden write path:
explicit case targets (no update-all default), an explicit `module:function` scorer path,
atomic replacement of only each target's expected file, deterministic timestamp-free output.
Pytest never rewrites a golden; the runner has no update flag; architecture guards prove the
runner and golden suite contain no write operation.

**Fixed Hypothesis seed 20260724.** Property tests run under the explicit fixed seed
**20260724**, supplied through Hypothesis's supported pytest mechanism
(`--hypothesis-seed=20260724` in `pyproject.toml` `addopts`) — a stable constant, never a
random or clock-derived value in CI. The `greenmachine-ci` profile keeps `database=None`,
`deadline=None`, explicit `max_examples=50`, and no suppressed health checks;
`derandomize` stays `False` deliberately, because Hypothesis prefers derandomization over a
forced seed and the explicit seed is the configured mechanism. Deliberate local overrides are
`--hypothesis-seed=<N>` for another explicit seed and
`--hypothesis-profile=greenmachine-exploratory --hypothesis-seed=random` for exploration.

**Suite-wide network blocking, including child processes.** An autouse session fixture fails
every network operation immediately — TCP/stream connections (`connect`, `connect_ex`,
`create_connection`), datagram sends (`sendto`, and `sendmsg` where available), and name
resolution (`getaddrinfo`, `gethostbyname`, `gethostbyname_ex`, `gethostbyaddr`) — IPv4 and
IPv6, always before DNS or any packet, with no opt-out flag and no environment escape hatch.
Child Python processes inherit an equivalent guard through an **explicit bootstrap**: every
test-spawned Python child runs through `tests/network_guard/child_bootstrap.py` (via the
centralized `tests.network_guard.guarded_child` launcher), which installs the guard before the
child payload executes — portably, even when a competing `sitecustomize` appears earlier on
`sys.path`, a condition covered by regression tests. An architecture guard confines
`sys.executable` to the launcher so no unguarded child invocation exists; the `sitecustomize`
shim in the same directory is retained as secondary defense only. Execution failures recorded
by the batch runner are rendered deterministically from exception arguments alone (class name
plus plain-string/primitive arguments or stable type names) — never from `repr`, custom
`__str__`, or anything that could embed a memory address.

**Synthetic-only fixtures.** Every golden value is visibly synthetic; no production threshold,
allocation, sample minimum, or real player/game/provider datum may appear. Architecture tests
scan the committed cases for the synthetic markers and the single-profile rule, and the new
GM-008 files for clock reads, environment access, raw randomness, and network/database imports
— each guard proven against seeded violations.

## Consequences

- Any scoring change surfaces as an explicit fixture diff a reviewer must approve; an
  unreviewed behavioral change cannot land silently once the Sprint-2 engine is injected.
- Golden updates require deliberate developer action with named targets and a named scorer;
  the suite never self-heals, so a stale expectation always fails the build.
- One source capture may carry separate recent and long-term cases, so profile separation is
  exercised — not just asserted — by the committed tree.
- The future scoring engine replaces the stub through the existing `GoldenScorer` boundary
  without redesigning the runner, the case format, or the update script.
- Golden fixtures are test data, never production configuration: production thresholds still
  arrive only as approved, versioned configuration under MODEL_SPEC §20.
- The cost accepted: committed canonical records are verbose, and deliberately so — byte-exact
  fixtures are what make drift visible and review meaningful.
