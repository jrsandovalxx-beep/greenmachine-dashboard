"""Boundaries for the configuration package.

``config`` is the one package permitted a third-party modelling toolchain
(ARCHITECTURE.md §9): Pydantic and PyYAML, and nothing else. It may reach into
``domain`` for the shared vocabulary and into ``common`` for the numeric policy
and the error taxonomy, but never sideways or downstream — importing ``scoring``
or ``features`` here would invert the dependency direction the whole
architecture rests on.

It also holds no baseball. Every threshold, bucket edge, and sample minimum
lives in YAML fixtures; production source contains none.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from static_analysis import (
    collect_imports,
    package_of,
    third_party_offenders,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
PACKAGE_ROOT = SRC_ROOT / "greenmachine"
CONFIG_ROOT = PACKAGE_ROOT / "config"

CONFIG_PACKAGE = "greenmachine.config"

# The modelling toolchain the architecture names, and nothing else.
APPROVED_THIRD_PARTY = frozenset({"pydantic", "yaml"})

# GreenMachine packages `config` may depend on (ARCHITECTURE.md §4: dependencies
# point inward only). GM-004 adds `common.ids` — the shared content-hash used to
# derive `config_hash` — which is explicitly within the ticket's allowed imports
# (deterministic serialization/hashing) and reuses GM-005 rather than adding a
# second hasher.
APPROVED_INTERNAL = frozenset(
    {
        "greenmachine.domain",
        "greenmachine.common.errors",
        "greenmachine.common.numeric",
        "greenmachine.common.ids",
    }
)

# Packages at or downstream of config; importing any of them inverts the graph.
FORBIDDEN_INTERNAL = (
    "greenmachine.scoring",
    "greenmachine.features",
    "greenmachine.evaluation",
    "greenmachine.ingestion",
    "greenmachine.persistence",
    "greenmachine.reporting",
    "greenmachine.validation",
    "greenmachine.cli",
)

FORBIDDEN_THIRD_PARTY = frozenset(
    {"pandas", "numpy", "streamlit", "plotly", "requests", "httpx", "aiohttp", "sqlalchemy"}
)

# Environment, network, and write-capable modules.
FORBIDDEN_STDLIB = frozenset({"os", "socket", "subprocess", "shutil", "urllib", "http", "tempfile"})


def config_files() -> list[Path]:
    return sorted(CONFIG_ROOT.rglob("*.py"))


def parse_file(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def seeded(source: str) -> ast.Module:
    """Parse seeded source, first proving it is syntactically valid."""
    try:
        return ast.parse(source)
    except SyntaxError as exc:  # pragma: no cover - the snippets are valid
        pytest.fail(f"seeded source must be syntactically valid, but did not parse: {exc}")


def internal_offenders(tree: ast.Module, package: str) -> list[str]:
    """GreenMachine imports outside the approved set."""
    offenders: list[str] = []
    for record in collect_imports(tree):
        resolved = record.resolved(package)
        if not resolved.startswith("greenmachine"):
            continue
        if resolved == package or resolved.startswith(f"{package}."):
            continue  # intra-config
        if any(
            resolved == approved or resolved.startswith(f"{approved}.")
            for approved in APPROVED_INTERNAL
        ):
            continue
        offenders.append(resolved)
    return offenders


def unapproved_third_party(tree: ast.Module) -> list[str]:
    """Third-party imports outside the approved modelling toolchain."""
    return [
        record.top_level
        for record in third_party_offenders(tree)
        if record.top_level not in APPROVED_THIRD_PARTY
    ]


# --------------------------------------------------------------------------
# The real package
# --------------------------------------------------------------------------


def test_the_config_package_is_not_empty() -> None:
    """Guards every scan below against passing on an empty package."""
    assert len(config_files()) >= 5


@pytest.mark.parametrize("path", config_files(), ids=lambda p: p.name)
def test_config_imports_only_approved_greenmachine_packages(path: Path) -> None:
    offenders = internal_offenders(parse_file(path), package_of(path, SRC_ROOT))

    assert not offenders, f"{path.name} imports outside the approved set: {offenders}"


@pytest.mark.parametrize("path", config_files(), ids=lambda p: p.name)
def test_config_imports_no_downstream_package(path: Path) -> None:
    """Dependencies point inward only (ARCHITECTURE.md §4)."""
    imported = {
        record.resolved(package_of(path, SRC_ROOT)) for record in collect_imports(parse_file(path))
    }
    offenders = [
        name
        for name in imported
        for forbidden in FORBIDDEN_INTERNAL
        if name == forbidden or name.startswith(f"{forbidden}.")
    ]

    assert not offenders, f"{path.name} imports a downstream package: {offenders}"


@pytest.mark.parametrize("path", config_files(), ids=lambda p: p.name)
def test_config_uses_only_the_approved_third_party_toolchain(path: Path) -> None:
    offenders = unapproved_third_party(parse_file(path))

    assert not offenders, f"{path.name} imports unapproved third-party code: {offenders}"


@pytest.mark.parametrize("path", config_files(), ids=lambda p: p.name)
def test_config_imports_no_forbidden_library(path: Path) -> None:
    offenders = [
        record.top_level
        for record in collect_imports(parse_file(path))
        if record.top_level in FORBIDDEN_THIRD_PARTY
    ]

    assert not offenders, f"{path.name} imports a forbidden dependency: {offenders}"


@pytest.mark.parametrize("path", config_files(), ids=lambda p: p.name)
def test_config_reads_no_environment_and_opens_no_socket(path: Path) -> None:
    offenders = [
        record.top_level
        for record in collect_imports(parse_file(path))
        if record.top_level in FORBIDDEN_STDLIB
    ]

    assert not offenders, f"{path.name} imports an environment or network module: {offenders}"


# Method names that write to, create, or destroy a filesystem entry. `shutil`'s
# copy/move helpers are covered by the stdlib import ban above (`shutil` may not
# be imported at all), so a bare `copy(...)`/`move(...)` name — which could be an
# innocent dict/list method — is deliberately not listed here.
WRITE_ATTRS = frozenset(
    {
        "write_text",
        "write_bytes",
        "writelines",
        "mkdir",
        "unlink",
        "touch",
        "rmtree",
        "makedirs",
        "dump",  # yaml.dump / yaml.safe_dump to a stream
        "safe_dump",
    }
)


def filesystem_write_offenders(tree: ast.AST) -> list[tuple[int, str]]:
    """Every call that could create, write, or delete a filesystem entry.

    A write is either an attribute call whose name is in :data:`WRITE_ATTRS`
    (``path.write_text(...)``, ``yaml.dump(data, stream)``) or any ``open(...)``
    — configuration is read exclusively through ``Path.read_text``, so any
    ``open`` at all, in any mode, is a write path waiting to happen. Reads via
    ``read_text``/``read_bytes`` are not writes and are not flagged here.
    """
    offenders: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in WRITE_ATTRS:
            offenders.append((node.lineno, func.attr))
        elif isinstance(func, ast.Name) and func.id == "open":
            offenders.append((node.lineno, "open"))
    return offenders


@pytest.mark.parametrize("path", config_files(), ids=lambda p: p.name)
def test_config_has_no_write_path(path: Path) -> None:
    """Configuration is version-controlled and never written by the application.

    No ``save_config``/``update_config`` exists, and no module reaches a write
    call directly either (ENGINEERING_GUIDELINES §8; GM-004 acceptance).
    """
    offenders = filesystem_write_offenders(parse_file(path))

    assert not offenders, f"{path.name} contains a write path: {offenders}"


def test_filesystem_reads_are_confined_to_the_two_reading_modules() -> None:
    """File I/O is confined and read-only, so the rest of the package is pure.

    GM-003's ``loader.py`` reads a configuration; GM-004's ``versioning.py`` reads
    one to version it and reads it back to verify a use seal. No other module
    touches the filesystem, and none writes (see the no-write guard below).
    """
    readers = [
        path.name
        for path in config_files()
        for node in ast.walk(parse_file(path))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"read_text", "read_bytes"}
    ]

    assert set(readers) <= {"loader.py", "versioning.py"}, (
        f"filesystem reads outside the reading modules: {set(readers)}"
    )


# --------------------------------------------------------------------------
# No baseball in production source
# --------------------------------------------------------------------------


def test_no_component_threshold_table_lives_in_source() -> None:
    """Bucket edges and allocations are data; source holds none of them.

    A component identifier sitting next to a numeric literal is the shape a
    hardcoded threshold table takes.
    """
    from greenmachine.domain import ComponentId

    names = {member.value for member in ComponentId}
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or '"""' in stripped:
                continue
            for name in names:
                if name in stripped and any(char.isdigit() for char in stripped):
                    # A digit in a section reference such as "§9.1" is prose.
                    assert "§" in stripped, (
                        f"{path.name}: '{name}' appears beside a numeric literal, which looks "
                        f"like a hardcoded threshold: {stripped!r}"
                    )


