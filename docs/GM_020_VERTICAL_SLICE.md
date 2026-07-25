# GM-020 — Thin production ingestion vertical slice

**Status:** implemented (code version 0.2.0).
**Scope:** one slate date, one game, one hitter, one expected starting pitcher.
**Not in scope:** scoring, full-slate orchestration, weather and park sourcing,
bullpen modelling, dashboards, and durable storage adapters.

This document is the engineering reference for the first production path from a
real provider response to a frozen `InputSnapshot`. It records what the slice
does, which provider semantics are frozen, which are interim, and how any run is
replayed offline and byte-for-byte.

---

## 1. What the slice produces

A single coordinated capture yields **two independently frozen snapshots** — one
`RECENT_7D`, one `LONG_TERM_2Y` — that share one `source_capture_id` and differ
in `snapshot_id`, `input_hash`, window bounds, and observations. That is the v6.3
rule "one source capture may produce two profile-specific snapshots", realised
against live data for the first time.

Both snapshots share one coordinated **`as_of`**: the latest
`retrieval_completed_at` among the **participating** captures. The audit-only
pitcher capture never participates, so neither its timing nor its bytes can
alter either hitter snapshot — proven by tests that perturb only the pitcher
capture and assert byte-identical snapshots. Per-profile
`source_as_of`/`retrieved_at` still come from that profile's own batter
capture, and `manifest.run_completed_at` remains global operational audit
metadata only.

Alongside them, the run publishes the raw provider bytes it derived them from,
an immutable manifest, and audit reports. Nothing is scored: the slice stops at
the snapshot boundary.

---

## 2. Architecture and dependency boundaries

```
scripts/run_gm020_vertical_slice.py     composition root: the only place that
  │                                     constructs SystemClock, UrllibTransport,
  │                                     SystemSleeper, and a sample-minimum policy
  ▼
ingestion/orchestration.py              pure coordination over injected ports
  ├── ingestion/capture.py              retry/attempt accounting (never raises)
  ├── ingestion/{mlb,savant}/client.py  request construction (URLs, parameters)
  ├── ingestion/{mlb,savant}/parser.py  strict schema contracts → neutral records
  ├── ingestion/events.py               window, game-type, duplicate, identity rules
  ├── ingestion/savant/metrics.py       event-derived metrics, exact Decimal
  ├── ingestion/mapping.py              neutral records → frozen domain contracts
  ├── ingestion/manifest.py             content-derived identities
  └── ingestion/archive.py              atomic publication + confined reading
```

Enforced by `tests/architecture/test_ingestion_boundaries.py`:

- `domain` and `common` never import `ingestion`; `ingestion` never imports
  `scoring`, `features`, `reporting`, `cli`, or `config`.
- Provider **wire keys** (`gamePk`, `hc_x`, `bb_type`, `hfGT`, …) appear only in
  `client.py` and `parser.py` modules. Ingestion-internal records deliberately
  keep Statcast column names as *field* names so a value can be traced to its
  source column; that vocabulary stops at the mapping boundary and never reaches
  `domain`.
- `SystemClock` is never instantiated inside `src/`; the concrete transport is
  imported only by the runner script.
- No `float` literal, call, or annotation exists anywhere in `ingestion`.
- No `SampleMinimumPolicy` is constructed inside `src/` — it is always injected.
- `scoring`, `features`, `reporting`, and `cli` remain docstring-only.

The suite-wide network block still applies: no test performs I/O against a
provider. Every test drives a `FakeTransport` over recorded synthetic bytes.

---

## 3. Capture lifecycle

1. **Fetch.** Each provider request is fetched through the injected transport
   under an explicit `RetryPolicy` (timeout, **maximum 3 attempts**, fixed
   backoff tuple — no jitter, because jitter is nondeterminism). Retryable:
   transport failures, `429`, and `500/502/503/504`. A `Retry-After` header is
   honoured when it is an integer, capped at 120 seconds. Every attempt is
   recorded — index, start, completion, outcome, status, error category.
2. **Assemble in memory.** Nothing is written until the whole run succeeds.
3. **Eligibility.** Game type, schedule status, identity agreement, and (in
   prospective mode) pregame state are checked. Any blocker ends the run.
