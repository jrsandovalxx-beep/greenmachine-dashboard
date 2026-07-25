# GreenMachine test suite

How the suite is organized, and how to work with the GM-008 golden harness.
All commands run from the repository root.

## Suite roles

| Directory | Role |
|---|---|
| `tests/unit/` | Every pure function and contract, with emphasis on boundaries and rejection paths |
| `tests/property/` | Hypothesis property tests under a **deterministic CI profile** (see below) |
| `tests/architecture/` | AST-based guards: import boundaries, determinism rules, write-path confinement — each paired with seeded violations proving the guard bites |
| `tests/integration/` | The reusable repository contract suite every persistence adapter must pass |
| `tests/golden/` | The golden harness: committed profile-specific cases that turn any scoring change into an explicit, reviewable diff |
| `tests/fixtures/` | Shared synthetic builders (`synthetic_records.py`, `synthetic_golden_cases.py`) and fixture data |

Two suite-wide policies live in `tests/conftest.py`:

- **Network blocking.** An autouse session fixture makes every network
  operation fail immediately with `network access is prohibited in tests`:
  connection paths (`socket.socket.connect`, `connect_ex`,
  `socket.create_connection`), datagram paths (`sendto`, and `sendmsg` where
  the platform provides it), and resolver paths (`getaddrinfo`,
  `gethostbyname`, `gethostbyname_ex`, `gethostbyaddr`) — IPv4 and IPv6 alike,
  always before any DNS lookup or packet. **Child Python processes spawned by
  the suite inherit an equivalent guard through an explicit bootstrap**: every
  test-spawned Python child is launched via
  `tests.network_guard.guarded_child` (`guarded_python_command` /
  `run_guarded_python`), which routes `-c` / `-m` / script invocations through
  `tests/network_guard/child_bootstrap.py` — the guard installs before the
  child payload runs, portably, even when a competing `sitecustomize` sits
  earlier on `sys.path` (regression-tested). An architecture guard confines
  `sys.executable` to the launcher, so an unguarded child invocation cannot
  exist in the suite. The `sitecustomize` shim in the same directory remains
  as secondary defense only, activated via `PYTHONPATH` where the environment
  permits. There is no opt-out flag and no environment variable that disables
  any of it. Local filesystem and subprocess use are unaffected.
- **Synthetic fixtures only.** Every fixture value is visibly synthetic
  (`SYNTHETIC-GAME-0001`, `Synthetic Test Park`, deliberately odd numbers).
  **No production baseball threshold, allocation, sample minimum, or real
  player/game/provider datum may appear anywhere under `tests/`** — production
  rules arrive only as approved, versioned configuration (MODEL_SPEC §20).

## Golden harness

A golden case proves the contract
`InputSnapshot + config version reference -> GradeResult`.
The scorer is injected; GM-008 ships only the clearly labeled test-only stub
(`tests/golden/stub_scorer.py`). The Sprint-2 scoring engine will be injected
through the same `GoldenScorer` boundary without changing the runner.

### Directory structure

```
tests/golden/
├── runner.py            # discovery, strict loading, execution, field-level diffs
├── stub_scorer.py       # TEST-ONLY deterministic stub (never enters src/)
├── test_golden_cases.py # the pytest suite that runs every committed case
└── cases/
    └── <case-directory>/
        ├── case.json                    # strict manifest
        ├── input_snapshot.json          # canonical GM-006 InputSnapshot record
        └── expected_grade_result.json   # canonical GM-006 GradeResult record
```

### Case manifest (`case.json`)

Exactly these five fields — unknown or missing fields are rejected:

```json
{
  "case_id": "synthetic-recent-evaluated",
  "config_version_identifier": "synthetic-fixture-0",
  "window_profile": "RECENT_7D",
  "snapshot_file": "input_snapshot.json",
  "expected_file": "expected_grade_result.json"
}
```

`case_id` must be a lowercase ASCII stable identifier matching
`^[a-z][a-z0-9_-]*$` (so `synthetic-recent-evaluated`, `case_2`, and `a` are
valid; spaces, uppercase, punctuation, and a leading digit, hyphen, or
underscore are rejected). `window_profile` must parse exactly as a
`WindowProfile`; the two fixture filenames must be simple names inside the
case directory (absolute paths and `..` traversal are rejected); the
referenced files must be canonical GM-006 records whose profiles match the
manifest.

