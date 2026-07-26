# GM-040 operator report

**Classification:** prospective

prospective capture: every participating retrieval and the run completion precede the scheduled first pitch, proven from recorded manifest instants and re-proven on every replay

## Selection
- slate date: 2026-07-26
- game: `823194` at Oracle Park
- hitter: Jose Siri (MLBAM `642350`)
- lineup status (operator-supplied): **confirmed**
- capture mode: PROSPECTIVE
- expected-pitcher cross-check: not supplied (feed resolution accepted)

## Resolved expected pitcher
- Carson Whisenhunt (MLBAM `687931`), expected_starter

## Timing (recorded instants only)
- scheduled first pitch (UTC): 2026-07-26T20:05:00+00:00
- latest participating capture completion: 2026-07-26T18:54:49.779158+00:00
- run completed: 2026-07-26T18:54:49.938926+00:00
- captured before scheduled start: true

## Identities
- manifest_id: `capture_manifest-f04ca68ad649de7323df9c7a7d896ee388441cafbe4e510d636bee7298571ef8`
- source_capture_id: `source_capture-26232e06f5d2f901126effc98264e20b5c140cc7d323eb6291b83696eec17b71`
- RECENT_7D snapshot: `input_snapshot-be33348b196fb9c26946020c32a7b8ca8a8d100f753452bf96df645d00be075a`
- LONG_TERM_2Y snapshot: `input_snapshot-a003a954754e0982cbd9129994a568df016178127f406be8db2707ca160ac836`

## Notes
- lineup status is operator-supplied metadata recorded in this report only; it participates in no manifest-v1 identity, snapshot, or archived report
- no score, tier, recommendation, ranking, or betting claim is produced by this run

Replay offline with:
```
python scripts/run_gm040_real_slice.py replay --run-dir <this run directory>
```
