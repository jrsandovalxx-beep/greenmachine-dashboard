"""Golden execution semantics: deterministic order, readable diffs, no writes.

Corruption scenarios copy a committed case into ``tmp_path`` and mutate the
copy — the repository's committed cases are never altered in place.
"""

from __future__ import annotations

import dataclasses
import json
import shutil
from decimal import Decimal
from pathlib import Path

import pytest
from tests.golden.runner import (
    CASES_ROOT,
    DifferenceKind,
    GoldenCase,
    GoldenCaseError,
    GoldenCaseRun,
    GoldenMismatchError,
    assert_case_passes,
    discover_cases,
    load_case,
    run_case,
    run_cases,
    score_case,
)
from tests.golden.stub_scorer import score_snapshot

from greenmachine.domain import (
    EvaluatedGradeResult,
    InputSnapshot,
    NotEvaluableGradeResult,
    WindowProfile,
)

RECENT_CASE_ID = "synthetic-recent-evaluated"
LONG_TERM_CASE_ID = "synthetic-long-term-evaluated"
NOT_EVALUABLE_CASE_ID = "synthetic-recent-not-evaluable"


def committed_case(case_id: str) -> GoldenCase:
    by_id = {case.case_id: case for case in discover_cases(CASES_ROOT)}
    return by_id[case_id]


def copy_case(case_id: str, tmp_path: Path) -> Path:
    """Copy one committed case directory into a temporary tree."""
    destination = tmp_path / case_id
    shutil.copytree(CASES_ROOT / case_id, destination)
    return destination


def mutate_expected(directory: Path, mutate: object) -> None:
    """Apply a JSON-level mutation to the copied case's expected file."""
    expected_path = directory / "expected_grade_result.json"
    parsed = json.loads(expected_path.read_bytes().decode("utf-8"))
    mutate(parsed)  # type: ignore[operator]
    expected_path.write_bytes(json.dumps(parsed).encode("utf-8"))


# --------------------------------------------------------------------------
# Passing execution
# --------------------------------------------------------------------------


def test_unmodified_recent_case_passes() -> None:
    run = run_case(committed_case(RECENT_CASE_ID), score_snapshot)
    assert run.passed
    assert run.differences == ()


def test_unmodified_long_term_case_passes() -> None:
    run = run_case(committed_case(LONG_TERM_CASE_ID), score_snapshot)
    assert run.passed


def test_unmodified_not_evaluable_case_passes() -> None:
    run = run_case(committed_case(NOT_EVALUABLE_CASE_ID), score_snapshot)
    assert run.passed


def test_run_cases_executes_in_deterministic_order_regardless_of_input_order() -> None:
    cases = list(discover_cases(CASES_ROOT))
    forward = run_cases(cases, score_snapshot)
    backward = run_cases(list(reversed(cases)), score_snapshot)

    assert [run.case_id for run in forward] == sorted(case.case_id for case in cases)
    assert forward == backward


def test_run_results_are_immutable() -> None:
    run = run_case(committed_case(RECENT_CASE_ID), score_snapshot)
    with pytest.raises(AttributeError):
        run.case_id = "other"  # type: ignore[misc]
    assert isinstance(run, GoldenCaseRun)
    assert isinstance(run.differences, tuple)


def _mixed_outcome_scorer(
    snapshot: InputSnapshot, config_version_identifier: str, /
) -> EvaluatedGradeResult | NotEvaluableGradeResult:
    """First case: unsupported output. Second: ordinary exception. Third: passes.

    Dispatches on snapshot shape because a scorer never sees case ids: the
    LONG_TERM_2Y case gets a non-result, the evaluated RECENT_7D case raises,
    and the not-evaluable RECENT_7D case (no present observations) scores
    normally. In deterministic case order that is exactly outcomes 1, 2, 3.
    """
    if snapshot.window_profile is WindowProfile.LONG_TERM_2Y:
        return "unsupported output"  # type: ignore[return-value]
    if snapshot.present_observations:
        raise RuntimeError("synthetic failure")
    return score_snapshot(snapshot, config_version_identifier)


