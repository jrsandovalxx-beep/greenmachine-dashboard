# GM-030 — Streamlit Manual-Review Prototype

**Status:** working usability prototype, not the final interface and not
production-ready. The Product Owner uses it against approved archived GM-020
runs and records UI pain points; a later refinement ticket acts on them.

## Scope and navigation

Navigation is shallow: an original **GreenMachine landing hub** (the default
screen) opens exactly one content screen at a time, and every content screen
carries a `<< GREENMACHINE HUB` return control.

The hub is original GreenMachine artwork *inspired by* the classic console
dashboard aesthetic — a dark emerald/black geometric grid, a glowing
baseball-seamed energy sphere with a subtle pulse, compact neon-green menu
bars with a bright hover/focus state, circular accents, and console-style
typography from local/system font stacks. **No Xbox logo, icon, asset, or
menu graphic is copied**, and no remote font, image, stylesheet, script, or
CDN request exists anywhere (tests enforce both). The stylized look lives on
the hub; content screens keep the dark-green identity with a calmer layout
for readability, and remain fully usable without the landing styling.

Hub destinations:

- **OVERVIEW** — hitter/pitcher/game header, capture mode and instants,
  abbreviated `SourceCaptureId`, prominent integrity status.
- **HITTER METRICS** — RECENT_7D and LONG_TERM_2Y side by side (never
  blended), metric cards grouped Power Profile / Form / Pull Power with
  provenance tucked into per-card expanders, and the Recent-vs-Long-Term
  comparison table on the same screen (arithmetic differences only).
- **MATCHUP CONTEXT** — expected pitcher **identity and role only** (name,
  MLBAM ID, role, a handedness note). Pitcher-specific metrics are deferred
  by Product Owner ruling to the later Pitchers to Target work; the screen
  says so with one concise neutral note, and the archived ingredient report
  is never even parsed for the UI.
- **DATA AUDIT** — collapsible missing/insufficient/fallback/normalization/
  identity/timing/replay/policy sections.
- **MANUAL REVIEW** — user-entered category scores, notes, deterministic
  JSON/CSV export.

## What it intentionally does NOT do

- no automated scoring, grading, or signal of any kind (no STRONG_BET / LEAN
  / PASS / AVOID, no recommendation, no betting output);
- no live provider request — archived runs only, verified read-only;
- no full-slate aggregation; one run, one hitter, one game;
- no weather, park factors, bullpen targeting, or Pitchers to Target;
- no pitcher-specific metrics of any kind (usage, pitch counts, two-strike or
  put-away statistics, vulnerability scores, rankings) — deferred by ruling;
- **no Whiff Rate anywhere** (frozen Product Owner ruling). The dashboard
  simply omits the metric without drawing attention to it: the rendered
  element tree, view models, and exports contain no whiff-related text at
  all, and an AppTest assertion sweeps every screen to prove it;
- no writes: nothing touches the archived run, the evidence bundle, a
  database, or cloud storage; manual reviews live in session state until you
  explicitly download them;
- no secrets: the app runs with no `secrets.toml`, no credential, no API key.

## Local installation and launch

```bash
python -m pip install -e ".[dev,ui]"
```

```bash
streamlit run streamlit_app.py
```

The entry point is the repository-root `streamlit_app.py`. Configuration is
the committed `.streamlit/config.toml` (usage telemetry disabled, headless,
focused error rendering).

## Data source

Default archived evidence: `evidence/gm020_vertical_slice/prospective_run/`
(the approved GM-020-r2 live prospective capture: Rafael Devers vs. Grayson
Rodriguez, gamePk 823196).

Every load re-verifies the run through the GM-020 read-only replay: strict
manifest contract, per-entry and overall identities, raw digests, the
archived digest-pinned validation-only sample policy, prospective timing
from recorded instants, and byte-identical snapshot regeneration. The
audit/context reports the dashboard additionally reads are **not** part of
`SourceCaptureId`; they pass through strict display adapters (duplicate JSON
keys rejected, types and structures validated, only canonical Decimal
strings accepted, negative counts rejected). Any failure — replay-level or
report-level — renders a focused error (run name, error category or report
label, concise message, suggestion to pick another run) — never a traceback.

