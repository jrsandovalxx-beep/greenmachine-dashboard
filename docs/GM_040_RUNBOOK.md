# GM-040 operator runbook — real-data vertical slice

One explicit selection (game, hitter, expected pitcher) through capture →
raw archive → verification → normalization → mapping → deterministic replay
→ the existing Streamlit review experience. Script-triggered only: the
hosted app never captures.

## Prerequisites

```bash
python -m pip install -e ".[dev,ui]"
```

## 1. Choose the selection explicitly

Nothing is guessed. You supply:

- **slate date** — the official MLB date (`YYYY-MM-DD`);
- **gamePk** — the official game identifier (from the MLB schedule);
- **hitter MLBAM id** — the one manually selected hitter;
- **lineup status** — `projected` or `confirmed`, your statement, recorded in
  the operator report only (it never enters an identity);
- optionally **--expected-pitcher-id** — a *cross-check only*: manifest v1
  always records the feed-resolved pitcher, so a mismatch fails closed and
  publishes nothing. If the feed cannot resolve a pitcher at all, the run is
  a fail-closed eligibility outcome; there is no override.

## 2. Capture

```bash
python scripts/run_gm040_real_slice.py capture --slate-date 2026-07-25 --game-pk <GAMEPK> --batter-id <MLBAM> --lineup-status projected --output-dir evidence/gm020_vertical_slice/run_gm040_<name> --sample-policy tests/fixtures/ingestion/gm020_nonproduction_sample_policy.json --capture-mode prospective
```

- `--capture-mode prospective` requires a pregame game and recorded
  completion strictly before first pitch (enforced from manifest instants,
  re-proven on every replay).
- `--capture-mode retrospective` is the **explicit development permission**:
  the run publishes but is permanently labeled `retrospective-development`
  and is never represented as a locked pregame prediction — even when its
  timestamps happen to precede the scheduled start.
- Repeating a run against the same directory: byte-identical content
  **verifies** (`verified-existing`, nothing written); any difference is an
  explicit conflict and nothing is overwritten.
- A failed capture publishes only `failed_run/` evidence (blockers, attempt
  log, raw bytes that did arrive, and your operator selection) and exits 3.

Exit codes: `0` published/verified · `2` typed GreenMachine error ·
`3` capture not published · `4` replay mismatch.

## 3. Read the operator report

Inside the published bundle: `OPERATOR_REPORT.md` (human-readable) and
`reports/operator_report.json` (canonical). They record your selection and
lineup status, the resolved pitcher, the timing classification with the
scheduled-start comparison, and every identity. Lineup status lives **only**
here by ruling — no frozen surface carries it.

## 4. Replay (offline, repeatable)

```bash
python scripts/run_gm040_real_slice.py replay --run-dir evidence/gm020_vertical_slice/run_gm040_<name>
```

No network, no clock; the bundle's own digest-pinned sample policy is used
automatically; repeat runs succeed without rewriting the report.

## 5. Review in the app

Any bundle under `evidence/gm020_vertical_slice/` appears in the Streamlit
run selector automatically — no code change:

```bash
streamlit run streamlit_app.py
```

Multi-player operation is exactly this loop repeated: **one independent
manifest-v1 bundle per hitter**, never a combined slate bundle.

## Sample policy reminder

The referenced policy file is the GM-020 **validation-only, non-production**
fixture (Q14 is open). Its exact bytes are archived and digest-pinned inside
every bundle.
