# GM-020 live prospective capture — evidence notes

## Selection

- **Slate date:** 2026-07-24 (the capture day's official MLB date).
- **Game:** `gamePk` **823196**, Los Angeles Angels at San Francisco Giants,
  Oracle Park, scheduled first pitch 2026-07-25T02:15:00Z (19:15 venue-local,
  `America/Los_Angeles`). Regular season (`gameType == "R"`).
- **Why this game:** at selection time (~21:45Z) fourteen regular-season games
  on the slate were still pregame. This one had the largest margin before first
  pitch (~4.5 hours), the strongest guarantee that the capture is genuinely
  prospective, and both probables were conventional named starters with no
  opener or uncertainty notes.
- **Batter:** Rafael Devers, MLBAM **646240** (Giants, home side). Chosen from
  the pregame boxscore roster as the position player with the strongest tracked
  coverage in the trailing week (14 batted-ball events, 61 tracked attack-angle
  rows in the 7-day window), so every event-derived metric would exercise a
  real sample.
- **Expected pitcher (resolved by the slice, not pre-selected):** Grayson
  Rodriguez, MLBAM **680570**, away probable, role `EXPECTED_STARTER`, no note.
- **Sample policy:** the non-production validation fixture
  `tests/fixtures/ingestion/gm020_nonproduction_sample_policy.json`, carrying
  its own disclaimer. Production minimums remain open under Q14. The exact
  policy bytes are archived inside the bundle at
  `inputs/sample_minimum_policy.json` and digest-pinned by
  `inputs/replay_inputs.json`, so the published run is self-contained.

## Timeline (UTC, 2026-07-24)

1. ~21:45 — slate surveyed; game and batter selected; game state `Preview` /
   `Scheduled`.
2. ~21:46 — **first capture attempt failed closed** (runner exit 3) on real
   provider schema drift: see `SCHEMA_DRIFT_INCIDENT.md` for the sanitized
   incident record, the correction, and the regression protection. Nothing
   was published.
3. ~21:47 — contract and synthetic fixture corrected; suites re-run green.
4. 21:47:51 — **second capture attempt published** (`prospective_run/`,
   runner exit 0). Every capture succeeded on attempt 1 of 3; no retries were
   consumed. All recorded completions precede the scheduled first pitch by
   roughly 4.5 hours, satisfying the recorded-instant prospective timing
   rules.
5. Offline replay (runner exit 0): `raw_digests_verified: true`, both
   snapshots regenerated **byte-identically** with no network access.

## GM-020-r1 regeneration (offline)

Both snapshots and the reports were regenerated **offline** from the original
archived raw bytes and recorded retrieval instants, applying the r1
corrections (IAA-only fallback provenance; coordinated `as_of` anchored to the
latest participating completion; archived digest-pinned replay inputs). No
raw byte, retrieval instant, HTTP status, request parameter, digest, capture
mode, or selection changed:

- `manifest.json` — **byte-identical** to the original publication (same
  `manifest_id`).
- All five raw artifacts — **byte-identical** (same SHA-256 digests).
- `SourceCaptureId` — **unchanged**.
- Coordinated `as_of` — `2026-07-24T21:47:46.664183+00:00` (the long-term
  batter capture's completion, the latest participating instant; the
  audit-only pitcher capture and the later `run_completed_at`
  `21:47:51.806672Z` deliberately do not contribute).
- Snapshot ids — **new**, because the corrected `as_of` and fallback
  provenance change canonical snapshot content:
  - recent: `input_snapshot-f0d4ba53401fa47f24c7d522b46ad58b231fc4a4b9ceeeca815bd72f68497a73`
  - long-term: `input_snapshot-9de3b0e742e90d07e4d30851f30ca2cffb63f1a98f5ab43e8fb978493ec45c53`
- Prospective eligibility re-validated from recorded instants: zero blockers.
- Offline replay of the regenerated bundle: byte-identical.

## GM-020-r2 regeneration (offline)

`manifest_identity` was widened to cover the **complete** canonical manifest
content (every published field, with recomputed capture identities), so
`manifest.json` was regenerated with the new identity. Nothing else changed:
raw bytes, digests, recorded instants, `SourceCaptureId`, both snapshot
files (byte-identical to r1, same ids and hashes), and the archived policy
bytes are all untouched — the regeneration diff against r1 is exactly
`manifest.json` plus the recomputed replay report. Prospective eligibility
and the v1 semantic contract were re-validated from the recorded values.

## Published run identity

- `manifest_id` (complete-content projection, r2):
  `capture_manifest-2023883387eec9adb4a2b72a65248535923241dccc92727311db7cd7a5cb1880`
- `source_capture_id`:
  `source_capture-fc3344425547eb728643e834b563f41156f060efb24e9fd171f0b427327db6c9`
- Participating captures: `mlb_schedule`, `mlb_game_feed`,
  `batter_events_recent_7d`, `batter_events_long_term_2y`. The
  `pitcher_events_season` capture is present and audit-only (non-participating).

## Snapshot summary (Devers, event-derived, exact Decimal)

| Component | RECENT_7D | n | LONG_TERM_2Y | n |
|---|---|---:|---|---:|
| exit_velocity | 92.79285714… | 14 | 92.84915048… | 824 |
| barrel_pct | 0 | 14 | 13.47087378… | 824 |
| hard_hit_pct | 42.85714285… | 14 | 53.39805825… | 824 |
| sweet_spot_pct | 21.42857142… | 14 | 35.92233009… | 824 |
| bat_speed | 72.67377049… | 61 | 70.17603305… | 2,662 |
| attack_angle_quality (IAA%) | 55.73770491… | 61 | 56.42374154… | 2,662 |
| pull_pct_air_balls | 16.66666666… | 6 | 30.29612756… | 439 |

Only `attack_angle_quality` carries a `FallbackRecord` (the official IAA
aggregate hierarchy it bypasses); every other present observation has
`fallback_used = null`. Missing in both profiles, as specified:
`pitch_mix_pressure` and `put_away_pitch_exploitation` (interim
`SOURCE_UNAVAILABLE` — the provider transport succeeded and the audit
ingredients exist; the Q15/Q16 formulas are undefined and nothing was
manufactured), `park` (`SOURCE_UNAVAILABLE`), `weather`
(`WEATHER_UNAVAILABLE`, `weather_is_forecast: false`). Both snapshots share
the `source_capture_id` above and have distinct `snapshot_id` / `input_hash`
values.

This capture is **prospective**: every recorded participating completion and
the run completion precede the scheduled first pitch, both provider statuses
were pregame with agreeing scheduled starts, and the timing is re-proven from
the recorded manifest instants on every replay.
