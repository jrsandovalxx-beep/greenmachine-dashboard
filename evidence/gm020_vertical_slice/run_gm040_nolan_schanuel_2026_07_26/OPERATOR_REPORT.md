# GM-040 operator report

**Classification:** prospective

prospective capture: every participating retrieval and the run completion precede the scheduled first pitch, proven from recorded manifest instants and re-proven on every replay

## Selection
- slate date: 2026-07-26
- game: `823194` at Oracle Park
- hitter: Nolan Schanuel (MLBAM `694384`)
- lineup status (operator-supplied): **confirmed**
- capture mode: PROSPECTIVE
- expected-pitcher cross-check: not supplied (feed resolution accepted)

## Resolved expected pitcher
- Carson Whisenhunt (MLBAM `687931`), expected_starter

## Timing (recorded instants only)
- scheduled first pitch (UTC): 2026-07-26T20:05:00+00:00
- latest participating capture completion: 2026-07-26T18:54:27.199043+00:00
- run completed: 2026-07-26T18:54:27.449948+00:00
- captured before scheduled start: true

## Identities
- manifest_id: `capture_manifest-452182da8e7be543b612f16d4a0a23659c91c41044c4454f7b248f0957cee531`
- source_capture_id: `source_capture-c0a5ca10de1c2e7c4bced7292ffcd1c080dc21790a9f2239ac9f1be51471e6cc`
- RECENT_7D snapshot: `input_snapshot-4e792c62322f7e48e5b430499d5cf83f3f43691f3c36308becdc38eabb98f285`
- LONG_TERM_2Y snapshot: `input_snapshot-f6fd2c02b09297e379f56c523a90e5d4f49a6bc1f530b0f6a0bb0ffe62683e72`

## Notes
- lineup status is operator-supplied metadata recorded in this report only; it participates in no manifest-v1 identity, snapshot, or archived report
- no score, tier, recommendation, ranking, or betting claim is produced by this run

Replay offline with:
```
python scripts/run_gm040_real_slice.py replay --run-dir <this run directory>
```
