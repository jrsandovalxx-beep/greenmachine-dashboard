# GM-040 operator report

**Classification:** prospective

prospective capture: every participating retrieval and the run completion precede the scheduled first pitch, proven from recorded manifest instants and re-proven on every replay

## Selection
- slate date: 2026-07-25
- game: `823600` at Citi Field
- hitter: Shohei Ohtani (MLBAM `660271`)
- lineup status (operator-supplied): **projected**
- capture mode: PROSPECTIVE
- expected-pitcher cross-check: `690997` (matched)
- operator note: GM-040 live evidence: manually selected hitter vs. posted home probable; lineups not yet published

## Resolved expected pitcher
- Nolan McLean (MLBAM `690997`), expected_starter

## Timing (recorded instants only)
- scheduled first pitch (UTC): 2026-07-25T23:15:00+00:00
- latest participating capture completion: 2026-07-25T05:09:07.505532+00:00
- run completed: 2026-07-25T05:09:11.424464+00:00
- captured before scheduled start: true

## Identities
- manifest_id: `capture_manifest-cbb70d96e13cbd15bad98e92decb41deb337d4c3faf486ce1294c4cefc68a54e`
- source_capture_id: `source_capture-827209bf6636b5a93876aa3945736b8b2ca6fd89cff8237c2785702ca739a129`
- RECENT_7D snapshot: `input_snapshot-7181624daf04567b4a287408223ee49c67b287942c87f05edc883b548bf637f6`
- LONG_TERM_2Y snapshot: `input_snapshot-da33658dbcb2cf7bdbd49d53218bedca3a5c78da652b2921339507ff688c8603`

## Notes
- lineup status is operator-supplied metadata recorded in this report only; it participates in no manifest-v1 identity, snapshot, or archived report
- no score, tier, recommendation, ranking, or betting claim is produced by this run

Replay offline with:
```
python scripts/run_gm040_real_slice.py replay --run-dir <this run directory>
```
