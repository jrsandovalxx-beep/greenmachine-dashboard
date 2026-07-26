# GM-040 operator report

**Classification:** prospective

prospective capture: every participating retrieval and the run completion precede the scheduled first pitch, proven from recorded manifest instants and re-proven on every replay

## Selection
- slate date: 2026-07-26
- game: `823194` at Oracle Park
- hitter: Zach Neto (MLBAM `687263`)
- lineup status (operator-supplied): **confirmed**
- capture mode: PROSPECTIVE
- expected-pitcher cross-check: not supplied (feed resolution accepted)

## Resolved expected pitcher
- Carson Whisenhunt (MLBAM `687931`), expected_starter

## Timing (recorded instants only)
- scheduled first pitch (UTC): 2026-07-26T20:05:00+00:00
- latest participating capture completion: 2026-07-26T18:53:17.641127+00:00
- run completed: 2026-07-26T18:53:19.056817+00:00
- captured before scheduled start: true

## Identities
- manifest_id: `capture_manifest-b95c786eefd07ccbb8378b249628e6d64897afe8b9a3a73653ed9f084c5de64f`
- source_capture_id: `source_capture-87706cf57d24946805f1875d8e60785e382fab16061c37b5835f1d347cf8d61e`
- RECENT_7D snapshot: `input_snapshot-f59df9b7366ee1b6dcb8ffc5a6246b7f7ce2865e9d2f592110e6009c73fdcaa8`
- LONG_TERM_2Y snapshot: `input_snapshot-c8738c105904da101b67052f1b91768cdfde27fd54065ad761ce1dd4515cb1db`

## Notes
- lineup status is operator-supplied metadata recorded in this report only; it participates in no manifest-v1 identity, snapshot, or archived report
- no score, tier, recommendation, ranking, or betting claim is produced by this run

Replay offline with:
```
python scripts/run_gm040_real_slice.py replay --run-dir <this run directory>
```
