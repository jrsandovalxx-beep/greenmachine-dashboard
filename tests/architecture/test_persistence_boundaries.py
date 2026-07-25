"""Boundaries for the persistence layer: append-only, isolated, deterministic.

The ports and adapters may reach ``domain`` and the narrow ``common`` primitives
(errors, deterministic IDs, canonical serialization) and nothing else — no
config, no downstream layer, no third-party client, no filesystem, no network,
no environment, no clock, no randomness, and no durable-storage module. The
repository surface itself is guarded structurally: exactly ``append``, ``get``,
and ``query``, with no update/delete/upsert-shaped operation anywhere, explicit
sorting in every query, and no exposure of a backing collection.
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import pytest
from static_analysis import collect_imports, package_of, third_party_offenders

from greenmachine.domain import OutcomeRecord

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
PERSISTENCE_ROOT = SRC_ROOT / "greenmachine" / "persistence"

PERSISTENCE_PACKAGE = "greenmachine.persistence"

APPROVED_INTERNAL = frozenset(
    {
        "greenmachine.domain",
        "greenmachine.common.errors",
        "greenmachine.common.ids",
        "greenmachine.common.serialization",
    }
)

FORBIDDEN_INTERNAL = (
    "greenmachine.config",
    "greenmachine.scoring",
    "greenmachine.validation",
    "greenmachine.features",
    "greenmachine.ingestion",
    "greenmachine.reporting",
    "greenmachine.cli",
    "greenmachine.evaluation",
)

# I/O, non-determinism, and durable-storage modules.
FORBIDDEN_STDLIB = frozenset(
    {
        "os",
        "socket",
        "subprocess",
        "shutil",
        "urllib",
        "http",
        "tempfile",
        "pathlib",
        "sqlite3",
        "dbm",
        "shelve",
        "pickle",
        "random",
        "secrets",
        "uuid",
        "time",
    }
)

FORBIDDEN_SOURCE_PATTERNS = (
    "datetime.now",
    "utcnow",
    ".today(",
    "time.time",
    "uuid4",
    "uuid1",
    "random.",
    "os.environ",
    "getenv",
    "open(",
    "Path(",
)

# The only public repository operations. Anything else — update, delete, upsert,
# replace, save, put, set, remove, clear, truncate — is a history-rewrite path.
ALLOWED_REPOSITORY_OPERATIONS = frozenset({"append", "get", "query"})
FORBIDDEN_OPERATIONS = frozenset(
    {
        "update",
        "delete",
        "upsert",
        "replace",
        "save",
        "put",
        "set",
        "remove",
        "clear",
        "truncate",
        "pop",
        "discard",
        "overwrite",
    }
)


def persistence_files() -> list[Path]:
    return sorted(PERSISTENCE_ROOT.rglob("*.py"))


def parse_file(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def seeded(source: str) -> ast.Module:
    try:
        return ast.parse(source)
    except SyntaxError as exc:  # pragma: no cover - the snippets are valid
        pytest.fail(f"seeded source must be syntactically valid, but did not parse: {exc}")


def internal_offenders(tree: ast.Module, package: str) -> list[str]:
    offenders: list[str] = []
    for record in collect_imports(tree):
        resolved = record.resolved(package)
        if not resolved.startswith("greenmachine"):
            continue
        if resolved == package or resolved.startswith(f"{package}."):
            continue  # intra-persistence
        if any(
            resolved == approved or resolved.startswith(f"{approved}.")
            for approved in APPROVED_INTERNAL
        ):
            continue
        offenders.append(resolved)
    return offenders


def repository_classes(tree: ast.Module) -> list[ast.ClassDef]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name.endswith("Repository")
    ]


def public_method_names(class_node: ast.ClassDef) -> set[str]:
    return {
        node.name
        for node in class_node.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and not node.name.startswith("_")
    }


def repository_operation_offenders(tree: ast.Module) -> list[tuple[str, str]]:
    """(class, method) pairs that are outside the append/get/query surface."""
    offenders: list[tuple[str, str]] = []
    for class_node in repository_classes(tree):
        for name in sorted(public_method_names(class_node)):
            if name not in ALLOWED_REPOSITORY_OPERATIONS:
                offenders.append((class_node.name, name))
    return offenders


def forbidden_operation_offenders(tree: ast.Module) -> list[tuple[str, str]]:
    """(class, method) pairs whose name is a history-rewrite operation."""
    offenders: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                if (
                    isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)
                    and child.name.lstrip("_") in FORBIDDEN_OPERATIONS
                ):
                    offenders.append((node.name, child.name))
    return offenders


def query_methods_without_sorted(tree: ast.Module) -> list[str]:
    """Repository classes whose ``query`` body never calls ``sorted``."""
    offenders: list[str] = []
    for class_node in repository_classes(tree):
        for child in class_node.body:
            if isinstance(child, ast.FunctionDef) and child.name == "query":
                calls_sorted = any(
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "sorted"
                    for node in ast.walk(child)
                )
                if not calls_sorted:
                    offenders.append(class_node.name)
    return offenders


def bare_private_attribute_returns(tree: ast.Module) -> list[tuple[str, str]]:
    """Public methods that return ``self._x`` directly, exposing internals."""
    offenders: list[tuple[str, str]] = []
    for class_node in ast.walk(tree):
        if not isinstance(class_node, ast.ClassDef):
            continue
        for method in class_node.body:
            if not isinstance(method, ast.FunctionDef) or method.name.startswith("_"):
                continue
            for node in ast.walk(method):
                if (
                    isinstance(node, ast.Return)
                    and isinstance(node.value, ast.Attribute)
                    and isinstance(node.value.value, ast.Name)
                    and node.value.value.id == "self"
                    and node.value.attr.startswith("_")
                ):
                    offenders.append((class_node.name, method.name))
    return offenders


# --------------------------------------------------------------------------
# The real package
# --------------------------------------------------------------------------


def test_the_persistence_package_is_populated() -> None:
    assert len(persistence_files()) >= 4


@pytest.mark.parametrize("path", persistence_files(), ids=lambda p: p.name)
def test_persistence_imports_only_approved_greenmachine_packages(path: Path) -> None:
    offenders = internal_offenders(parse_file(path), package_of(path, SRC_ROOT))
    assert not offenders, f"{path.name} imports outside the approved set: {offenders}"


@pytest.mark.parametrize("path", persistence_files(), ids=lambda p: p.name)
def test_persistence_imports_no_forbidden_layer(path: Path) -> None:
    imported = {
        record.resolved(package_of(path, SRC_ROOT)) for record in collect_imports(parse_file(path))
    }
    offenders = [
        name
        for name in imported
        for forbidden in FORBIDDEN_INTERNAL
        if name == forbidden or name.startswith(f"{forbidden}.")
    ]
    assert not offenders, f"{path.name} imports a forbidden layer: {offenders}"


@pytest.mark.parametrize("path", persistence_files(), ids=lambda p: p.name)
def test_persistence_uses_no_third_party_library(path: Path) -> None:
    offenders = third_party_offenders(parse_file(path))
    assert not offenders, f"{path.name} imports third-party code: {offenders}"


@pytest.mark.parametrize("path", persistence_files(), ids=lambda p: p.name)
def test_persistence_imports_no_io_or_nondeterministic_module(path: Path) -> None:
    offenders = [
        record.top_level
        for record in collect_imports(parse_file(path))
        if record.top_level in FORBIDDEN_STDLIB
    ]
    assert not offenders, f"{path.name} imports a forbidden stdlib module: {offenders}"


@pytest.mark.parametrize("path", persistence_files(), ids=lambda p: p.name)
def test_persistence_reads_no_clock_randomness_or_filesystem(path: Path) -> None:
    code = "\n".join(
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )
    offenders = [pattern for pattern in FORBIDDEN_SOURCE_PATTERNS if pattern in code]
    assert not offenders, f"{path.name} contains a forbidden construct: {offenders}"


# --------------------------------------------------------------------------
# The append-only surface
# --------------------------------------------------------------------------


@pytest.mark.parametrize("module", ["ports.py", "in_memory.py"])
def test_repository_classes_expose_only_append_get_query(module: str) -> None:
    tree = parse_file(PERSISTENCE_ROOT / module)
    assert repository_classes(tree), f"{module} must define repository classes"
    offenders = repository_operation_offenders(tree)
    assert not offenders, f"{module} has repository operations beyond append/get/query: {offenders}"


@pytest.mark.parametrize("path", persistence_files(), ids=lambda p: p.name)
def test_no_history_rewrite_operation_exists_anywhere(path: Path) -> None:
    offenders = forbidden_operation_offenders(parse_file(path))
    assert not offenders, f"{path.name} defines a history-rewrite operation: {offenders}"


def test_every_adapter_query_sorts_explicitly() -> None:
    tree = parse_file(PERSISTENCE_ROOT / "in_memory.py")
    offenders = query_methods_without_sorted(tree)
    assert not offenders, f"query without explicit sorted(): {offenders}"


def test_no_public_method_returns_a_backing_collection() -> None:
    tree = parse_file(PERSISTENCE_ROOT / "in_memory.py")
    offenders = bare_private_attribute_returns(tree)
    assert not offenders, f"a public method returns internal state directly: {offenders}"


# --------------------------------------------------------------------------
# Contract placement
# --------------------------------------------------------------------------


def test_outcome_record_has_no_supersedes_or_identity_field() -> None:
    field_names = {field.name for field in dataclasses.fields(OutcomeRecord)}
    assert field_names == {"game_id", "batter_id", "hit_at_least_one_home_run"}


def test_outcome_revision_lives_outside_the_domain() -> None:
    import greenmachine.domain as domain

    assert not hasattr(domain, "OutcomeRevision")
    assert not hasattr(domain, "OutcomeRevisionId")
    domain_root = SRC_ROOT / "greenmachine" / "domain"
    for path in sorted(domain_root.rglob("*.py")):
        class_names = {
            node.name for node in ast.walk(parse_file(path)) if isinstance(node, ast.ClassDef)
        }
        assert "OutcomeRevision" not in class_names, f"{path.name} defines OutcomeRevision"


def test_the_repositories_accept_only_their_own_record_types() -> None:
    import synthetic_records as sr

    from greenmachine.persistence import (
        InMemoryEvaluationRepository,
        InMemoryOutcomeRepository,
        MalformedRepositoryInputError,
        create_outcome_revision,
    )

    evaluations = InMemoryEvaluationRepository()
    with pytest.raises(MalformedRepositoryInputError):
        evaluations.append(sr.outcome_record())  # type: ignore[arg-type]
    with pytest.raises(MalformedRepositoryInputError):
        evaluations.append(create_outcome_revision(sr.outcome_record()))  # type: ignore[arg-type]

    outcomes = InMemoryOutcomeRepository()
    with pytest.raises(MalformedRepositoryInputError):
        outcomes.append(sr.outcome_record())  # type: ignore[arg-type]
    with pytest.raises(MalformedRepositoryInputError):
        outcomes.append(sr.evaluation_envelope())  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Meta-tests: the guards bite on syntax-valid violations
# --------------------------------------------------------------------------


def test_meta_an_update_method_is_detected() -> None:
    tree = seeded(
        "class SeededRepository:\n"
        "    def append(self, record): ...\n"
        "    def update(self, record): ...\n"
    )
    assert repository_operation_offenders(tree) == [("SeededRepository", "update")]
    assert ("SeededRepository", "update") in forbidden_operation_offenders(tree)


def test_meta_a_delete_method_is_detected() -> None:
    tree = seeded("class SeededRepository:\n    def delete(self, record_id): ...\n")
    assert ("SeededRepository", "delete") in forbidden_operation_offenders(tree)


def test_meta_an_upsert_method_is_detected() -> None:
    tree = seeded("class SeededStore:\n    def upsert(self, record): ...\n")
    assert ("SeededStore", "upsert") in forbidden_operation_offenders(tree)


def test_meta_a_privately_spelled_rewrite_is_detected() -> None:
    """A leading underscore does not launder a delete."""
    tree = seeded("class SeededRepository:\n    def _delete(self, record_id): ...\n")
    assert ("SeededRepository", "_delete") in forbidden_operation_offenders(tree)


def test_meta_an_unsorted_query_is_detected() -> None:
    tree = seeded(
        "class SeededRepository:\n"
        "    def query(self, query):\n"
        "        return tuple(self._records.values())\n"
    )
    assert query_methods_without_sorted(tree) == ["SeededRepository"]


def test_meta_a_sorted_query_passes() -> None:
    tree = seeded(
        "class SeededRepository:\n"
        "    def query(self, query):\n"
        "        return tuple(sorted(self._records.values(), key=key))\n"
    )
    assert query_methods_without_sorted(tree) == []


def test_meta_returning_the_backing_dictionary_is_detected() -> None:
    tree = seeded("class SeededRepository:\n    def records(self):\n        return self._records\n")
    assert bare_private_attribute_returns(tree) == [("SeededRepository", "records")]


def test_meta_a_config_import_is_rejected() -> None:
    tree = seeded("from greenmachine.config import load_config\n")
    offenders = internal_offenders(tree, PERSISTENCE_PACKAGE)
    assert offenders == ["greenmachine.config"]


def test_meta_an_evaluation_import_is_rejected() -> None:
    tree = seeded("from greenmachine.evaluation import serialize_record\n")
    assert internal_offenders(tree, PERSISTENCE_PACKAGE) == ["greenmachine.evaluation"]


@pytest.mark.parametrize(
    "source",
    [
        "from greenmachine.domain import InputSnapshot\n",
        "from greenmachine.common.errors import PersistenceError\n",
        "from greenmachine.common.ids import deterministic_id\n",
        "from .ports import SnapshotQuery\n",
    ],
)
def test_meta_approved_imports_are_permitted(source: str) -> None:
    assert internal_offenders(seeded(source), PERSISTENCE_PACKAGE) == []


def test_meta_a_database_client_is_rejected() -> None:
    assert third_party_offenders(seeded("import sqlalchemy\n"))
    assert third_party_offenders(seeded("import psycopg2\n"))