def test_run_cases_reports_every_outcome_despite_execution_failures() -> None:
    """Two execution failures never hide the third case; all three come back."""
    cases = list(discover_cases(CASES_ROOT))
    assert [case.case_id for case in cases] == [
        LONG_TERM_CASE_ID,
        RECENT_CASE_ID,
        NOT_EVALUABLE_CASE_ID,
    ]

    runs = run_cases(list(reversed(cases)), _mixed_outcome_scorer)

    assert [run.case_id for run in runs] == [
        LONG_TERM_CASE_ID,
        RECENT_CASE_ID,
        NOT_EVALUABLE_CASE_ID,
    ]
    unsupported, raised, passed = runs

    assert not unsupported.passed
    assert unsupported.error_type == "GoldenCaseError"
    assert unsupported.error_message is not None
    assert "must return exactly" in unsupported.error_message
    assert unsupported.differences == ()

    assert not raised.passed
    assert raised.error_type == "RuntimeError"
    assert raised.error_message == "synthetic failure"  # the message, never a repr
    assert raised.differences == ()

    assert passed.passed
    assert passed.error_type is None
    assert passed.error_message is None
    assert passed.differences == ()


def test_run_cases_execution_failure_outcomes_are_repeatable_and_immutable() -> None:
    cases = discover_cases(CASES_ROOT)
    first = run_cases(cases, _mixed_outcome_scorer)
    second = run_cases(cases, _mixed_outcome_scorer)

    assert first == second
    failed = first[0]
    with pytest.raises(AttributeError):
        failed.error_type = "Other"  # type: ignore[misc]


class _NondeterministicRepr:
    """An argument whose repr embeds its memory address — must never surface."""

    def __repr__(self) -> str:  # pragma: no cover - never called by the runner
        return f"<NondeterministicRepr at {id(self):#x}>"


class _EvilStrError(Exception):
    """An exception whose __str__ is nondeterministic — must never be trusted."""

    def __str__(self) -> str:  # pragma: no cover - never called by the runner
        return f"nondeterministic {id(self):#x}"


def _scorer_raising(failure: BaseException):  # type: ignore[no-untyped-def]
    def scorer(snapshot: InputSnapshot, config_version_identifier: str, /) -> object:
        raise failure

    return scorer


def test_object_arguments_render_without_memory_addresses() -> None:
    case = committed_case(RECENT_CASE_ID)
    runs = run_cases([case], _scorer_raising(RuntimeError(object())))  # type: ignore[arg-type]

    run = runs[0]
    assert run.error_type == "RuntimeError"
    assert run.error_message == "non-text exception argument types: object"
    assert "0x" not in run.error_message


def test_two_object_arguments_report_only_stable_type_names() -> None:
    case = committed_case(RECENT_CASE_ID)
    runs = run_cases([case], _scorer_raising(RuntimeError(object(), object())))  # type: ignore[arg-type]

    assert runs[0].error_message == "non-text exception argument types: object, object"
    assert "0x" not in str(runs[0].error_message)


def test_nondeterministic_repr_argument_is_never_rendered() -> None:
    case = committed_case(RECENT_CASE_ID)
    runs = run_cases([case], _scorer_raising(RuntimeError(_NondeterministicRepr())))  # type: ignore[arg-type]

    assert runs[0].error_message == ("non-text exception argument types: _NondeterministicRepr")
    assert "0x" not in str(runs[0].error_message)


def test_nondeterministic_custom_str_is_never_trusted() -> None:
    case = committed_case(RECENT_CASE_ID)

    with_argument = run_cases([case], _scorer_raising(_EvilStrError("stable-argument")))  # type: ignore[arg-type]
    assert with_argument[0].error_type == "_EvilStrError"
    assert with_argument[0].error_message == "stable-argument"  # args[0], never __str__

    without_arguments = run_cases([case], _scorer_raising(_EvilStrError()))  # type: ignore[arg-type]
    assert without_arguments[0].error_message == ""
    for run in (*with_argument, *without_arguments):
        assert "nondeterministic" not in str(run.error_message)
        assert "0x" not in str(run.error_message)


def test_deterministic_error_message_argument_families() -> None:
    from tests.golden.runner import deterministic_error_message

    assert deterministic_error_message(RuntimeError()) == ""
    assert deterministic_error_message(RuntimeError("synthetic failure")) == "synthetic failure"
    assert deterministic_error_message(RuntimeError("first", "second")) == '["first", "second"]'
    assert deterministic_error_message(RuntimeError("code", 7, True, None)) == (
        '["code", 7, true, null]'
    )
    assert deterministic_error_message(RuntimeError("text", object())) == (
        "non-text exception argument types: str, object"
    )


