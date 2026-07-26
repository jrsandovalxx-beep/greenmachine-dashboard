# GM-040 operator report

**Classification:** prospective

prospective capture: every participating retrieval and the run completion precede the scheduled first pitch, proven from recorded manifest instants and re-proven on every replay

## Selection
- slate date: 2026-07-26
- game: `823194` at Oracle Park
- hitter: Jorge Soler (MLBAM `624585`)
- lineup status (operator-supplied): **confirmed**
- capture mode: PROSPECTIVE
- expected-pitcher cross-check: not supplied (feed resolution accepted)

## Resolved expected pitcher
- Carson Whisenhunt (MLBAM `687931`), expected_starter

## Timing (recorded instants only)
- scheduled first pitch (UTC): 2026-07-26T20:05:00+00:00
- latest participating capture completion: 2026-07-26T18:54:17.627272+00:00
- run completed: 2026-07-26T18:54:17.853096+00:00
- captured before scheduled start: true

## Identities
- manifest_id: `capture_manifest-831f55ec726d28cafa05252efc35d3985b25048612ea7fc89e80e8c9cc0fdec6`
- source_capture_id: `source_capture-000fa4b74afbbb295bec1d0790d15760d8c613873b2ea6d8398a07df867210d5`
- RECENT_7D snapshot: `input_snapshot-37d155d2880a291d0e3f42e822f2cb48d6cb37f0bdcad07d636b72d3e3531562`
- LONG_TERM_2Y snapshot: `input_snapshot-4c0bd7f9b3fe641b831de151f5877dcf96db049763bb7fa782b322d0046c2700`

## Notes
- lineup status is operator-supplied metadata recorded in this report only; it participates in no manifest-v1 identity, snapshot, or archived report
- no score, tier, recommendation, ranking, or betting claim is produced by this run

Replay offline with:
```
python scripts/run_gm040_real_slice.py replay --run-dir <this run directory>
```