**Case-root confinement:** a discovered case must be a regular directory whose
resolved path stays inside the resolved case root. Symlinked case directories
are rejected during discovery, and `scripts/update_goldens.py` re-validates
containment before planning or writing anything.

### One case, one profile

Every case declares exactly one `WindowProfile`, in the manifest **and** in
both typed records — the loader rejects any disagreement, and an architecture
guard checks the committed files. One source capture may legitimately produce
two cases (a `RECENT_7D` and a `LONG_TERM_2Y` snapshot sharing a
`source_capture_id` with distinct `snapshot_id`/`input_hash`), which is exactly
how `synthetic-recent-evaluated` and `synthetic-long-term-evaluated` are built.
Profiles are never blended and never substituted (ADR-0005).

### Adding a case (no runner change required)

1. Create a new directory under `tests/golden/cases/` with a unique `case_id`.
2. Add `case.json`, a canonical `input_snapshot.json` (freeze a synthetic
   snapshot with `freeze_input_snapshot` and write `serialize_record` bytes),
   and an `expected_grade_result.json`.
3. Run the golden suite. Discovery is automatic; ordering is by `case_id`.

### Running goldens

```bash
# all golden cases
pytest tests/golden -q

# one case (parametrized by case_id)
pytest "tests/golden/test_golden_cases.py::test_golden_case[synthetic-recent-evaluated]" -q
```

### Reading a mismatch

A drifted case fails with a `GoldenMismatchError` naming the case and every
field-level difference — exact paths, exact canonical values (Decimals as
base-10 strings, never floats):

```
golden case 'synthetic-recent-evaluated' does not match its expected result:
payload.total_score: value mismatch
    expected "9.999"
    actual   "1.111"
```

### Updating a golden — deliberately, never automatically

Pytest **never** rewrites a golden file. There is no self-healing, no
`--update` flag on the runner, and the architecture tests prove the runner and
the golden suite contain no write operation. A stale expectation always fails
the build until a developer explicitly regenerates it:

```bash
python scripts/update_goldens.py synthetic-recent-evaluated \
    --scorer tests.golden.stub_scorer:score_snapshot
```

Targets are mandatory (there is no update-everything default), the scorer is an
explicit `module:function` path, and only each targeted case's
`expected_file` is rewritten — `case.json` and `input_snapshot.json` never are.
The rewritten bytes are canonical `serialize_record` output: no timestamp, no
current date, byte-identical on repeated runs. Review the resulting diff like
any other code change; a golden update *is* the reviewable record of a scoring
change.

## Hypothesis: fixed seed 20260724, deterministic CI profile

The property suite runs under **fixed seed 20260724**, configured through
Hypothesis's supported pytest mechanism: `--hypothesis-seed=20260724` in
`pyproject.toml` `addopts`. The value is a stable constant chosen once — never
derived from a date, a clock, or an environment variable. The profile is
registered in `tests/conftest.py` and loaded by `tests/property/conftest.py`:

| Setting | Value | Meaning |
|---|---|---|
| profile name | `greenmachine-ci` | active for every property run unless explicitly overridden |
| seed | **20260724** | fixed, explicit, via `--hypothesis-seed` in `addopts`; never random in CI |
| `derandomize` | `False` | deliberate: Hypothesis prefers derandomization over a forced seed, so it stays off and the explicit seed genuinely drives generation |
| `max_examples` | `50` | explicit example budget |
| `database` | `None` | in-memory generation only; no persistent example database |
| `deadline` | `None` | no wall-clock dependence |
| health checks | none suppressed | |

Deliberate local overrides (never the default; a later `--hypothesis-seed` on
the command line wins over the `addopts` value):

```bash
# choose another explicit seed
pytest tests/property --hypothesis-seed=12345
```

```bash
# run the exploratory profile without the CI seed
pytest tests/property --hypothesis-profile=greenmachine-exploratory --hypothesis-seed=random
```

## Everything else

```bash
pytest -q                      # whole suite
pytest tests/unit/golden -q    # golden harness unit tests
pytest tests/architecture -q   # boundary and determinism guards
ruff format --check .
ruff check .
mypy --strict src/
```

No test may depend on the network, the current date or time, the current
working directory, or environment-derived configuration — enforced by the
blocked-socket fixture and the architecture guards in
`tests/architecture/test_golden_boundaries.py`.