def test_rendered_failure_runs_are_repeatable_and_equal() -> None:
    cases = discover_cases(CASES_ROOT)

    def failing(snapshot: InputSnapshot, config_version_identifier: str, /) -> object:
        raise RuntimeError(object(), object())

    first = run_cases(cases, failing)  # type: ignore[arg-type]
    second = run_cases(cases, failing)  # type: ignore[arg-type]
    assert first == second
    assert all(run.error_type == "RuntimeError" for run in first)


def test_fresh_subprocesses_render_failures_byte_identically() -> None:
    from tests.network_guard.guarded_child import run_guarded_python

    repo_root = Path(__file__).resolve().parents[3]
    program = (
        f"import sys\n"
        f"sys.path.insert(0, {str(repo_root)!r})\n"
        f"sys.path.insert(0, {str(repo_root / 'tests' / 'fixtures' / 'evaluations')!r})\n"
        "from tests.golden.runner import CASES_ROOT, discover_cases, run_cases\n"
        "def failing(snapshot, config_version_identifier, /):\n"
        "    raise RuntimeError(object(), object())\n"
        "for run in run_cases(discover_cases(CASES_ROOT), failing):\n"
        "    print(run.case_id, run.error_type, repr(run.error_message))\n"
    )
    first = run_guarded_python("-c", program, timeout=120)
    second = run_guarded_python("-c", program, timeout=120)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert first.stdout == second.stdout
    assert "0x" not in first.stdout
    assert "non-text exception argument types: object, object" in first.stdout


def test_later_cases_still_execute_after_a_nondeterministic_failure() -> None:
    cases = discover_cases(CASES_ROOT)

    def mixed(snapshot: InputSnapshot, config_version_identifier: str, /) -> object:
        if snapshot.window_profile is WindowProfile.LONG_TERM_2Y:
            raise RuntimeError(object())
        return score_snapshot(snapshot, config_version_identifier)

    runs = run_cases(cases, mixed)  # type: ignore[arg-type]

    assert [run.case_id for run in runs] == [
        LONG_TERM_CASE_ID,
        RECENT_CASE_ID,
        NOT_EVALUABLE_CASE_ID,
    ]
    assert runs[0].error_type == "RuntimeError"
    assert runs[1].passed and runs[2].passed


def test_golden_case_run_coherence_is_validated() -> None:
    case = committed_case(RECENT_CASE_ID)
    with pytest.raises(GoldenCaseError, match="must be set together"):
        GoldenCaseRun(
            case_id=case.case_id, directory=case.directory, differences=(), error_type="X"
        )
    with pytest.raises(GoldenCaseError, match="must be set together"):
        GoldenCaseRun(
            case_id=case.case_id,
            directory=case.directory,
            differences=(),
            error_message="orphan message",
        )
    mismatch = run_case(
        committed_case(NOT_EVALUABLE_CASE_ID),
        lambda snapshot, config, /: score_snapshot(committed_case(RECENT_CASE_ID).snapshot, config),
    )
    assert mismatch.differences
    with pytest.raises(GoldenCaseError, match="cannot be combined"):
        GoldenCaseRun(
            case_id=case.case_id,
            directory=case.directory,
            differences=mismatch.differences,
            error_type="RuntimeError",
            error_message="synthetic",
        )


def test_run_cases_does_not_swallow_keyboard_interrupt() -> None:
    case = committed_case(RECENT_CASE_ID)

    def interrupting_scorer(snapshot: InputSnapshot, config_version_identifier: str, /) -> object:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_cases([case], interrupting_scorer)  # type: ignore[arg-type]


def test_run_cases_does_not_swallow_system_exit() -> None:
    case = committed_case(RECENT_CASE_ID)

    def exiting_scorer(snapshot: InputSnapshot, config_version_identifier: str, /) -> object:
        raise SystemExit(3)

    with pytest.raises(SystemExit):
        run_cases([case], exiting_scorer)  # type: ignore[arg-type]


def test_one_failing_case_does_not_hide_the_others(tmp_path: Path) -> None:
    """run_cases reports every outcome; a mismatch never masks another case."""
    directory = copy_case(RECENT_CASE_ID, tmp_path)
    mutate_expected(directory, lambda parsed: parsed["payload"].__setitem__("total_score", "9.999"))
    corrupted = load_case(directory)
    healthy = committed_case(LONG_TERM_CASE_ID)

    runs = run_cases([corrupted, healthy], score_snapshot)

    outcomes = {run.case_id: run.passed for run in runs}
    assert outcomes == {LONG_TERM_CASE_ID: True, RECENT_CASE_ID: False}


