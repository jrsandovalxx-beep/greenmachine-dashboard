"""Architecture guards for the GM-008 golden harness (ADR-0008).

Focused rules over the new GM-008 files: the runner's import allowlist, the
single golden write path, current-date and environment independence, no
randomness outside Hypothesis, network-free golden/property tests, and the
synthetic single-profile discipline of the committed case files. Each rule that
scans real files is paired with a seeded, syntax-valid violation proving the
guard bites. Seeded snippets live only in this file, which no rule scans —
so they cannot produce false positives elsewhere.
"""

from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path

import pytest
from static_analysis import (
    clock_reads,
    collect_imports,
    io_module_offenders,
    random_offenders,
    third_party_offenders,
    uuid_offenders,
    within,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_PACKAGE = REPO_ROOT / "src" / "greenmachine"
GOLDEN_DIR = REPO_ROOT / "tests" / "golden"
CASES_ROOT = GOLDEN_DIR / "cases"
UNIT_GOLDEN_DIR = REPO_ROOT / "tests" / "unit" / "golden"
PROPERTY_DIR = REPO_ROOT / "tests" / "property"
SCRIPTS_DIR = REPO_ROOT / "scripts"

RUNNER = GOLDEN_DIR / "runner.py"
STUB = GOLDEN_DIR / "stub_scorer.py"
GOLDEN_INIT = GOLDEN_DIR / "__init__.py"
GOLDEN_SUITE = GOLDEN_DIR / "test_golden_cases.py"
UPDATE_SCRIPT = SCRIPTS_DIR / "update_goldens.py"
PROPERTY_CONFTEST = PROPERTY_DIR / "conftest.py"
GOLDEN_PROPERTIES = PROPERTY_DIR / "test_golden_properties.py"
ROOT_CONFTEST = REPO_ROOT / "tests" / "conftest.py"
NETWORK_GUARD_DIR = REPO_ROOT / "tests" / "network_guard"
SITECUSTOMIZE = NETWORK_GUARD_DIR / "sitecustomize.py"
NETWORK_GUARD_INSTALLER = NETWORK_GUARD_DIR / "greenmachine_network_guard.py"
CHILD_BOOTSTRAP = NETWORK_GUARD_DIR / "child_bootstrap.py"
GUARDED_CHILD = NETWORK_GUARD_DIR / "guarded_child.py"

# Every Python file GM-008 added or reworked. The current-date, randomness,
# and UUID rules apply to all of them — including the root conftest and the
# child-process network guard.
GM008_PYTHON_FILES = sorted(
    {
        RUNNER,
        STUB,
        GOLDEN_INIT,
        GOLDEN_SUITE,
        UPDATE_SCRIPT,
        PROPERTY_CONFTEST,
        GOLDEN_PROPERTIES,
        ROOT_CONFTEST,
        SITECUSTOMIZE,
        NETWORK_GUARD_INSTALLER,
        CHILD_BOOTSTRAP,
        GUARDED_CHILD,
        REPO_ROOT / "tests" / "fixtures" / "evaluations" / "synthetic_golden_cases.py",
        *UNIT_GOLDEN_DIR.glob("*.py"),
    }
)

# Modules that would mean a network, database, or external-service dependency.
NETWORK_AND_DB_MODULES = frozenset(
    {"socket", "ssl", "urllib", "http", "ftplib", "smtplib", "sqlite3", "requests", "httpx"}
)

# Narrow, deliberate exemptions from the no-network-import rule: the network
# meta-test attempts connections ON PURPOSE, and the two guard installers (the
# parent-session fixture and the shared child installer) must import socket to
# patch it. Nothing else — not even sitecustomize or the bootstrap, which
# delegate to the installer — may touch these modules.
NETWORK_RULE_EXEMPT = frozenset(
    {UNIT_GOLDEN_DIR / "test_network_blocking.py", ROOT_CONFTEST, NETWORK_GUARD_INSTALLER}
)


def parse_file(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def seeded(source: str) -> ast.Module:
    try:
        return ast.parse(source)
    except SyntaxError as exc:  # pragma: no cover - the snippets are valid
        pytest.fail(f"seeded source must be syntactically valid, but did not parse: {exc}")


def test_every_expected_gm008_file_exists() -> None:
    """Anti-vacuity: the scans below must actually cover the harness files."""
    for path in (
        RUNNER,
        STUB,
        GOLDEN_INIT,
        GOLDEN_SUITE,
        UPDATE_SCRIPT,
        PROPERTY_CONFTEST,
        GOLDEN_PROPERTIES,
    ):
        assert path.is_file(), path
    assert len(GM008_PYTHON_FILES) >= 10
    assert CASES_ROOT.is_dir()


# --------------------------------------------------------------------------
# Runner and stub import allowlists
# --------------------------------------------------------------------------

RUNNER_ALLOWED_ROOTS = ("greenmachine.domain", "greenmachine.evaluation")
FORBIDDEN_RUNNER_ROOTS = (
    "greenmachine.scoring",
    "greenmachine.config",
    "greenmachine.ingestion",
    "greenmachine.features",
    "greenmachine.persistence",
    "greenmachine.reporting",
    "greenmachine.cli",
    "greenmachine.common",
)


def greenmachine_import_offenders(tree: ast.Module, allowed_roots: tuple[str, ...]) -> list[str]:
    """GreenMachine imports outside the allowlist, plus any relative import."""
    offenders: list[str] = []
    for record in collect_imports(tree):
        if record.is_relative:
            offenders.append(f"line {record.lineno}: relative import")
        elif record.top_level == "greenmachine" and not any(
            within(record.module, root) for root in allowed_roots
        ):
            offenders.append(f"line {record.lineno}: {record.module}")
    return offenders


def test_runner_imports_only_domain_and_evaluation_serialization() -> None:
    tree = parse_file(RUNNER)
    assert greenmachine_import_offenders(tree, RUNNER_ALLOWED_ROOTS) == []
    assert third_party_offenders(tree) == []


def test_runner_reaches_no_forbidden_layer() -> None:
    imported = [
        record.module
        for record in collect_imports(parse_file(RUNNER))
        if record.top_level == "greenmachine"
    ]
    for module in imported:
        for forbidden in FORBIDDEN_RUNNER_ROOTS:
            assert not within(module, forbidden), f"runner imports {module}"


def test_runner_does_not_import_the_stub_or_pytest() -> None:
    """The core runner stays usable by the update script without pytest."""
    tops = {record.top_level for record in collect_imports(parse_file(RUNNER))}
    assert "pytest" not in tops
    modules = {record.module for record in collect_imports(parse_file(RUNNER))}
    assert not any("stub_scorer" in module for module in modules)


def test_stub_scorer_imports_only_domain_and_stdlib() -> None:
    tree = parse_file(STUB)
    assert greenmachine_import_offenders(tree, ("greenmachine.domain",)) == []
    assert third_party_offenders(tree) == []


def test_seeded_forbidden_import_is_detected() -> None:
    flagged = seeded("from greenmachine.scoring import resolve_bucket\n")
    assert greenmachine_import_offenders(flagged, RUNNER_ALLOWED_ROOTS)
    flagged_config = seeded("import greenmachine.config.loader\n")
    assert greenmachine_import_offenders(flagged_config, RUNNER_ALLOWED_ROOTS)
    control = seeded(
        "from greenmachine.domain import WindowProfile\n"
        "from greenmachine.evaluation import serialize_record\n"
    )
    assert greenmachine_import_offenders(control, RUNNER_ALLOWED_ROOTS) == []


# --------------------------------------------------------------------------
# The stub exists only under tests/; src/ gained nothing from GM-008
# --------------------------------------------------------------------------


def test_no_stub_or_golden_module_exists_under_src() -> None:
    assert list(SRC_PACKAGE.rglob("*stub*")) == []
    assert list(SRC_PACKAGE.rglob("*golden*")) == []


@pytest.mark.parametrize("path", sorted(SRC_PACKAGE.rglob("*.py")), ids=lambda p: p.name)
def test_src_imports_neither_tests_nor_hypothesis(path: Path) -> None:
    tops = {record.top_level for record in collect_imports(parse_file(path))}
    assert "tests" not in tops
    assert "hypothesis" not in tops


# --------------------------------------------------------------------------
# Single golden write path
# --------------------------------------------------------------------------

_WRITE_ATTRIBUTES = frozenset(
    {
        "write",
        "write_text",
        "write_bytes",
        "unlink",
        "rename",
        "replace",
        "rmdir",
        "mkdir",
        "makedirs",
        "touch",
        "remove",
        "removedirs",
        "copy",
        "copyfile",
        "copytree",
        "move",
        "fdopen",
        "mkstemp",
    }
)


def write_api_offenders(tree: ast.Module) -> list[tuple[int, str]]:
    """Calls that could create, modify, or remove a file.

    Attribute-name based (``path.write_bytes``, ``os.replace``, ``shutil.move``)
    plus builtin ``open`` with a writing mode. Read-only ``open(path)`` and
    ``read_bytes`` are not flagged.
    """
    offenders: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        callee = node.func
        if isinstance(callee, ast.Attribute) and callee.attr in _WRITE_ATTRIBUTES:
            offenders.append((node.lineno, callee.attr))
        elif isinstance(callee, ast.Name) and callee.id == "open":
            mode: object = None
            if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                mode = node.args[1].value
            for keyword in node.keywords:
                if keyword.arg == "mode" and isinstance(keyword.value, ast.Constant):
                    mode = keyword.value.value
            if isinstance(mode, str) and any(flag in mode for flag in "wax+"):
                offenders.append((node.lineno, f"open(mode={mode!r})"))
    return offenders


@pytest.mark.parametrize(
    "path",
    [
        RUNNER,
        STUB,
        GOLDEN_INIT,
        GOLDEN_SUITE,
        ROOT_CONFTEST,
        SITECUSTOMIZE,
        NETWORK_GUARD_INSTALLER,
        CHILD_BOOTSTRAP,
        GUARDED_CHILD,
    ],
    ids=lambda p: p.name,
)
def test_the_runner_stub_suite_and_guards_contain_no_write_operation(path: Path) -> None:
    assert write_api_offenders(parse_file(path)) == []


def test_the_update_script_is_the_only_golden_write_path() -> None:
    """Anti-vacuity for the rule above: the script exists and does write."""
    script_writes = write_api_offenders(parse_file(UPDATE_SCRIPT))
    assert script_writes, "scripts/update_goldens.py must contain the golden write path"
    written_names = {name for _, name in script_writes}
    assert "replace" in written_names, "the script must use atomic os.replace"


def test_seeded_write_operations_are_detected() -> None:
    for snippet in (
        "from pathlib import Path\nPath('x').write_bytes(b'')\n",
        "import os\nos.replace('a', 'b')\n",
        "handle = open('x', 'w')\n",
        "handle = open('x', mode='ab')\n",
    ):
        assert write_api_offenders(seeded(snippet)), snippet
    control = seeded(
        "from pathlib import Path\ndata = Path('x').read_bytes()\nhandle = open('x')\n"
    )
    assert write_api_offenders(control) == []


def test_the_runner_has_no_automatic_update_flag() -> None:
    from tests.golden import runner

    banned_fragments = ("update", "write", "regenerate", "heal", "fix")
    entry_points = (
        runner.discover_cases,
        runner.load_case,
        runner.run_case,
        runner.run_cases,
        runner.score_case,
        runner.assert_case_passes,
    )
    for entry_point in entry_points:
        for parameter in inspect.signature(entry_point).parameters:
            lowered = parameter.lower()
            assert not any(fragment in lowered for fragment in banned_fragments), (
                f"{entry_point.__name__} exposes suspicious parameter {parameter!r}"
            )
    update_named = {name for name in vars(runner) if "update" in name.lower()}
    assert update_named == {"GoldenUpdateError"}


# --------------------------------------------------------------------------
# No clock reads, no environment access, no randomness
# --------------------------------------------------------------------------


@pytest.mark.parametrize("path", GM008_PYTHON_FILES, ids=lambda p: p.name)
def test_no_gm008_file_reads_the_clock(path: Path) -> None:
    assert clock_reads(parse_file(path)) == []


def test_seeded_clock_read_is_detected() -> None:
    flagged = seeded("from datetime import datetime\nstamp = datetime.now()\n")
    assert clock_reads(flagged)
    control = seeded("from datetime import datetime, UTC\nstamp = datetime(2026, 7, 15)\n")
    assert clock_reads(control) == []


def _is_os_environ(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr in {"environ", "environb"}
        and isinstance(node.value, ast.Name)
        and node.value.id == "os"
    )


def _constant_key(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def environment_accesses(tree: ast.Module) -> list[tuple[int, str, str | None]]:
    """Every environment access, with the environment-variable key where literal.

    Returns ``(line, description, key)`` for ``os.environ[...]`` (read, write,
    or delete), ``os.environ.get(...)``, ``os.getenv(...)``, bare ``os.environ``
    passed around (key ``None``), and ``from os import environ/getenv``.
    """
    accesses: list[tuple[int, str, str | None]] = []
    handled: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and _is_os_environ(node.value):
            handled.add(id(node.value))
            accesses.append((node.lineno, "os.environ[...]", _constant_key(node.slice)))
        elif isinstance(node, ast.Call):
            callee = node.func
            if (
                isinstance(callee, ast.Attribute)
                and callee.attr in {"get", "pop", "setdefault"}
                and _is_os_environ(callee.value)
            ):
                handled.add(id(callee.value))
                key = _constant_key(node.args[0]) if node.args else None
                accesses.append((node.lineno, f"os.environ.{callee.attr}(...)", key))
            elif (
                isinstance(callee, ast.Attribute)
                and callee.attr == "getenv"
                and isinstance(callee.value, ast.Name)
                and callee.value.id == "os"
            ):
                key = _constant_key(node.args[0]) if node.args else None
                accesses.append((node.lineno, "os.getenv(...)", key))
        elif isinstance(node, ast.ImportFrom) and node.module == "os" and node.level == 0:
            accesses.extend(
                (node.lineno, f"from os import {alias.name}", None)
                for alias in node.names
                if alias.name in {"environ", "environb", "getenv"}
            )
    for node in ast.walk(tree):
        if _is_os_environ(node) and id(node) not in handled:
            accesses.append((node.lineno, "os.environ", None))
    return sorted(accesses)


@pytest.mark.parametrize(
    "path",
    [
        RUNNER,
        STUB,
        GOLDEN_INIT,
        GOLDEN_SUITE,
        UPDATE_SCRIPT,
        PROPERTY_CONFTEST,
        SITECUSTOMIZE,
        NETWORK_GUARD_INSTALLER,
        CHILD_BOOTSTRAP,
        GUARDED_CHILD,
    ],
    ids=lambda p: p.name,
)
def test_harness_core_reads_no_environment_variable(path: Path) -> None:
    assert environment_accesses(parse_file(path)) == []


def test_root_conftest_touches_only_pythonpath_for_the_child_guard() -> None:
    """The one sanctioned environment concern: propagating the network guard.

    ``tests/conftest.py`` is included in the environment scan; its only
    permitted accesses are ``PYTHONPATH``-keyed reads/writes/restores inside
    the blocked-network fixture. Any other key — and any unkeyed use, such as
    passing ``os.environ`` around — fails this guard.
    """
    accesses = environment_accesses(parse_file(ROOT_CONFTEST))
    assert accesses, "the child-guard propagation must exist (anti-vacuity)"
    for line, description, key in accesses:
        assert key == "PYTHONPATH", (
            f"tests/conftest.py line {line}: {description} touches environment key "
            f"{key!r}; only PYTHONPATH (child network-guard propagation) is permitted"
        )


def test_seeded_environment_access_is_detected() -> None:
    scorer_read = environment_accesses(seeded("import os\nvalue = os.environ['SCORER']\n"))
    assert scorer_read and scorer_read[0][2] == "SCORER"
    assert environment_accesses(seeded("from os import getenv\n"))
    assert environment_accesses(seeded("import os\nos.getenv('SEED')\n"))
    unkeyed = environment_accesses(seeded("import os\nchild_env = dict(os.environ)\n"))
    assert unkeyed and unkeyed[0][2] is None
    pythonpath_write = environment_accesses(seeded("import os\nos.environ['PYTHONPATH'] = 'x'\n"))
    assert pythonpath_write == [(2, "os.environ[...]", "PYTHONPATH")]
    control = seeded("import os\npath = os.fspath('x')\n")
    assert environment_accesses(control) == []


@pytest.mark.parametrize("path", GM008_PYTHON_FILES, ids=lambda p: p.name)
def test_no_gm008_file_uses_raw_randomness(path: Path) -> None:
    """Randomness exists only inside Hypothesis's controlled deterministic framework."""
    tree = parse_file(path)
    assert random_offenders(tree) == []
    assert uuid_offenders(tree) == []


def test_seeded_randomness_is_detected() -> None:
    assert random_offenders(seeded("import random\n"))
    assert uuid_offenders(seeded("import uuid\nidentifier = uuid.uuid4()\n"))


# --------------------------------------------------------------------------
# No network or database modules in the harness
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [p for p in GM008_PYTHON_FILES if p not in NETWORK_RULE_EXEMPT],
    ids=lambda p: p.name,
)
def test_no_gm008_file_imports_network_or_database_modules(path: Path) -> None:
    assert io_module_offenders(parse_file(path), NETWORK_AND_DB_MODULES) == []


def test_the_exemptions_are_exactly_the_meta_test_and_the_two_guard_installers() -> None:
    expected = {
        UNIT_GOLDEN_DIR / "test_network_blocking.py",
        ROOT_CONFTEST,
        NETWORK_GUARD_INSTALLER,
    }
    assert expected == NETWORK_RULE_EXEMPT


def sys_executable_uses(tree: ast.Module) -> list[int]:
    """Every ``sys.executable`` reference — the raw material of a direct child."""
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and node.attr == "executable"
        and isinstance(node.value, ast.Name)
        and node.value.id == "sys"
    ]


@pytest.mark.parametrize(
    "path",
    sorted(
        entry
        for entry in (REPO_ROOT / "tests").rglob("*.py")
        if entry != GUARDED_CHILD and "__pycache__" not in entry.parts
    ),
    ids=lambda p: p.relative_to(REPO_ROOT).as_posix(),
)
def test_only_the_guarded_launcher_spawns_python_children(path: Path) -> None:
    """Every test-spawned Python interpreter goes through the guarded mechanism.

    ``sys.executable`` may appear in exactly one test file — the centralized
    guarded launcher — so an unguarded ``python -c/-m/script`` child cannot be
    launched from anywhere else in the suite.
    """
    assert sys_executable_uses(parse_file(path)) == []


def test_the_guarded_launcher_actually_names_sys_executable() -> None:
    """Anti-vacuity: the rule above would pass if the launcher vanished."""
    assert sys_executable_uses(parse_file(GUARDED_CHILD))
    assert CHILD_BOOTSTRAP.is_file()


def test_seeded_direct_python_child_invocation_is_detected() -> None:
    flagged = seeded(
        "import subprocess\nimport sys\nsubprocess.run([sys.executable, '-c', 'pass'])\n"
    )
    assert sys_executable_uses(flagged)
    control = seeded(
        "import subprocess\n"
        "from tests.network_guard.guarded_child import guarded_python_command\n"
        "subprocess.run(guarded_python_command('-c', 'pass'))\n"
    )
    assert sys_executable_uses(control) == []


def test_seeded_network_import_is_detected() -> None:
    assert io_module_offenders(seeded("import socket\n"), NETWORK_AND_DB_MODULES)
    assert io_module_offenders(seeded("import sqlite3\n"), NETWORK_AND_DB_MODULES)
    control = seeded("import json\nimport subprocess\n")
    assert io_module_offenders(control, NETWORK_AND_DB_MODULES) == []


# --------------------------------------------------------------------------
# Third-party discipline per file
# --------------------------------------------------------------------------

_ALLOWED_NON_STDLIB: dict[str, frozenset[str]] = {
    "runner.py": frozenset(),
    "stub_scorer.py": frozenset(),
    "__init__.py": frozenset(),
    "update_goldens.py": frozenset({"tests"}),
    "test_golden_cases.py": frozenset({"pytest", "tests"}),
    "conftest.py": frozenset({"pytest", "hypothesis"}),
    "test_golden_properties.py": frozenset({"pytest", "hypothesis", "tests"}),
    "synthetic_golden_cases.py": frozenset({"synthetic_records"}),
    "sitecustomize.py": frozenset({"greenmachine_network_guard"}),
    "greenmachine_network_guard.py": frozenset(),
    "child_bootstrap.py": frozenset({"greenmachine_network_guard"}),
    "guarded_child.py": frozenset(),
}
_UNIT_GOLDEN_ALLOWED = frozenset(
    {"pytest", "tests", "scripts", "synthetic_records", "synthetic_golden_cases"}
)


@pytest.mark.parametrize("path", GM008_PYTHON_FILES, ids=lambda p: p.name)
def test_gm008_files_take_no_new_external_dependency(path: Path) -> None:
    offenders = third_party_offenders(parse_file(path))
    allowed = (
        _UNIT_GOLDEN_ALLOWED
        if path.parent == UNIT_GOLDEN_DIR
        else _ALLOWED_NON_STDLIB.get(path.name, frozenset())
    )
    unexpected = [record.module for record in offenders if record.top_level not in allowed]
    assert unexpected == []


# --------------------------------------------------------------------------
# Committed case files: synthetic-only, one profile each, JSON only
# --------------------------------------------------------------------------


def case_directories() -> list[Path]:
    return sorted(entry for entry in CASES_ROOT.iterdir() if entry.is_dir())


def collect_profile_values(structure: object) -> set[str]:
    """Every ``window_profile`` value appearing anywhere in a parsed record."""
    found: set[str] = set()
    if isinstance(structure, dict):
        for key, value in structure.items():
            if key == "window_profile" and isinstance(value, str):
                found.add(value)
            found |= collect_profile_values(value)
    elif isinstance(structure, list):
        for item in structure:
            found |= collect_profile_values(item)
    return found


def test_the_committed_case_tree_is_not_empty() -> None:
    assert len(case_directories()) >= 2


@pytest.mark.parametrize("directory", case_directories(), ids=lambda p: p.name)
def test_every_case_contains_exactly_the_three_case_files(directory: Path) -> None:
    names = sorted(entry.name for entry in directory.iterdir())
    assert names == ["case.json", "expected_grade_result.json", "input_snapshot.json"]


@pytest.mark.parametrize("directory", case_directories(), ids=lambda p: p.name)
def test_every_case_declares_exactly_one_profile_everywhere(directory: Path) -> None:
    manifest = json.loads((directory / "case.json").read_bytes())
    declared = manifest["window_profile"]
    assert declared in {"RECENT_7D", "LONG_TERM_2Y"}

    snapshot = json.loads((directory / "input_snapshot.json").read_bytes())
    expected = json.loads((directory / "expected_grade_result.json").read_bytes())
    assert collect_profile_values(snapshot["payload"]) == {declared}
    assert collect_profile_values(expected["payload"]) == {declared}


def test_a_seeded_two_profile_case_file_is_detected(tmp_path: Path) -> None:
    """The file-level guard flags a snapshot smuggling a second profile."""
    source = case_directories()[0]
    snapshot = json.loads((source / "input_snapshot.json").read_bytes())
    observations = snapshot["payload"]["present_observations"]
    if not observations:
        observations = snapshot["payload"]["missing_observations"]
    original = observations[0]["window_profile"]
    observations[0]["window_profile"] = "LONG_TERM_2Y" if original == "RECENT_7D" else "RECENT_7D"
    tampered = tmp_path / "input_snapshot.json"
    tampered.write_bytes(json.dumps(snapshot).encode("utf-8"))

    values = collect_profile_values(json.loads(tampered.read_bytes())["payload"])
    assert len(values) == 2


@pytest.mark.parametrize("directory", case_directories(), ids=lambda p: p.name)
def test_every_case_uses_only_synthetic_identifiers(directory: Path) -> None:
    snapshot = json.loads((directory / "input_snapshot.json").read_bytes())["payload"]
    assert "SYNTHETIC" in snapshot["game_context"]["game_id"]["value"]
    assert "SYNTHETIC" in snapshot["batter"]["player_id"]["value"]
    assert "Synthetic" in snapshot["batter"]["full_name"]
    assert "SYNTHETIC" in snapshot["expected_starting_pitcher"]["player_id"]["value"]
    assert "Synthetic" in snapshot["expected_starting_pitcher"]["full_name"]
    assert "Synthetic" in snapshot["game_context"]["venue"]["name"]
    assert "SYNTHETIC" in snapshot["source_capture_id"]["value"]

    manifest = json.loads((directory / "case.json").read_bytes())
    assert manifest["config_version_identifier"].startswith("synthetic-")


def test_no_yaml_configuration_was_added_by_gm008() -> None:
    """Golden fixtures are canonical JSON records, never model configuration."""
    for root in (GOLDEN_DIR, UNIT_GOLDEN_DIR, SCRIPTS_DIR):
        assert list(root.rglob("*.yaml")) == []
        assert list(root.rglob("*.yml")) == []
