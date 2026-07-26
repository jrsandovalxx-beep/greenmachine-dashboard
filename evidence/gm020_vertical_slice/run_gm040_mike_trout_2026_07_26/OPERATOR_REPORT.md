# GM-040 operator report

**Classification:** prospective

prospective capture: every participating retrieval and the run completion precede the scheduled first pitch, proven from recorded manifest instants and re-proven on every replay

## Selection
- slate date: 2026-07-26
- game: `823194` at Oracle Park
- hitter: Mike Trout (MLBAM `545361`)
- lineup status (operator-supplied): **confirmed**
- capture mode: PROSPECTIVE
- expected-pitcher cross-check: not supplied (feed resolution accepted)

## Resolved expected pitcher
- Carson Whisenhunt (MLBAM `687931`), expected_starter

## Timing (recorded instants only)
- scheduled first pitch (UTC): 2026-07-26T20:05:00+00:00
- latest participating capture completion: 2026-07-26T18:54:05.298488+00:00
- run completed: 2026-07-26T18:54:05.535732+00:00
- captured before scheduled start: true

## Identities
- manifest_id: `capture_manifest-f88b67a90b955fadae0b3d379a072f1849f0a47041e6630b995aeaa53cae2d02`
- source_capture_id: `source_capture-5b77d816e9e1106a43e0f4acddac8f41a653d6c49e05d73cffa987d4d6e4b087`
- RECENT_7D snapshot: `input_snapshot-89b3f4563220cf7b042ee149aeedefe6c9e11aa3200ccd279c5e25ca1e7fe947`
- LONG_TERM_2Y snapshot: `input_snapshot-3eca4ed54eeb31cb08a291dbd0b7956ace4ef16899647b533599c5c2cb870b20`

## Notes
- lineup status is operator-supplied metadata recorded in this report only; it participates in no manifest-v1 identity, snapshot, or archived report
- no score, tier, recommendation, ranking, or betting claim is produced by this run

Replay offline with:
```
python scripts/run_gm040_real_slice.py replay --run-dir <this run directory>
```