# --------------------------------------------------------------------------
# Readable field-level diffs
# --------------------------------------------------------------------------


def test_corrupted_expected_scalar_produces_a_readable_field_level_diff(
    tmp_path: Path,
) -> None:
    directory = copy_case(RECENT_CASE_ID, tmp_path)
    mutate_expected(directory, lambda parsed: parsed["payload"].__setitem__("total_score", "9.999"))
    run = run_case(load_case(directory), score_snapshot)

    assert not run.passed
    assert len(run.differences) == 1
    difference = run.differences[0]
    assert difference.path == "payload.total_score"
    assert difference.kind is DifferenceKind.VALUE_MISMATCH
    assert difference.expected == '"9.999"'
    assert difference.actual == '"1.111"'
    rendered = difference.describe()
    assert "payload.total_score" in rendered
    assert 'expected "9.999"' in rendered
    assert 'actual   "1.111"' in rendered


def test_missing_field_produces_a_readable_diff(tmp_path: Path) -> None:
    """Expected carries an extra audit entry the scorer does not produce."""
    directory = copy_case(RECENT_CASE_ID, tmp_path)

    def add_audit_entry(parsed: dict) -> None:  # type: ignore[type-arg]
        entries = parsed["payload"]["audit_derivation"]
        extra = dict(entries[-1])
        extra["sequence"] = entries[-1]["sequence"] + 1
        entries.append(extra)

    mutate_expected(directory, add_audit_entry)
    run = run_case(load_case(directory), score_snapshot)

    assert not run.passed
    missing = [d for d in run.differences if d.kind is DifferenceKind.MISSING_KEY]
    assert missing
    assert missing[0].path == "payload.audit_derivation[2]"
    assert missing[0].actual is None


def test_unexpected_field_produces_a_readable_diff(tmp_path: Path) -> None:
    """Expected carries fewer audit entries than the scorer produces."""
    directory = copy_case(RECENT_CASE_ID, tmp_path)
    mutate_expected(directory, lambda parsed: parsed["payload"]["audit_derivation"].pop())
    run = run_case(load_case(directory), score_snapshot)

    assert not run.passed
    unexpected = [d for d in run.differences if d.kind is DifferenceKind.UNEXPECTED_KEY]
    assert unexpected
    assert unexpected[0].path == "payload.audit_derivation[1]"
    assert unexpected[0].expected is None


def test_result_variant_mismatch_is_explicit() -> None:
    """A case expecting EVALUATED scored by a NOT_EVALUABLE-returning scorer."""
    case = committed_case(NOT_EVALUABLE_CASE_ID)

    def evaluated_scorer(
        snapshot: InputSnapshot, config_version_identifier: str, /
    ) -> EvaluatedGradeResult | NotEvaluableGradeResult:
        recent = committed_case(RECENT_CASE_ID)
        return score_snapshot(recent.snapshot, config_version_identifier)

    run = run_case(case, evaluated_scorer)

    assert not run.passed
    assert len(run.differences) == 1
    difference = run.differences[0]
    assert difference.kind is DifferenceKind.VARIANT_MISMATCH
    assert difference.expected == "NotEvaluableGradeResult"
    assert difference.actual == "EvaluatedGradeResult"
    assert "result-variant mismatch" in difference.describe()


def test_mismatch_error_includes_case_id_and_every_difference(tmp_path: Path) -> None:
    directory = copy_case(RECENT_CASE_ID, tmp_path)

    def two_mutations(parsed: dict) -> None:  # type: ignore[type-arg]
        parsed["payload"]["total_score"] = "9.999"
        parsed["payload"]["signal_reason"] = "synthetic_other_reason"

    mutate_expected(directory, two_mutations)
    case = load_case(directory)

    with pytest.raises(GoldenMismatchError) as failure:
        assert_case_passes(case, score_snapshot)

    message = str(failure.value)
    assert RECENT_CASE_ID in message
    assert "payload.total_score" in message
    assert "payload.signal_reason" in message
    assert failure.value.case_id == RECENT_CASE_ID
    assert len(failure.value.differences) == 2


# --------------------------------------------------------------------------
# Scorer contract enforcement
# --------------------------------------------------------------------------


def test_scorer_returning_an_unsupported_type_is_rejected() -> None:
    case = committed_case(RECENT_CASE_ID)

    def bad_scorer(snapshot: InputSnapshot, config_version_identifier: str, /) -> object:
        return "not a grade result"

    with pytest.raises(GoldenCaseError, match="must return exactly an EvaluatedGradeResult"):
        run_case(case, bad_scorer)  # type: ignore[arg-type]


