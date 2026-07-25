"""Profile-aware golden-case discovery, execution, and field-level diffing.

This is the GM-008 golden harness (ADR-0008). A golden case is one directory
under ``tests/golden/cases/`` holding a strict ``case.json`` manifest plus two
canonical GM-006 records: one profile-specific ``InputSnapshot`` and one
expected ``GradeResult``. The golden contract is::

    InputSnapshot + config version reference  ->  GradeResult

The scorer is **injected** (:class:`GoldenScorer`): GM-008 ships only the
test-only stub in :mod:`tests.golden.stub_scorer`, and the Sprint-2 scoring
engine will be injected through the same boundary without changing this module.

Boundary rules, enforced by ``tests/architecture/test_golden_boundaries.py``:
the runner imports only the standard library, ``greenmachine.domain``, and the
``greenmachine.evaluation`` serialization API. It never imports scoring, config,
features, ingestion, persistence, reporting, or the CLI; it never writes a
file; it never reads a clock, the environment, or the network. Golden files are
rewritten only by the explicit developer tool ``scripts/update_goldens.py``.

The errors raised here (:class:`GoldenCaseError`, :class:`GoldenMismatchError`,
:class:`GoldenUpdateError`) are deliberately plain test-infrastructure
exceptions, not ``GreenMachineError`` subtypes.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

from greenmachine.domain import (
    EvaluatedGradeResult,
    InputSnapshot,
    NotEvaluableGradeResult,
    WindowProfile,
)
from greenmachine.evaluation import (
    EvaluationError,
    deserialize_record,
    deserialize_snapshot,
    serialize_record,
)

__all__ = [
    "CASES_ROOT",
    "MANIFEST_FILENAME",
    "DifferenceKind",
    "FieldDifference",
    "GoldenCase",
    "GoldenCaseError",
    "GoldenCaseRun",
    "GoldenMismatchError",
    "GoldenScorer",
    "GoldenUpdateError",
    "assert_case_passes",
    "canonical_structure_differences",
    "contained_case_directory",
    "deterministic_error_message",
    "discover_cases",
    "load_case",
    "run_case",
    "run_cases",
    "score_case",
]

# The committed golden tree. Derived from this file's location, never from the
# current working directory.
CASES_ROOT = Path(__file__).resolve().parent / "cases"

MANIFEST_FILENAME = "case.json"

_MANIFEST_KEYS = frozenset(
    {"case_id", "config_version_identifier", "window_profile", "snapshot_file", "expected_file"}
)

# The only two record contracts a golden expectation may hold. Exact types:
# an arbitrary third GradeResult subtype is not a contract this harness accepts.
_RESULT_TYPES = (EvaluatedGradeResult, NotEvaluableGradeResult)

GradeResultVariant = EvaluatedGradeResult | NotEvaluableGradeResult


# --------------------------------------------------------------------------
# Test-infrastructure errors
# --------------------------------------------------------------------------


class GoldenCaseError(Exception):
    """A golden case is malformed, incomplete, or violated the harness contract."""


class GoldenMismatchError(AssertionError):
    """A golden case ran but the actual result differed from the expectation.

    Carries the case identity and every field-level difference, so a failing
    golden test reads as a reviewable diff rather than an opaque inequality.
    """

    def __init__(self, case_id: str, differences: tuple[FieldDifference, ...]) -> None:
        self.case_id = case_id
        self.differences = differences
        rendered = "\n".join(difference.describe() for difference in differences)
        super().__init__(f"golden case '{case_id}' does not match its expected result:\n{rendered}")


class GoldenUpdateError(Exception):
    """A deliberate golden regeneration was requested but could not proceed."""


# --------------------------------------------------------------------------
# The injected scorer boundary
# --------------------------------------------------------------------------


class GoldenScorer(Protocol):
    """The narrow boundary the future scoring engine will be injected through.

    A scorer is any callable taking the exact decoded snapshot and the case's
    configuration version reference, returning exactly one of the two approved
    GradeResult variants. No scorer is ever selected globally: every runner
    entry point takes the scorer as an explicit argument.
    """

    def __call__(
        self, snapshot: InputSnapshot, config_version_identifier: str, /
    ) -> GradeResultVariant: ...


# --------------------------------------------------------------------------
# Case contract
# --------------------------------------------------------------------------


def _require_non_blank(value: object, description: str) -> str:
    if not isinstance(value, str):
        raise GoldenCaseError(f"{description} must be a string, got {type(value).__name__}")
    if not value.strip():
        raise GoldenCaseError(f"{description} must be a non-empty, non-blank string")
    return value


# The documented case_id convention: a lowercase ASCII stable identifier.
_CASE_ID_CONVENTION = r"^[a-z][a-z0-9_-]*$"
_CASE_ID_PATTERN = re.compile(r"[a-z][a-z0-9_-]*")


def _require_stable_case_id(value: object, owner: str) -> str:
    """Enforce the case_id convention, naming the owner and the received value."""
    if not isinstance(value, str):
        raise GoldenCaseError(f"{owner}: case_id must be a string, got {type(value).__name__}")
    if _CASE_ID_PATTERN.fullmatch(value) is None:
        raise GoldenCaseError(
            f"{owner}: case_id must be a stable identifier matching {_CASE_ID_CONVENTION} "
            f"(a lowercase ASCII letter, then lowercase letters, digits, hyphens, or "
            f"underscores), got {value!r}"
        )
    return value


def _require_simple_filename(value: object, description: str) -> str:
    """A fixture reference is a bare filename inside the case directory.

    Path separators, ``..``, ``.``, drive letters, and absolute paths are all
    rejected, so a manifest can never reach outside its own case directory.
    """
    name = _require_non_blank(value, description)
    if "/" in name or "\\" in name:
        raise GoldenCaseError(
            f"{description} must be a simple filename inside the case directory "
            f"(no path separators), got {name!r}"
        )
    if name in {".", ".."}:
        raise GoldenCaseError(f"{description} must name a file, got {name!r}")
    as_path = Path(name)
    if as_path.is_absolute() or as_path.drive:
        raise GoldenCaseError(f"{description} must be relative, got the absolute path {name!r}")
    return name


@dataclass(frozen=True, slots=True)
class GoldenCase:
    """One loaded, fully validated golden case.

    Immutable and runtime-validated: the snapshot and the expected result must
    each be exactly one approved GM-006 contract, and all three profile
    declarations — manifest, snapshot, expected result — must agree. A case
    represents exactly one :class:`WindowProfile` by construction.
    """

    case_id: str
    directory: Path
    config_version_identifier: str
    window_profile: WindowProfile
    snapshot_filename: str
    expected_filename: str
    snapshot: InputSnapshot
    expected_result: GradeResultVariant

    def __post_init__(self) -> None:
        _require_stable_case_id(self.case_id, "GoldenCase")
        if not isinstance(self.directory, Path):
            raise GoldenCaseError(
                f"GoldenCase.directory must be a Path, got {type(self.directory).__name__}"
            )
        _require_non_blank(self.config_version_identifier, "GoldenCase.config_version_identifier")
        if not isinstance(self.window_profile, WindowProfile):
            raise GoldenCaseError(
                f"GoldenCase.window_profile must be a WindowProfile, got "
                f"{type(self.window_profile).__name__}"
            )
        _require_simple_filename(self.snapshot_filename, "GoldenCase.snapshot_filename")
        _require_simple_filename(self.expected_filename, "GoldenCase.expected_filename")
        if type(self.snapshot) is not InputSnapshot:
            raise GoldenCaseError(
                f"GoldenCase.snapshot must be an InputSnapshot, got {type(self.snapshot).__name__}"
            )
        if type(self.expected_result) not in _RESULT_TYPES:
            raise GoldenCaseError(
                f"GoldenCase.expected_result must be exactly an EvaluatedGradeResult or a "
                f"NotEvaluableGradeResult, got {type(self.expected_result).__name__}"
            )
        if self.snapshot.window_profile is not self.window_profile:
            raise GoldenCaseError(
                f"GoldenCase '{self.case_id}': the snapshot's window_profile "
                f"'{self.snapshot.window_profile.value}' does not equal the case's declared "
                f"profile '{self.window_profile.value}'"
            )
        if self.expected_result.window_profile is not self.window_profile:
            raise GoldenCaseError(
                f"GoldenCase '{self.case_id}': the expected result's window_profile "
                f"'{self.expected_result.window_profile.value}' does not equal the case's "
                f"declared profile '{self.window_profile.value}'"
            )


# --------------------------------------------------------------------------
# Strict manifest reading
# --------------------------------------------------------------------------


def _reject_float(text: str) -> float:
    raise GoldenCaseError(
        f"a golden case manifest must not contain floating-point numbers, got {text!r}"
    )


def _read_manifest(directory: Path) -> dict[str, str]:
    manifest_path = directory / MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise GoldenCaseError(
            f"golden case directory {directory} has no {MANIFEST_FILENAME}; every directory "
            f"under a golden case root must be a complete case"
        )
    try:
        parsed: object = json.loads(
            manifest_path.read_bytes().decode("utf-8"), parse_float=_reject_float
        )
    except UnicodeDecodeError as exc:
        raise GoldenCaseError(f"{manifest_path} is not UTF-8: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise GoldenCaseError(f"{manifest_path} is not valid JSON: {exc}") from exc

    if not isinstance(parsed, dict):
        raise GoldenCaseError(
            f"{manifest_path}: the manifest root must be a JSON object, got {type(parsed).__name__}"
        )
    unknown = sorted(set(parsed) - _MANIFEST_KEYS)
    if unknown:
        raise GoldenCaseError(f"{manifest_path}: unknown manifest field(s): {unknown}")
    missing = sorted(_MANIFEST_KEYS - set(parsed))
    if missing:
        raise GoldenCaseError(f"{manifest_path}: missing required manifest field(s): {missing}")

    fields: dict[str, str] = {}
    for key in sorted(_MANIFEST_KEYS):
        if key == "case_id":
            fields[key] = _require_stable_case_id(parsed[key], str(manifest_path))
        else:
            fields[key] = _require_non_blank(parsed[key], f"{manifest_path}: {key}")
    return fields


def _resolve_fixture_file(directory: Path, name: str, key: str) -> Path:
    manifest_path = directory / MANIFEST_FILENAME
    filename = _require_simple_filename(name, f"{manifest_path}: {key}")
    target = directory / filename
    # Belt and braces on top of the filename rules: the resolved file must sit
    # directly inside the case directory.
    if target.resolve().parent != directory.resolve():
        raise GoldenCaseError(f"{manifest_path}: {key} {name!r} escapes the case directory")
    if not target.is_file():
        raise GoldenCaseError(
            f"{manifest_path}: {key} references {name!r}, which does not exist as a regular "
            f"file in the case directory"
        )
    return target


def load_case(directory: Path) -> GoldenCase:
    """Load and strictly validate one golden case directory.

    The snapshot is decoded through the approved GM-006 decoder, which verifies
    its content-derived identity; the expected result must decode to exactly one
    of the two approved GradeResult variants; and the manifest, snapshot, and
    expected result must declare the same single :class:`WindowProfile`.
    """
    if not isinstance(directory, Path):
        raise GoldenCaseError(
            f"a golden case directory must be a Path, got {type(directory).__name__}"
        )
    directory = directory.resolve()
    if not directory.is_dir():
        raise GoldenCaseError(f"golden case directory {directory} does not exist")

    fields = _read_manifest(directory)
    manifest_path = directory / MANIFEST_FILENAME

    try:
        profile = WindowProfile(fields["window_profile"])
    except ValueError as exc:
        raise GoldenCaseError(
            f"{manifest_path}: window_profile {fields['window_profile']!r} is not a valid "
            f"WindowProfile; expected one of "
            f"{sorted(member.value for member in WindowProfile)}"
        ) from exc

    snapshot_path = _resolve_fixture_file(directory, fields["snapshot_file"], "snapshot_file")
    expected_path = _resolve_fixture_file(directory, fields["expected_file"], "expected_file")

    try:
        snapshot = deserialize_snapshot(snapshot_path.read_bytes())
    except EvaluationError as exc:
        raise GoldenCaseError(
            f"{manifest_path}: snapshot_file {fields['snapshot_file']!r} is not a valid "
            f"canonical InputSnapshot record: {exc}"
        ) from exc

    try:
        expected: object = deserialize_record(expected_path.read_bytes())
    except EvaluationError as exc:
        raise GoldenCaseError(
            f"{manifest_path}: expected_file {fields['expected_file']!r} is not a valid "
            f"canonical record: {exc}"
        ) from exc
    if type(expected) not in _RESULT_TYPES:
        raise GoldenCaseError(
            f"{manifest_path}: expected_file {fields['expected_file']!r} must hold exactly an "
            f"evaluated_grade_result or a not_evaluable_grade_result record, got "
            f"{type(expected).__name__}"
        )
    assert isinstance(expected, _RESULT_TYPES)  # narrows for the type checker

    if snapshot.window_profile is not profile:
        raise GoldenCaseError(
            f"{manifest_path}: window_profile declares '{profile.value}' but the snapshot "
            f"record carries '{snapshot.window_profile.value}'; a golden case represents "
            f"exactly one profile"
        )
    if expected.window_profile is not profile:
        raise GoldenCaseError(
            f"{manifest_path}: window_profile declares '{profile.value}' but the expected "
            f"result carries '{expected.window_profile.value}'; a golden case represents "
            f"exactly one profile"
        )

    return GoldenCase(
        case_id=fields["case_id"],
        directory=directory,
        config_version_identifier=fields["config_version_identifier"],
        window_profile=profile,
        snapshot_filename=fields["snapshot_file"],
        expected_filename=fields["expected_file"],
        snapshot=snapshot,
        expected_result=expected,
    )


def contained_case_directory(entry: Path, root: Path) -> Path:
    """Resolve a case-directory candidate, refusing anything that escapes the root.

    A golden case discovered under an explicit root must remain inside that
    resolved root: a symlinked case directory is rejected outright, and any
    directory whose resolved path lands outside the resolved root (a junction,
    a mount trick) is rejected too. Returns the resolved, contained directory.
    Never leaks a raw ``ValueError`` or ``OSError`` — every refusal is a
    :class:`GoldenCaseError` naming the entry and the root.
    """
    if not isinstance(entry, Path) or not isinstance(root, Path):
        raise GoldenCaseError(
            f"contained_case_directory expects Paths, got {type(entry).__name__} and "
            f"{type(root).__name__}"
        )
    resolved_root = root.resolve()
    if entry.is_symlink():
        raise GoldenCaseError(
            f"golden case directory {entry} is a symlink; a golden case must be a regular "
            f"directory inside its case root {resolved_root}"
        )
    resolved = entry.resolve()
    if resolved == resolved_root or not resolved.is_relative_to(resolved_root):
        raise GoldenCaseError(
            f"golden case directory {entry} resolves to {resolved}, which is not inside "
            f"the case root {resolved_root}; a discovered case may never escape its root"
        )
    return resolved


def discover_cases(root: Path) -> tuple[GoldenCase, ...]:
    """Discover every golden case under ``root``, in deterministic order.

    Every *directory* under the root must be a complete, valid case — a partial
    case fails loudly, and a case directory must be a regular directory whose
    resolved path stays inside the resolved root (symlinks and other escapes
    are rejected, see :func:`contained_case_directory`). Plain files at the
    root (a ``.gitkeep``, a note) cannot be mistaken for a case and are
    ignored. Ordering is by ``case_id`` with the directory path as a final
    tie-breaker, never by filesystem enumeration order; duplicate case ids are
    rejected.
    """
    if not isinstance(root, Path):
        raise GoldenCaseError(f"a golden case root must be a Path, got {type(root).__name__}")
    root = root.resolve()
    if not root.is_dir():
        raise GoldenCaseError(f"golden case root {root} does not exist")

    case_directories = sorted(
        (entry for entry in root.iterdir() if entry.is_dir()), key=lambda entry: entry.name
    )
    cases = [load_case(contained_case_directory(directory, root)) for directory in case_directories]

    seen: dict[str, Path] = {}
    for case in cases:
        if case.case_id in seen:
            raise GoldenCaseError(
                f"duplicate golden case_id '{case.case_id}' in {seen[case.case_id]} and "
                f"{case.directory}"
            )
        seen[case.case_id] = case.directory

    return tuple(sorted(cases, key=lambda case: (case.case_id, str(case.directory))))


# --------------------------------------------------------------------------
# Field-level structural diffing over canonical records
# --------------------------------------------------------------------------


class DifferenceKind(Enum):
    """The five ways two canonical record structures can disagree."""

    MISSING_KEY = "missing_key"
    UNEXPECTED_KEY = "unexpected_key"
    TYPE_MISMATCH = "type_mismatch"
    VALUE_MISMATCH = "value_mismatch"
    VARIANT_MISMATCH = "variant_mismatch"


_KIND_LABELS = {
    DifferenceKind.MISSING_KEY: "missing from actual",
    DifferenceKind.UNEXPECTED_KEY: "unexpected in actual",
    DifferenceKind.TYPE_MISMATCH: "type mismatch",
    DifferenceKind.VALUE_MISMATCH: "value mismatch",
    DifferenceKind.VARIANT_MISMATCH: "result-variant mismatch",
}


@dataclass(frozen=True, slots=True)
class FieldDifference:
    """One field-level difference between an expected and an actual structure.

    ``expected`` and ``actual`` are exact JSON renderings of the canonical
    values (Decimals appear as their canonical base-10 strings), or ``None``
    where the side has no value at all.
    """

    path: str
    kind: DifferenceKind
    expected: str | None
    actual: str | None

    def describe(self) -> str:
        absent = "<absent>"
        return (
            f"{self.path or '<root>'}: {_KIND_LABELS[self.kind]}\n"
            f"    expected {self.expected if self.expected is not None else absent}\n"
            f"    actual   {self.actual if self.actual is not None else absent}"
        )


def _json_type(value: object) -> str:
    # bool must be tested before int: True is an int in Python but not in JSON.
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    raise GoldenCaseError(
        f"unsupported value of type {type(value).__name__} in a canonical structure"
    )


def _render(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _render_typed(value: object) -> str:
    return f"{_json_type(value)} {_render(value)}"


def _child(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


def canonical_structure_differences(
    expected: object, actual: object
) -> tuple[FieldDifference, ...]:
    """Every field-level difference between two parsed canonical structures.

    Mappings are compared in sorted key order, sequences in index order, and
    scalars exactly — so the resulting differences are deterministic, carry
    exact field paths, and render Decimal-carrying strings without any float
    round-trip. Equal structures produce an empty tuple.
    """
    differences: list[FieldDifference] = []
    _walk("", expected, actual, differences)
    return tuple(differences)


def _walk(path: str, expected: object, actual: object, differences: list[FieldDifference]) -> None:
    expected_type = _json_type(expected)
    actual_type = _json_type(actual)
    if expected_type != actual_type:
        differences.append(
            FieldDifference(
                path=path,
                kind=DifferenceKind.TYPE_MISMATCH,
                expected=_render_typed(expected),
                actual=_render_typed(actual),
            )
        )
        return

    if isinstance(expected, dict) and isinstance(actual, dict):
        for key in sorted(set(expected) | set(actual)):
            key_path = _child(path, key)
            if key not in actual:
                differences.append(
                    FieldDifference(
                        path=key_path,
                        kind=DifferenceKind.MISSING_KEY,
                        expected=_render(expected[key]),
                        actual=None,
                    )
                )
            elif key not in expected:
                differences.append(
                    FieldDifference(
                        path=key_path,
                        kind=DifferenceKind.UNEXPECTED_KEY,
                        expected=None,
                        actual=_render(actual[key]),
                    )
                )
            else:
                _walk(key_path, expected[key], actual[key], differences)
        return

    if isinstance(expected, list) and isinstance(actual, list):
        for index in range(min(len(expected), len(actual))):
            _walk(f"{path}[{index}]", expected[index], actual[index], differences)
        for index in range(min(len(expected), len(actual)), len(expected)):
            differences.append(
                FieldDifference(
                    path=f"{path}[{index}]",
                    kind=DifferenceKind.MISSING_KEY,
                    expected=_render(expected[index]),
                    actual=None,
                )
            )
        for index in range(min(len(expected), len(actual)), len(actual)):
            differences.append(
                FieldDifference(
                    path=f"{path}[{index}]",
                    kind=DifferenceKind.UNEXPECTED_KEY,
                    expected=None,
                    actual=_render(actual[index]),
                )
            )
        return

    if expected != actual:
        differences.append(
            FieldDifference(
                path=path,
                kind=DifferenceKind.VALUE_MISMATCH,
                expected=_render(expected),
                actual=_render(actual),
            )
        )


# --------------------------------------------------------------------------
# Execution
# --------------------------------------------------------------------------


def deterministic_error_message(failure: BaseException) -> str:
    """Render an exception's arguments deterministically — never via repr.

    ``str(exception)`` and ``repr`` can embed memory addresses, nondeterministic
    custom ``__str__``/``__repr__`` output, or environment-specific text, so
    neither is ever consulted. The policy, over ``failure.args`` only:

    * no arguments → ``""``
    * exactly one ``str`` argument → that string, verbatim
    * every argument a deterministic primitive (``str``/``int``/``bool``/
      ``None``) → the canonical JSON array of them, order preserved
    * anything else → ``"non-text exception argument types: ..."`` naming only
      the stable argument type names

    The result contains no memory address, no object repr, no traceback text,
    and no path that was not itself supplied as a plain string argument.
    """
    arguments = failure.args
    if not arguments:
        return ""
    if len(arguments) == 1 and isinstance(arguments[0], str):
        return arguments[0]
    if all(argument is None or isinstance(argument, str | int | bool) for argument in arguments):
        return json.dumps(list(arguments), ensure_ascii=False)
    type_names = ", ".join(type(argument).__name__ for argument in arguments)
    return f"non-text exception argument types: {type_names}"


@dataclass(frozen=True, slots=True)
class GoldenCaseRun:
    """The immutable outcome of running one golden case against a scorer.

    Exactly one of three shapes, enforced at construction: a pass (no
    differences, no error), a canonical mismatch (``differences`` populated),
    or an execution failure (``error_type`` and ``error_message`` populated
    together — the stable exception class name and the deterministic rendering
    of its arguments via :func:`deterministic_error_message`, never an object
    repr). Differences and an execution failure cannot be combined.
    ``case_id`` is always present, so a batch report can name every case
    regardless of how it fared.
    """

    case_id: str
    directory: Path
    differences: tuple[FieldDifference, ...]
    error_type: str | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        if (self.error_type is None) != (self.error_message is None):
            raise GoldenCaseError(
                f"GoldenCaseRun '{self.case_id}': error_type and error_message form one "
                f"execution-failure state and must be set together, got error_type="
                f"{self.error_type!r} with error_message={self.error_message!r}"
            )
        if self.error_type is not None and self.differences:
            raise GoldenCaseError(
                f"GoldenCaseRun '{self.case_id}': canonical differences and an execution "
                f"failure cannot be combined on one run"
            )

    @property
    def passed(self) -> bool:
        return not self.differences and self.error_type is None


def score_case(case: GoldenCase, scorer: GoldenScorer) -> GradeResultVariant:
    """Invoke the injected scorer and validate its result against the contract.

    The scorer receives the exact decoded snapshot and the case's configuration
    version reference. A result that is not exactly one of the two approved
    GradeResult variants, or that carries a different profile than the case
    declares, is rejected — it would otherwise poison the golden comparison.
    """
    if not isinstance(case, GoldenCase):
        raise GoldenCaseError(f"score_case expects a GoldenCase, got {type(case).__name__}")
    if not callable(scorer):
        raise GoldenCaseError(f"the injected scorer must be callable, got {type(scorer).__name__}")

    result = scorer(case.snapshot, case.config_version_identifier)
    if type(result) not in _RESULT_TYPES:
        raise GoldenCaseError(
            f"golden case '{case.case_id}': the scorer returned {type(result).__name__}; a "
            f"scorer must return exactly an EvaluatedGradeResult or a NotEvaluableGradeResult"
        )
    if result.window_profile is not case.window_profile:
        raise GoldenCaseError(
            f"golden case '{case.case_id}': the scorer returned a result for profile "
            f"'{result.window_profile.value}', but the case declares "
            f"'{case.window_profile.value}'; profiles are never substituted"
        )
    return result


def _parse_canonical(data: bytes) -> object:
    return json.loads(data.decode("utf-8"), parse_float=_reject_float)


def run_case(case: GoldenCase, scorer: GoldenScorer) -> GoldenCaseRun:
    """Run one case: score the snapshot and diff the result against expectation.

    Comparison is lossless: both results are serialized through the one
    canonical GM-006 encoder and compared structurally, so every difference is
    reported with its exact field path and exact rendered values. Execution
    performs no writes and mutates nothing.
    """
    actual = score_case(case, scorer)

    if type(actual) is not type(case.expected_result):
        differences: tuple[FieldDifference, ...] = (
            FieldDifference(
                path="record_type",
                kind=DifferenceKind.VARIANT_MISMATCH,
                expected=type(case.expected_result).__name__,
                actual=type(actual).__name__,
            ),
        )
        return GoldenCaseRun(
            case_id=case.case_id, directory=case.directory, differences=differences
        )

    expected_bytes = serialize_record(case.expected_result)
    actual_bytes = serialize_record(actual)
    if expected_bytes == actual_bytes:
        return GoldenCaseRun(case_id=case.case_id, directory=case.directory, differences=())

    differences = canonical_structure_differences(
        _parse_canonical(expected_bytes), _parse_canonical(actual_bytes)
    )
    return GoldenCaseRun(case_id=case.case_id, directory=case.directory, differences=differences)


def run_cases(
    cases: tuple[GoldenCase, ...] | list[GoldenCase], scorer: GoldenScorer
) -> tuple[GoldenCaseRun, ...]:
    """Run every case in deterministic order, reporting each outcome.

    One case never hides another: every supplied case is executed and exactly
    one immutable :class:`GoldenCaseRun` is returned per case, ordered by
    ``case_id`` with the directory path as the tie-breaker regardless of input
    order. Where :func:`run_case` stays strict and raises — an unsupported
    scorer result, a wrong-profile result, or an ordinary scorer exception —
    this batch entry point records the failure on that case's run
    (``error_type``/``error_message``) and continues with the remaining cases.
    Nothing is discarded: every recorded failure is surfaced in the returned
    outcomes. ``KeyboardInterrupt`` and ``SystemExit`` are never caught.
    """
    for case in cases:
        if not isinstance(case, GoldenCase):
            raise GoldenCaseError(f"run_cases expects GoldenCase items, got {type(case).__name__}")
    ordered = sorted(cases, key=lambda case: (case.case_id, str(case.directory)))
    outcomes: list[GoldenCaseRun] = []
    for case in ordered:
        try:
            outcomes.append(run_case(case, scorer))
        except Exception as failure:  # recorded per case, never swallowed (see docstring)
            outcomes.append(
                GoldenCaseRun(
                    case_id=case.case_id,
                    directory=case.directory,
                    differences=(),
                    error_type=type(failure).__name__,
                    error_message=deterministic_error_message(failure),
                )
            )
    return tuple(outcomes)


def assert_case_passes(case: GoldenCase, scorer: GoldenScorer) -> None:
    """Pytest-facing helper: raise a readable :class:`GoldenMismatchError` on drift."""
    run = run_case(case, scorer)
    if not run.passed:
        raise GoldenMismatchError(case.case_id, run.differences)
