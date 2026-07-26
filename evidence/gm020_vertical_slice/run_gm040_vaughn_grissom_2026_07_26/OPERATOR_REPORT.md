# GM-040 operator report

**Classification:** prospective

prospective capture: every participating retrieval and the run completion precede the scheduled first pitch, proven from recorded manifest instants and re-proven on every replay

## Selection
- slate date: 2026-07-26
- game: `823194` at Oracle Park
- hitter: Vaughn Grissom (MLBAM `687093`)
- lineup status (operator-supplied): **confirmed**
- capture mode: PROSPECTIVE
- expected-pitcher cross-check: not supplied (feed resolution accepted)

## Resolved expected pitcher
- Carson Whisenhunt (MLBAM `687931`), expected_starter

## Timing (recorded instants only)
- scheduled first pitch (UTC): 2026-07-26T20:05:00+00:00
- latest participating capture completion: 2026-07-26T18:54:10.003679+00:00
- run completed: 2026-07-26T18:54:10.170013+00:00
- captured before scheduled start: true

## Identities
- manifest_id: `capture_manifest-59ce9b8ca531a036ee2f811454ffb3d47c775478a9ceec337a15f7ea6a47792b`
- source_capture_id: `source_capture-627ceff83ac593dcd626b03b856250057b85218d785938b11bab0aaaa3d3f978`
- RECENT_7D snapshot: `input_snapshot-a835a8ad9bb67a57c116202fb0d9ecf5a2725d1fc34babd886c35acb9b43d8f6`
- LONG_TERM_2Y snapshot: `input_snapshot-4e4c5a80f4739541b85de0f9be5d38f171a939ecf5980989e6c4a08d40b367b7`

## Notes
- lineup status is operator-supplied metadata recorded in this report only; it participates in no manifest-v1 identity, snapshot, or archived report
- no score, tier, recommendation, ranking, or betting claim is produced by this run

Replay offline with:
```
python scripts/run_gm040_real_slice.py replay --run-dir <this run directory>
```