def test_scorer_returning_a_snapshot_is_rejected() -> None:
    case = committed_case(RECENT_CASE_ID)

    def snapshot_scorer(snapshot: InputSnapshot, config_version_identifier: str, /) -> object:
        return snapshot

    with pytest.raises(GoldenCaseError, match="returned InputSnapshot"):
        run_case(case, snapshot_scorer)  # type: ignore[arg-type]


def test_scorer_returning_the_wrong_profile_is_rejected() -> None:
    recent = committed_case(RECENT_CASE_ID)
    long_term = committed_case(LONG_TERM_CASE_ID)

    def wrong_profile_scorer(
        snapshot: InputSnapshot, config_version_identifier: str, /
    ) -> EvaluatedGradeResult | NotEvaluableGradeResult:
        return score_snapshot(long_term.snapshot, config_version_identifier)

    with pytest.raises(GoldenCaseError, match="profiles are never substituted"):
        run_case(recent, wrong_profile_scorer)


def test_scorer_receives_the_exact_snapshot_and_config_version() -> None:
    case = committed_case(RECENT_CASE_ID)
    received: list[tuple[InputSnapshot, str]] = []

    def recording_scorer(
        snapshot: InputSnapshot, config_version_identifier: str, /
    ) -> EvaluatedGradeResult | NotEvaluableGradeResult:
        received.append((snapshot, config_version_identifier))
        return score_snapshot(snapshot, config_version_identifier)

    score_case(case, recording_scorer)

    assert received == [(case.snapshot, case.config_version_identifier)]
    assert received[0][0] is case.snapshot


def test_non_callable_scorer_is_rejected() -> None:
    case = committed_case(RECENT_CASE_ID)
    with pytest.raises(GoldenCaseError, match="must be callable"):
        score_case(case, "not-callable")  # type: ignore[arg-type]


def test_repeated_runs_produce_identical_results() -> None:
    case = committed_case(RECENT_CASE_ID)
    first = run_case(case, score_snapshot)
    second = run_case(case, score_snapshot)
    assert first == second


# --------------------------------------------------------------------------
# The runner never writes
# --------------------------------------------------------------------------


def snapshot_tree(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_runner_performs_no_writes(tmp_path: Path) -> None:
    """Discovery plus execution leaves every byte of the case tree untouched."""
    root = tmp_path / "cases"
    root.mkdir()
    for case_id in (RECENT_CASE_ID, LONG_TERM_CASE_ID, NOT_EVALUABLE_CASE_ID):
        shutil.copytree(CASES_ROOT / case_id, root / case_id)

    before = snapshot_tree(root)
    cases = discover_cases(root)
    run_cases(cases, score_snapshot)
    for case in cases:
        assert_case_passes(case, score_snapshot)
    after = snapshot_tree(root)

    assert before == after


def test_diff_rendering_never_passes_through_binary_float(tmp_path: Path) -> None:
    """A Decimal-carrying string is rendered exactly, digit for digit.

    The mutated value differs from the stub's "1.111" only beyond float64
    precision: any binary-float round-trip would collapse the two to equality
    and the diff would vanish. The exact 27-digit rendering must survive.
    """
    directory = copy_case(RECENT_CASE_ID, tmp_path)
    beyond_float = "1.11100000000000000000000001"
    mutate_expected(
        directory, lambda parsed: parsed["payload"].__setitem__("total_score", beyond_float)
    )
    assert float(beyond_float) == float("1.111")  # equal once floats — the trap
    run = run_case(load_case(directory), score_snapshot)

    assert not run.passed
    difference = run.differences[0]
    assert difference.expected == f'"{beyond_float}"'
    assert difference.actual == '"1.111"'


def test_expected_result_object_equality_is_lossless(tmp_path: Path) -> None:
    """The decoded expected result equals a stub rerun, field for field."""
    case = committed_case(RECENT_CASE_ID)
    rerun = score_snapshot(case.snapshot, case.config_version_identifier)
    assert case.expected_result == rerun
    assert isinstance(case.expected_result, EvaluatedGradeResult)
    assert isinstance(case.expected_result.total_score, Decimal)
    fields = {field.name for field in dataclasses.fields(case.expected_result)}
    assert "total_score" in fields and "grade" in fields