# GM-041.5 relocated the disclaimed synthetic configuration out of tests/ so the
# deployed app never reads an executable configuration from the test tree. It
# lives in exactly one place, and that place announces non-production in its
# name. Everything ELSE under config/ would be a production configuration, which
# still cannot exist while Q11-Q16 are open.
NONPRODUCTION_CONFIG_DIR = REPO_ROOT / "config" / "nonproduction"


def test_no_production_yaml_configuration_is_committed() -> None:
    """No approved production model configuration exists (Q11-Q16 open).

    ``config/nonproduction/`` is the one permitted home for a disclaimed,
    non-production configuration. A YAML anywhere else under ``config/`` would
    be a production model configuration, which no ticket has approved.
    """
    config_dir = REPO_ROOT / "config"
    if config_dir.exists():
        committed = [
            path
            for path in [*config_dir.rglob("*.yaml"), *config_dir.rglob("*.yml")]
            if NONPRODUCTION_CONFIG_DIR not in path.parents
        ]
        assert not committed, f"production configuration committed: {committed}"

    assert not list(SRC_ROOT.rglob("*.yaml"))
    assert not list(SRC_ROOT.rglob("*.yml"))


def test_every_nonproduction_configuration_is_loudly_disclaimed() -> None:
    """Anything executable outside tests/ must say what it is, in the file."""
    configurations = sorted(NONPRODUCTION_CONFIG_DIR.rglob("*.yaml"))
    assert configurations, "the non-production configuration directory is populated"
    for path in configurations:
        text = path.read_text(encoding="utf-8").upper()
        assert "NOT A MODEL CONFIGURATION" in text, path.name
        assert "SYNTHETIC" in text, path.name


