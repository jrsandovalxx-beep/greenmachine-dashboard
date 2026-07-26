# GM-040 operator report

**Classification:** prospective

prospective capture: every participating retrieval and the run completion precede the scheduled first pitch, proven from recorded manifest instants and re-proven on every replay

## Selection
- slate date: 2026-07-26
- game: `823194` at Oracle Park
- hitter: Logan O'Hoppe (MLBAM `681351`)
- lineup status (operator-supplied): **confirmed**
- capture mode: PROSPECTIVE
- expected-pitcher cross-check: not supplied (feed resolution accepted)

## Resolved expected pitcher
- Carson Whisenhunt (MLBAM `687931`), expected_starter

## Timing (recorded instants only)
- scheduled first pitch (UTC): 2026-07-26T20:05:00+00:00
- latest participating capture completion: 2026-07-26T18:54:56.536679+00:00
- run completed: 2026-07-26T18:54:56.756251+00:00
- captured before scheduled start: true

## Identities
- manifest_id: `capture_manifest-6f90355fb206704f63b8f685a2a5d0433c50b685f6cd8b515fb5d32cb2afce06`
- source_capture_id: `source_capture-6c7263572b32a59e7087ed5363261babe13acbfd623874eb3968f55044429564`
- RECENT_7D snapshot: `input_snapshot-aff10e2f3349ed46b58dc2bcfb5b58cf1f74b0e15874be549849e37caeed4830`
- LONG_TERM_2Y snapshot: `input_snapshot-277874eaccc8748729c5777f35b92bdf1015fdfae6f9f219d06637cea7f3e4b8`

## Notes
- lineup status is operator-supplied metadata recorded in this report only; it participates in no manifest-v1 identity, snapshot, or archived report
- no score, tier, recommendation, ranking, or betting claim is produced by this run

Replay offline with:
```
python scripts/run_gm040_real_slice.py replay --run-dir <this run directory>
```