4. **Publish atomically and path-safely.** Every destination in the complete
   file plan passes one centralized bundle-relative path validator **before
   anything is created**: forward-slash relative paths only — no absolute
   paths, no `.`/`..`/empty segments, no backslashes, drive prefixes, colons,
   or NUL characters, and no duplicate destinations (including
   case-insensitive collisions and file/directory collisions). A validation
   failure writes nothing, inside or outside the run. `publish_bundle` then
   writes a staging directory — re-verifying each resolved destination
   against the staging root, so symlink tricks cannot redirect a write — and
   moves it into place with one `os.replace`. A published run directory is
   **immutable**: re-publishing to the same path is refused. The release
   archive builder runs its own file plan through the same validator.
5. **Failures never publish.** A failed run writes only under `failed_run/`,
   preserving the raw bytes that *did* arrive plus `eligibility.json` and
   `attempts.json`. No manifest and no snapshots are produced, so a partial
   capture can never be mistaken for a usable one.

### Published bundle layout

```
manifest.json   strict GreenMachine-owned document; embeds a capture_id per
                entry and the overall manifest_id, both re-verified on replay
raw/            mlb_schedule.json, mlb_game_feed.json,
                batter_events_recent_7d.csv, batter_events_long_term_2y.csv,
                pitcher_events_season.csv
inputs/         sample_minimum_policy.json (the exact supplied policy bytes,
                verbatim) and replay_inputs.json (schema version, the policy's
                run-relative path and SHA-256, its non-production
                classification and disclaimer)
snapshots/      input_snapshot_recent_7d.json, input_snapshot_long_term_2y.json
reports/        eligibility.json, normalization_recent_7d.json,
                normalization_long_term_2y.json, normalization_pitcher_season.json,
                schema.json, pull_audit_recent_7d.json,
                pull_audit_long_term_2y.json, pitcher_ingredients.json,
                limitations.json
                (replay.json is added once, by a later replay)
```

A published bundle is **self-contained**: a copied run directory alone is
sufficient for replay. The archived policy is not a provider capture — it is
never represented as a `RawCaptureEntry` and its digest never enters the
domain `SourceCaptureId`.

---

## 4. Identity

All identifiers are content-derived; none uses UUIDs, randomness, wall-clock
time at derivation, or filesystem paths.

- **Capture entry identity** — deliberately narrow: provider, endpoint, sorted
  parameters, completion instant, HTTP status, body digest.
- **Manifest identity** — the **complete** canonical manifest content: every
  published field at the top level and per entry (attempt histories, schema
  fingerprints, contract versions, content types, artifact paths,
  participation flags, error categories), excluding only the recorded
  `manifest_id` itself, with each entry's `capture_id` recomputed rather than
  trusted. Changing any published manifest field changes the `manifest_id`.
- **`SourceCaptureId`** — derived from the sorted `(label, sha256)` pairs of the
  **participating** captures only. The pitcher capture is audit-only and does
  **not** participate, so pitcher-side changes never perturb snapshot identity.
  A byte-identical re-fetch may therefore legitimately retain its
  `SourceCaptureId` while remaining a distinct manifest.

Moving an artifact does not change any identity; changing one participating byte
changes the `SourceCaptureId` and both snapshots.

---

## 5. Frozen date and game-type policy

- **Regular season only.** Only `game_type == "R"` rows are eligible. Every
  excluded row is counted by type in the normalization report, and a **missing**
  game type is never treated as regular season.
- **Windows are half-open** in slate-local terms: `RECENT_7D` is
  `[slate − 7, slate)`; `LONG_TERM_2Y` is `[slate − 730, slate)`. The slate date
  itself is always excluded — a snapshot may not contain information from the
  game being evaluated.
- Provider requests are stated **inclusively** and end at `slate − 1`, which is
  the same set of days; the half-open bound remains the contract.
- The selected game is excluded unconditionally, and counted.
- `slate_date` is the provider's official date. It is never derived from UTC.

---

## 6. Frozen metric definitions

| Metric | Definition | Denominator |
|---|---|---|
| Exit velocity | exact mean of tracked `launch_speed` | batted-ball events with a value |
| Barrel % | official bucket `launch_speed_angle == "6"` | classified batted-ball events |
| Hard-hit % | `launch_speed >= 95` | batted-ball events with a value |
| Sweet-spot % | launch angle in `[8, 32]` **inclusive** | batted-ball events with a value |
| Bat speed | exact mean of tracked values | swings with tracking |
| Ideal Attack Angle % | attack angle in `[5, 20]` **inclusive** | **all** rows with a tracked attack angle |
| Pull % (air balls) | pulled by geometry | `fly_ball` + `line_drive` with valid stand and coordinates |