# Tooling YAML, not model configuration. Enumerated rather than pattern-matched
# so a new file has to be considered rather than silently absorbed.
TOOLING_YAML = frozenset({".pre-commit-config.yaml"})


def test_model_configuration_yaml_lives_only_in_approved_locations() -> None:
    """Two permitted homes, both non-production, and nowhere else.

    ``tests/fixtures/`` holds fixtures the suite builds on; ``config/nonproduction/``
    holds the one disclaimed configuration the deployed app may execute. A model
    configuration anywhere else would be an unapproved production configuration.
    """
    candidates = [
        path
        for path in [*REPO_ROOT.rglob("*.yaml"), *REPO_ROOT.rglob("*.yml")]
        if ".venv" not in path.parts
        and ".github" not in path.parts
        and path.name not in TOOLING_YAML
    ]
    outside = [
        path
        for path in candidates
        if "fixtures" not in path.parts and NONPRODUCTION_CONFIG_DIR not in path.parents
    ]

    assert candidates, "expected the synthetic configurations to be found"
    assert not outside, f"model configuration YAML in an unapproved location: {outside}"


def test_the_relocated_configuration_is_outside_the_test_tree() -> None:
    """Anti-vacuity for the allowance above: the app's configuration really did
    leave tests/, which is the whole point of the GM-041.5 relocation."""
    canonical = NONPRODUCTION_CONFIG_DIR / "gm041_engine_synthetic.yaml"

    assert canonical.is_file()
    assert "tests" not in canonical.relative_to(REPO_ROOT).parts


