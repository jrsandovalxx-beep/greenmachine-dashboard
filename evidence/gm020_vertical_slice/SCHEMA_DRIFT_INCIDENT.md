# Schema-drift incident during the GM-020 live prospective capture

On 2026-07-24 (~21:46Z), the first live prospective capture attempt for
gamePk 823196 **failed closed** with:

```
SchemaDriftError: MLB response field 'liveData.boxscore.teams.home.player'
does not match the schema contract
```

## What happened

- The coded MLB live-feed contract expected the boxscore roster containers at
  `liveData.boxscore.teams.<side>.player`.
- The real MLB Stats API v1.1 feed carries them at
  `liveData.boxscore.teams.<side>.players` (verified directly against the
  live payload).
- The synthetic test fixture had encoded the same incorrect assumption as the
  parser, which is why the full suite could not catch it.

## What the system did

Exactly what the fail-closed rules require: the run **published nothing** —
no manifest, no `SourceCaptureId`, no snapshots. The runner exited with the
not-published code and reported the exact blocker. (The failed attempt's raw
bytes were preserved at the time under `failed_run/` per the
no-partial-publication design; that transient raw bundle is not shipped in
the release artifact — this document is the durable record, and the
fail-closed behavior itself is covered by the test suite.)

## Correction

- `src/greenmachine/ingestion/mlb/parser.py`: the required-field contract and
  roster extraction corrected to `...teams.<side>.players`.
- `tests/fixtures/ingestion/synthetic_provider_fixtures.py`: the fixture
  corrected to match the verified real payload, with a comment recording the
  live verification.

## Regression protection

- The corrected required-path set is exercised by
  `tests/unit/ingestion/test_mlb_parser_and_pitcher.py` (roster parsing and
  the fail-closed missing-required-field cases now run against the corrected
  path).
- The archived live feed bytes in `prospective_run/raw/mlb_game_feed.json`
  carry the real structure, and every offline replay re-parses them under the
  strict contract — so a regression to the wrong path would fail replay
  immediately.

The second capture attempt (~90 seconds later, still ~4.5 hours before first
pitch) parsed cleanly and published; see `CAPTURE_NOTES.md`.
