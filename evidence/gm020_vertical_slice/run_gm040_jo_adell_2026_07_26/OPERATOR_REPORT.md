# GM-040 operator report

**Classification:** prospective

prospective capture: every participating retrieval and the run completion precede the scheduled first pitch, proven from recorded manifest instants and re-proven on every replay

## Selection
- slate date: 2026-07-26
- game: `823194` at Oracle Park
- hitter: Jo Adell (MLBAM `666176`)
- lineup status (operator-supplied): **confirmed**
- capture mode: PROSPECTIVE
- expected-pitcher cross-check: not supplied (feed resolution accepted)

## Resolved expected pitcher
- Carson Whisenhunt (MLBAM `687931`), expected_starter

## Timing (recorded instants only)
- scheduled first pitch (UTC): 2026-07-26T20:05:00+00:00
- latest participating capture completion: 2026-07-26T18:54:36.233347+00:00
- run completed: 2026-07-26T18:54:36.480974+00:00
- captured before scheduled start: true

## Identities
- manifest_id: `capture_manifest-5f107ff1a6164961d4689a6cdb69912afa89721b80f1465c97d4801c61d69fcd`
- source_capture_id: `source_capture-61b60c52b10f4c2cc68473534598c8ab5243812f4d37563396c05928423288a5`
- RECENT_7D snapshot: `input_snapshot-a0b81f64f7b6764f01912f71781624be25b1aba6118afa0bfacd67f6789231e2`
- LONG_TERM_2Y snapshot: `input_snapshot-b80876d0a97719288257f07a794a2145c2f9cf9f491a21caedf5706cd039b71d`

## Notes
- lineup status is operator-supplied metadata recorded in this report only; it participates in no manifest-v1 identity, snapshot, or archived report
- no score, tier, recommendation, ranking, or betting claim is produced by this run

Replay offline with:
```
python scripts/run_gm040_real_slice.py replay --run-dir <this run directory>
```