### Adding another approved archived run

Copy the approved run directory (the whole bundle: `manifest.json`, `raw/`,
`inputs/`, `snapshots/`, `reports/`) under `evidence/gm020_vertical_slice/`.
Discovery is deterministic (sorted by directory name), confined to that
root, and requires no dashboard-code change. There is deliberately no path
textbox, ZIP upload, or URL loader in the UI; deployments may relocate the
root only through the `GREENMACHINE_EVIDENCE_ROOT` environment variable.

## Data-status color legend

Colors communicate **data state only** — never favorable/unfavorable, because
production thresholds and sample minimums are unresolved (Q11–Q14):

| Color | Meaning |
|---|---|
| green | present, sufficient under the archived GM-020 validation-only policy |
| yellow | present, but the sample is below the validation-only minimum |
| gray | missing or unavailable |
| blue | audit-only / contextual (e.g. Overall Pull%) — never a scoring input |
| red | data validation, loading, replay, or integrity error |

Badges always pair the color with an icon and a text label; meaning never
relies on color alone. The legend is pinned in the sidebar.

## Manual scoring disclaimer

The worksheet is **manual user review — not automated GreenMachine scoring**.
You assign Power Profile (0–3), Pitcher Matchup (0–3), Form (0–2), Pull Power
(0–2), Environment (0–2); the app adds the arithmetic and shows the frozen
tier (S 10–12 · A 8–9 · B 6–7 · C 4–5 · D 0–3) only once every category is
scored. Exports (deterministic JSON and CSV) carry the run identities, your
scores/notes, and the disclaimer verbatim; a timestamp appears only if you
typed one — the app never reads the clock for exports.

## Streamlit Community Cloud deployment

Community Cloud installs the repository-root `requirements.txt`
**automatically**. It contains the editable self-install line `-e .`
(GM-040-HF1: the host installs the local project itself, so the package's
distribution metadata — and therefore its version — resolves on the deployed
environment) plus exactly the four bounded runtime/UI dependencies the hosted
app needs (`streamlit>=1.32,<2`, `PyYAML>=6,<7`, `pydantic>=2,<3`,
`tzdata>=2024.1`), and nothing development-only. No `packages.txt` is needed
(no operating-system package is required); installing `requirements.txt`
alone is sufficient to launch.

The deployment structure the host expects, at the repository root:

```
repository root/
    streamlit_app.py
    requirements.txt
    pyproject.toml
    .streamlit/config.toml
    src/
    evidence/
```

**Getting from the release ZIP to a GitHub repository:** the ZIP contains one
outer `greenmachine/` directory. After extraction, the **contents of that
`greenmachine/` directory** become the GitHub repository root (so
`streamlit_app.py` and `requirements.txt` sit at the top level of the repo).
Do **not** upload:

- the ZIP itself as the app repository;
- an extra parent directory above the `greenmachine/` contents;
- secrets of any kind;
- virtual environments or caches;
- manual-review exports.

Community Cloud app settings:

| Setting | Value |
|---|---|
| repository | the published GitHub repository |
| branch | `main` |
| entrypoint | `streamlit_app.py` |
| Python | 3.12 |
| secrets | none |

After the first load, verify the landing hub renders and the Overview screen
shows "prospective live capture" with all integrity checks passing.

## Known prototype limitations

- Team and opponent names are not recorded in the provider-neutral archive,
  so the header marks them as unavailable.
- Pitcher handedness is not captured in the GM-020 slice; Matchup Context is
  identity/role only until the Pitchers to Target work.
- Pitch Mix Pressure / Put-Away Pitch Exploitation remain missing pending
  Q15/Q16; park and weather have no source yet.
- One archived run at a time; no slate view.
- Verification re-runs the full replay on first load of a run (a few
  seconds); the result is cached for the session.
- The console styling is a first pass; deeper visual refinement follows
  Product Owner use.

## Recording UI pain points

While using the prototype, note — per screen — confusing navigation,
excessive density, missing context, distracting metrics, unclear labels,
weak hierarchy, color-coding problems, unnecessary clicks, and desired
additions/removals. Deliver the notes as the input to the UI refinement
ticket; do not edit the prototype in place.