Two definitions deserve emphasis:

**Ideal Attack Angle % is swing-level, not batted-ball-level.** Its denominator
is every row carrying a tracked attack angle, including swings without contact.
It is event-derived and is *not* the published leaderboard aggregate; the
difference is recorded in `reports/limitations.json`.

**Pull % (air balls) uses a frozen initial denominator** of `fly_ball` +
`line_drive`. Pull is classified per row from that row's own `stand` value —
correct for switch hitters — using exact Decimal geometry from the Savant
coordinate frame:

```
y          = HOME_PLATE_Y − hc_y                 (must be > 0 to be usable)
pull_side  = HOME_PLATE_X − hc_x   for a right-handed stand
             hc_x − HOME_PLATE_X   for a left-handed stand
pulled     ⇔ pull_side >= TAN_15_DEGREES × y
HOME_PLATE_X = 125.42   HOME_PLATE_Y = 198.27
TAN_15_DEGREES = 0.26794919243112270647
```

The boundary is **inclusive on the pull side**. `reports/pull_audit_*.json`
additionally reports fly-ball-only, fly+line+popup, and overall-pull variants so
the denominator choice can be revisited with evidence — those alternatives are
**audit-only** and never enter a snapshot. Overall Pull % is likewise
report-only.

---

## 7. Prospective versus retrospective capture

**Prospective** is the production mode, and it is proven from **recorded
instants**, never from the current time. Before publication — and again on
every replay, from the manifest's recorded values — a prospective run
requires:

- pregame abstract state in **both** the schedule and the live feed, and no
  postponement;
- the schedule's and the feed's scheduled first-pitch instants **equal**;
- `manifest.run_completed_at` strictly before the scheduled start;
- every capture entry completed at or before `run_completed_at`;
- every **participating** capture completed strictly before the scheduled
  start (completion exactly at first pitch fails);
- the coordinated `as_of` strictly before the scheduled start.

Each failure family has one deterministic blocker string, and a stale
"Preview" status cannot bypass the timing rules. Because only recorded
instants participate, the current date and the replay date never affect the
verdict. This is the only mode that produces genuine point-in-time evidence.

**Retrospective reconstruction** is permitted for validation and backtests. Such
a run is labelled in its manifest and carries a verbatim disclaimer in
`reports/limitations.json` stating that it was reconstructed after the fact and
is not evidence of prospective capture. A retrospective run is never presented
as prospective.

---

## 8. Interim mappings and known limitations

These are recorded in every bundle's `reports/limitations.json`:

- **Pitch-matchup composites** (`pitch_mix_pressure`, `put_away_pitch_exploitation`)
  are missing under the **interim, explicitly temporary** `SOURCE_UNAVAILABLE`
  label pending **Q15/Q16**. The facts behind that label: the provider
  **transport succeeded**, the underlying pitcher ingredients — per stand and
  pitch type: usage %, two-strike counts, putaway finishes — were captured and
  reported transparently, no approved component formula exists, and no
  component value was manufactured. The label is the closest frozen
  `MissingReason` for a derivation that does not exist yet; it does **not**
  claim the Savant provider was unreachable. Whether a dedicated
  derivation-pending missing reason should exist remains an open Product Owner
  decision alongside Q15/Q16; no vocabulary change was made in GM-020.
- **Park** is missing with `SOURCE_UNAVAILABLE`; no park-factor source is
  selected in this slice.
- **Weather** is missing with `WEATHER_UNAVAILABLE`, and `weather_is_forecast`
  is `False`.
- **Sample minimums are injected, never defaulted.** Production minimums are
  **Q14**, still open. The slice ships a clearly labelled non-production JSON
  fixture (`tests/fixtures/ingestion/gm020_nonproduction_sample_policy.json`)
  whose own disclaimer states it exists only to exercise the pipeline and must
  be replaced when Q14 is answered. There is no default anywhere in `src/`, so a
  run cannot silently adopt an invented minimum.
- **Expected-pitcher role** follows the provider's note: an announced opener maps
  to `OPENER`, uncertainty markers map to `UNCERTAIN`, and an unnamed pitcher is
  an eligibility failure. No placeholder pitcher is ever fabricated.
