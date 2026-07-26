# GM-040 operator report

**Classification:** prospective

prospective capture: every participating retrieval and the run completion precede the scheduled first pitch, proven from recorded manifest instants and re-proven on every replay

## Selection
- slate date: 2026-07-26
- game: `823194` at Oracle Park
- hitter: Denzer Guzman (MLBAM `694203`)
- lineup status (operator-supplied): **confirmed**
- capture mode: PROSPECTIVE
- expected-pitcher cross-check: not supplied (feed resolution accepted)

## Resolved expected pitcher
- Carson Whisenhunt (MLBAM `687931`), expected_starter

## Timing (recorded instants only)
- scheduled first pitch (UTC): 2026-07-26T20:05:00+00:00
- latest participating capture completion: 2026-07-26T18:54:45.355690+00:00
- run completed: 2026-07-26T18:54:45.498491+00:00
- captured before scheduled start: true

## Identities
- manifest_id: `capture_manifest-02ca1c67211e2b5aa95783d316b0f421b1f3c70a361d89c9a94a6f1040d422a1`
- source_capture_id: `source_capture-d111a92fa8a55d8696656fc1bce0dd8de1252e37428b56e31312d9eaa9bc6aee`
- RECENT_7D snapshot: `input_snapshot-b8220a524997586b550ec85932d3655166b10ff534e142c0f6594516ba3d5ae8`
- LONG_TERM_2Y snapshot: `input_snapshot-3f88d20eda02f762c634e508f94db4d790adb68e360d8da29e1f63d808816560`

## Notes
- lineup status is operator-supplied metadata recorded in this report only; it participates in no manifest-v1 identity, snapshot, or archived report
- no score, tier, recommendation, ranking, or betting claim is produced by this run

Replay offline with:
```
python scripts/run_gm040_real_slice.py replay --run-dir <this run directory>
```