def test_the_fixtures_are_labelled_synthetic() -> None:
    fixture_root = REPO_ROOT / "tests" / "fixtures" / "config"
    valid = fixture_root / "valid" / "complete_synthetic.yaml"

    assert "SYNTHETIC" in valid.read_text(encoding="utf-8").upper()


# --------------------------------------------------------------------------
# Meta-tests: prove each guard bites
# --------------------------------------------------------------------------


def test_meta_a_downstream_import_is_rejected() -> None:
    tree = seeded("from greenmachine.scoring import resolve\n")

    assert internal_offenders(tree, CONFIG_PACKAGE) == ["greenmachine.scoring"]


def test_meta_a_relative_downstream_import_is_rejected() -> None:
    """`..scoring` never spells greenmachine, but resolves there."""
    tree = seeded("from ..scoring import resolve\n")

    assert internal_offenders(tree, CONFIG_PACKAGE) == ["greenmachine.scoring"]


def test_meta_an_unapproved_common_module_is_rejected() -> None:
    tree = seeded("from greenmachine.common.logging import configure_logger\n")

    assert internal_offenders(tree, CONFIG_PACKAGE) == ["greenmachine.common.logging"]


@pytest.mark.parametrize(
    "source",
    [
        "from greenmachine.domain import ComponentId\n",
        "from greenmachine.common.errors import ConfigurationError\n",
        "from greenmachine.common.numeric import decimal_from\n",
        "from greenmachine.common.ids import content_digest\n",  # GM-004: config_hash
        "from .schema import GreenMachineConfig\n",
        "from greenmachine.config.schema import GreenMachineConfig\n",
    ],
)
def test_meta_approved_imports_are_permitted(source: str) -> None:
    assert internal_offenders(seeded(source), CONFIG_PACKAGE) == []


def test_meta_an_unapproved_common_module_is_still_rejected() -> None:
    """The GM-004 grant is exactly `common.ids`, not the whole `common` package."""
    tree = seeded("from greenmachine.common.clock import SystemClock\n")

    assert internal_offenders(tree, CONFIG_PACKAGE) == ["greenmachine.common.clock"]


def test_meta_an_unapproved_third_party_import_is_rejected() -> None:
    assert unapproved_third_party(seeded("import pandas as pd\n")) == ["pandas"]
    assert unapproved_third_party(seeded("import scipy\n")) == ["scipy"]


def test_meta_the_approved_toolchain_is_permitted() -> None:
    assert unapproved_third_party(seeded("import yaml\nfrom pydantic import BaseModel\n")) == []


def test_meta_stdlib_imports_are_permitted() -> None:
    assert unapproved_third_party(seeded("from decimal import Decimal\nimport re\n")) == []


# --------------------------------------------------------------------------
# Meta-tests: the no-write guard catches real, syntax-valid violations
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source",
    [
        'Path("c.yaml").write_text("x")\n',
        'Path("c.yaml").write_bytes(b"x")\n',
        'open("c.yaml", "w").write("x")\n',
        'open("c.yaml", "a")\n',
        'open("c.yaml", "x")\n',
        'open("c.yaml")\n',
        "handle.writelines(lines)\n",
        "yaml.dump(data, stream)\n",
        "yaml.safe_dump(data, stream)\n",
        'Path("d").mkdir()\n',
        'Path("c.yaml").unlink()\n',
    ],
)
def test_meta_a_write_path_is_rejected(source: str) -> None:
    assert filesystem_write_offenders(seeded(source)), f"guard missed a write: {source!r}"


@pytest.mark.parametrize(
    "source",
    [
        'Path("c.yaml").read_text(encoding="utf-8")\n',
        "location.read_bytes()\n",
        "text.replace('\\r\\n', '\\n')\n",  # str.replace is not a filesystem move
        "yaml.load(text, Loader=StrictConfigLoader)\n",
        "hashlib.sha256(data).hexdigest()\n",
        "config.model_dump(mode='python')\n",
    ],
)
def test_meta_a_read_or_pure_call_is_not_a_write(source: str) -> None:
    assert filesystem_write_offenders(seeded(source)) == [], f"guard false-flagged: {source!r}"