- All present observations use `AcquisitionMethod.EVENT_DERIVED`. **Only Ideal
  Attack Angle % carries a `FallbackRecord`**: it is the one GM-020 metric with
  an approved higher-priority acquisition hierarchy (the official published
  aggregate) that event derivation deliberately bypasses, and its record names
  exactly the methods preceding `EVENT_DERIVED` in the IAA hierarchy — direct
  aggregate, structured extract, rendered scrape — each with an IAA-specific
  ineligibility reason (per v6.3, eligibility outranks priority). The other
  metrics are event-derived by definition in this slice with no bypassed
  hierarchy, so their `fallback_used` is `None` — attaching the IAA hierarchy
  to them would be false provenance.

---

## 9. Schema drift

Required fields are a contract. A missing required field, a changed required
type, malformed JSON, or malformed CSV **fails the run closed** with
`SchemaDriftError` (a `ProviderSchemaChangeError`); nothing is published.
Additive change is accepted and audited: unknown columns and unknown JSON keys
do not fail, but a schema fingerprint over the selected paths and the sorted
header set changes, and `reports/schema.json` records it.

Duplicate event rows under one `(game_pk, at_bat_number, pitch_number)` key are
collapsed when identical and counted; a genuine conflict under one key is a
`ProviderResponseError`.

---

## 10. Replay procedure

Replay reads a published bundle and nothing else:

1. `manifest.json` is parsed under a **strict document contract**: duplicate
   JSON object keys are rejected at every nesting level (as they are for
   `replay_inputs.json` and the archived policy), exactly the required field
   set exists at every level (unknown or missing fields fail), parameter
   pairs must be two strings, attempts must be well-formed with consecutive
   ascending indexes, `participates_in_snapshot` must be an actual JSON
   boolean, optional fields are strictly `str | null` / `int | null`,
   duplicate labels fail, and incidental JSON/type/value problems surface as
   deterministic typed ingestion errors. No malformed member is skipped or
   coerced.
2. Every entry's recorded `capture_id` is recomputed and must match exactly —
   **before any raw artifact is parsed** — and the recorded `manifest_id`
   must match its recomputed complete-content identity.
3. The **v1 semantic contract** is enforced: exactly the five GM-020 labels
   with the exact participation split; positive canonical decimal game and
   batter identifiers; every entry's capture mode equal to the manifest's;
   unique artifact paths; successful 2xx responses with null error
   categories; a SUCCESS final attempt agreeing with the entry's status and
   completion; attempt instants within the run bounds; and each entry's
   request **byte-equal to the request GM-020 constructs** for the recorded
   slate/game/batter (the pitcher request is checked against the
   feed-resolved expected pitcher once the feed parses). A self-consistent
   digest over false request metadata is rejected.
4. Every raw artifact's digest and length are verified (one flipped byte
   fails).
5. The bundle's own archived sample policy is loaded from
   `inputs/sample_minimum_policy.json`, digest-verified against
   `inputs/replay_inputs.json` — whose classification, disclaimer, statement,
   schema version, path, and digest format are all validated for **exact
   values and types** — and parsed strictly. **No caller-supplied policy
   exists**: the runner's replay mode takes no policy argument, so a run can
   never be silently replayed under different minimums; a corrupted or
   substituted policy file fails digest verification.
6. A prospective run's recorded timing is re-validated from the manifest
   instants (never the current time).
7. Both snapshots are regenerated and compared byte-for-byte with the
   published files.

```bash
python scripts/run_gm020_vertical_slice.py replay --run-dir <published-run>
```

The command is **repeatable**: `replay_run` itself is read-only, and at the
report boundary a missing `reports/replay.json` is written atomically, an
existing byte-identical report succeeds without being rewritten, and an
existing *different* report fails closed and is never overwritten.

Exit codes: `0` success · `2` a GreenMachine error · `3` capture not published ·
`4` replay mismatch. Replay performs no network I/O, is independent of the
working directory, and is stable across `PYTHONHASHSEED` values and host
timezones — all verified in
`tests/integration/ingestion/test_replay_determinism_and_runner.py`,
`tests/integration/ingestion/test_manifest_and_replay_inputs.py`, and
`tests/integration/ingestion/test_manifest_semantics.py`.

Because `zoneinfo` has no bundled database on Windows, `tzdata` is a runtime
dependency. It is a deterministic, versioned data input, not a behavioral one.

---

## 11. Deferred work

Scoring, full-slate orchestration, weather and park sourcing, bullpen modelling,
reporting and dashboards, and durable storage adapters all remain out of scope.
The composites blocked on Q15/Q16 and the production sample minimums blocked on
Q14 are Product Owner decisions; engineering has invented no substitute for
either.
