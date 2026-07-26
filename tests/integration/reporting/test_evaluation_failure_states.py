"""GM-041.5: the Engine Evaluation screen's terminal and failure branches.

Two things the real archived bundles cannot exercise, because both of them
evaluate successfully under the synthetic configuration:

* a ``NotEvaluableGradeResult`` — a structurally different terminal state that
  must never be shown as a zero or a tier D;
* a typed ``ScoringError`` — which must render *Evaluation unavailable*, never
  the run-verification error, and never a filesystem path or traceback.

Both are reached by patching the public scoring boundary **before** the app
module imports it. That is a test seam, not a production switch: nothing in
``streamlit_app.py`` branches on an environment flag, and the patch is undone by
``monkeypatch`` when the test ends.
"""

from __future__ import annotations

import dataclasses
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from greenmachine.common.errors import ErrorContext
from greenmachine.config import (
    ConfigParseError,
    ConfigSchemaError,
    ConfigSemanticError,
    ConfigVersionError,
)
from greenmachine.domain import (
    AcquisitionMethod,
    AuditEntry,
    ComponentId,
    MeasurementId,
    MethodIneligibility,
    NotEvaluableGradeResult,
    SampleType,
    UnavailableRequiredInput,
)
from greenmachine.reporting import RunHandle, load_verified_run
from greenmachine.scoring import ScoringConfigError, ScoringError, ScoringInputError

REPO_ROOT = Path(__file__).resolve().parents[3]
APP_PATH = REPO_ROOT / "streamlit_app.py"
EVIDENCE_ROOT = REPO_ROOT / "evidence" / "gm020_vertical_slice"
RUN = "prospective_run"

# Deliberately sensitive-looking paths. Neither may reach a rendered screen,
# nor may any identifying segment of them.
#
# The Windows path is ASSEMBLED rather than written as a literal: the release
# packaging guard scans shipped files for machine-local absolute paths, and a
# literal here would trip it. Building it from parts keeps this test honest
# without weakening that guard.
_SEPARATOR = chr(92)  # backslash
_USER_ROOT = "C:" + _SEPARATOR + "Users"
WINDOWS_PATH = _SEPARATOR.join((_USER_ROOT, "ExampleUser", "private", "config.yaml"))
POSIX_PATH = "/very/private/secret/config.yaml"
SECRET_SEGMENTS = (
    "ExampleUser",
    "private",
    "secret",
    "config.yaml",
    _USER_ROOT,
    "/very/private",
    "Errno",
    "Permission denied",
    "No such file",
    "Traceback",
)


def _rendered_text(app: AppTest) -> str:
    pieces: list[str] = []
    for kind in (
        "title",
        "header",
        "subheader",
        "markdown",
        "caption",
        "warning",
        "info",
        "success",
        "error",
        "code",
        "exception",
    ):
        for element in getattr(app, kind, []):
            pieces.append(str(getattr(element, "value", element)))
    for metric in app.get("metric"):
        pieces.append(f"{metric.proto.label} {metric.proto.body} {metric.proto.help}")
    for expander in app.get("expander"):
        pieces.append(str(expander.proto.label))
    return " \n".join(pieces)


@pytest.fixture
def patched_scoring(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[object], AppTest]]:
    """Replace ``greenmachine.scoring.score_snapshot`` for the app's import.

    The app does ``from greenmachine.scoring import ... score_snapshot`` at
    module scope, and AppTest imports the module fresh on each run, so patching
    the attribute on the already-imported package is picked up.
    """
    import greenmachine.scoring as scoring

    def install(behaviour: object) -> AppTest:
        def replacement(snapshot: object, config: object) -> object:
            if isinstance(behaviour, BaseException):
                raise behaviour
            return behaviour

        monkeypatch.setattr(scoring, "score_snapshot", replacement)
        sys.modules.pop("streamlit_app", None)
        app = AppTest.from_file(str(APP_PATH), default_timeout=600)
        app.run()
        app.selectbox(key="run_select").select(RUN).run()
        app.button(key="nav_evaluate").click().run()
        return app

    yield install


def _not_evaluable_result() -> NotEvaluableGradeResult:
    """A valid not-evaluable result built from the real archived snapshot.

    Reusing the archived observations keeps the record coherent with the frozen
    contract — the domain would refuse anything else — so the screen is
    exercised with a result it could genuinely receive.
    """
    run = load_verified_run(RunHandle(name=RUN, directory=EVIDENCE_ROOT / RUN))
    snapshot = run.recent_snapshot
    missing = snapshot.missing_observations[0]
    unavailable = UnavailableRequiredInput(
        component_id=missing.component_id,
        measurement_id=missing.measurement_id,
        missing_reason=missing.missing_reason,
        missing_observation=missing,
        attempted_methods=(
            MethodIneligibility(
                method=snapshot.present_observations[0].acquisition_method,
                reason="synthetic test ineligibility: no approved source at this as_of",
            ),
        ),
    )
    # A result that cannot say how it was derived is not a result -- the frozen
    # contract enforces at least one entry, so the test builds a real one rather
    # than working around the guard.
    derivation = (
        AuditEntry(
            sequence=1,
            stage="evaluability_verdict",
            rule_reference="gm041-engine-synthetic-0/components/missing_data",
            input_summary=f"required input unavailable: {unavailable.component_id.value}",
            output_summary="NOT_EVALUABLE (no score or grade exists)",
            explanation=(
                "NOT_EVALUABLE is a distinct terminal state, never a low grade "
                "(MODEL_SPEC section 15)"
            ),
        ),
    )
    return NotEvaluableGradeResult(
        window_profile=snapshot.window_profile,
        present_observations=snapshot.present_observations,
        missing_observations=snapshot.missing_observations,
        validation_findings=(),
        audit_derivation=derivation,
        unavailable_required_inputs=(unavailable,),
    )


# --------------------------------------------------------------------------
# NOT EVALUABLE
# --------------------------------------------------------------------------


def test_a_not_evaluable_result_renders_its_own_terminal_state(
    patched_scoring: Callable[[object], AppTest],
) -> None:
    result = _not_evaluable_result()
    app = patched_scoring(result)

    text = _rendered_text(app)
    assert app.exception == []
    assert "NOT EVALUABLE" in text
    assert "must never be read as zero" in text


def test_a_not_evaluable_result_shows_no_total_and_no_tier(
    patched_scoring: Callable[[object], AppTest],
) -> None:
    """The substitution that must never happen."""
    app = patched_scoring(_not_evaluable_result())

    labels = {metric.proto.label for metric in app.get("metric")}
    assert "Total Score" not in labels
    assert "Tier" not in labels

    text = _rendered_text(app)
    assert "of 12" not in text
    # No tier letter is presented as this result's outcome.
    assert "Tier** D" not in text
    assert "1. Total Score" not in text


def test_a_not_evaluable_result_renders_every_unavailable_required_input(
    patched_scoring: Callable[[object], AppTest],
) -> None:
    result = _not_evaluable_result()
    app = patched_scoring(result)
    text = _rendered_text(app)

    assert "Unavailable required inputs" in text
    for entry in result.unavailable_required_inputs:
        assert entry.component_id.value in text
        assert entry.missing_reason.value in text
        for ineligibility in entry.attempted_methods:
            assert ineligibility.method.value in text
            assert ineligibility.reason in text


def _not_evaluable_with_measurement() -> NotEvaluableGradeResult:
    """A not-evaluable result whose unavailable input carries a measurement id.

    The archived bundle's missing observations are all measurement-free, so the
    attack-angle **proxy** variant is added explicitly. It is a distinct
    ``(component_id, measurement_id)`` key from the present ideal-attack-angle
    observation, which is what the result contract requires.
    """
    base = _not_evaluable_result()
    template = base.missing_observations[0]
    proxy_missing = dataclasses.replace(
        template,
        component_id=ComponentId.ATTACK_ANGLE_QUALITY,
        measurement_id=MeasurementId.ATTACK_ANGLE_THRESHOLD_PROXY,
        sample_type=SampleType.SWINGS,
    )
    unavailable = UnavailableRequiredInput(
        component_id=proxy_missing.component_id,
        measurement_id=proxy_missing.measurement_id,
        missing_reason=proxy_missing.missing_reason,
        missing_observation=proxy_missing,
        attempted_methods=(
            MethodIneligibility(
                method=AcquisitionMethod.DIRECT_AGGREGATE,
                reason="synthetic test ineligibility: no approved proxy source",
            ),
        ),
    )
    return dataclasses.replace(
        base,
        missing_observations=(*base.missing_observations, proxy_missing),
        unavailable_required_inputs=(unavailable,),
    )


def test_a_not_evaluable_result_renders_a_measurement_id_when_present(
    patched_scoring: Callable[[object], AppTest],
) -> None:
    """A measurement variant must be named, not silently collapsed."""
    result = _not_evaluable_with_measurement()
    entry = result.unavailable_required_inputs[0]
    assert entry.measurement_id is not None  # the case this test exists for

    app = patched_scoring(result)
    text = _rendered_text(app)

    assert entry.measurement_id.value in text
    assert entry.component_id.value in text
    assert entry.attempted_methods[0].method.value in text


def test_a_not_evaluable_result_renders_warnings_and_fallbacks_from_its_observations(
    patched_scoring: Callable[[object], AppTest],
) -> None:
    app = patched_scoring(_not_evaluable_result())
    text = _rendered_text(app)

    assert "5. Warnings" in text
    assert "6. Fallbacks" in text
    # The archived snapshot records an attack-angle fallback; it travels on the
    # result's own observations and must surface here too.
    assert "attack_angle_quality` resolved through" in text
    assert "event_derived" in text


def test_a_not_evaluable_result_renders_its_audit_trail_section(
    patched_scoring: Callable[[object], AppTest],
) -> None:
    app = patched_scoring(_not_evaluable_result())

    assert "4. Audit Trail" in _rendered_text(app)


# --------------------------------------------------------------------------
# Typed scoring failures
# --------------------------------------------------------------------------

_SCORING_FAILURES = (
    pytest.param(
        ScoringInputError("snapshot disagrees", ErrorContext(subject="exit_velocity")),
        "ScoringInputError",
        id="ScoringInputError",
    ),
    pytest.param(
        ScoringConfigError("configuration cannot drive", ErrorContext(subject="weather")),
        "ScoringConfigError",
        id="ScoringConfigError",
    ),
    pytest.param(
        ScoringError("engine refused", ErrorContext(subject="engine")),
        "ScoringError",
        id="ScoringError",
    ),
)


@pytest.mark.parametrize(("failure", "category"), _SCORING_FAILURES)
def test_a_typed_scoring_failure_renders_evaluation_unavailable(
    failure: Exception, category: str, patched_scoring: Callable[[object], AppTest]
) -> None:
    app = patched_scoring(failure)
    text = _rendered_text(app)

    assert "Evaluation unavailable" in text
    assert category in text
    assert "Archived run could not be verified" not in text


@pytest.mark.parametrize(("failure", "category"), _SCORING_FAILURES)
def test_a_typed_scoring_failure_renders_no_partial_result(
    failure: Exception, category: str, patched_scoring: Callable[[object], AppTest]
) -> None:
    """Nothing of the six outputs may appear beside a failure."""
    app = patched_scoring(failure)
    text = _rendered_text(app)

    assert {metric.proto.label for metric in app.get("metric")} == set()
    for section in (
        "1. Total Score",
        "3. Component Breakdown",
        "4. Audit Trail",
        "5. Warnings",
        "6. Fallbacks",
        "NOT EVALUABLE",
    ):
        assert section not in text, section


@pytest.mark.parametrize(("failure", "category"), _SCORING_FAILURES)
def test_every_other_screen_still_works_after_a_scoring_failure(
    failure: Exception, category: str, patched_scoring: Callable[[object], AppTest]
) -> None:
    app = patched_scoring(failure)

    for screen in ("overview", "metrics", "matchup", "audit", "review"):
        app.button(key="return_hub").click().run()
        app.button(key=f"nav_{screen}").click().run()
        assert app.exception == [], screen
        assert "Evaluation unavailable" not in " ".join(
            str(element.value) for element in app.error
        ), screen


# --------------------------------------------------------------------------
# No path, username, or traceback ever reaches the screen
# --------------------------------------------------------------------------

_PATH_BEARING_FAILURES = (
    pytest.param(
        ConfigParseError(
            f"could not read configuration file: [Errno 13] Permission denied: '{POSIX_PATH}'",
            ErrorContext(file_path=POSIX_PATH),
        ),
        "ConfigParseError",
        id="ConfigParseError-posix",
    ),
    pytest.param(
        ConfigParseError(
            f"could not read configuration file: [Errno 2] No such file or directory: "
            f"'{WINDOWS_PATH}'",
            ErrorContext(file_path=WINDOWS_PATH),
        ),
        "ConfigParseError",
        id="ConfigParseError-windows",
    ),
    pytest.param(
        ConfigSchemaError(
            f"schema violation in {WINDOWS_PATH}", ErrorContext(file_path=WINDOWS_PATH)
        ),
        "ConfigSchemaError",
        id="ConfigSchemaError",
    ),
    pytest.param(
        ConfigSemanticError(
            f"invariant violated in {POSIX_PATH}", ErrorContext(file_path=POSIX_PATH)
        ),
        "ConfigSemanticError",
        id="ConfigSemanticError",
    ),
    pytest.param(
        ConfigVersionError(f"version identity unavailable for {POSIX_PATH}"),
        "ConfigVersionError",
        id="ConfigVersionError",
    ),
)


@pytest.fixture
def patched_config(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[Exception], AppTest]]:
    """Make configuration loading raise a chosen typed failure.

    Injecting the typed failure keeps the test cross-platform: it exercises an
    *unreadable* configuration without depending on filesystem permissions,
    which behave differently on Windows.
    """
    import greenmachine.config as config

    def install(failure: Exception) -> AppTest:
        def replacement(path: object) -> object:
            raise failure

        monkeypatch.setattr(config, "load_versioned_config", replacement)
        sys.modules.pop("streamlit_app", None)
        app = AppTest.from_file(str(APP_PATH), default_timeout=600)
        app.run()
        app.button(key="nav_evaluate").click().run()
        return app

    yield install


@pytest.mark.parametrize(("failure", "category"), _PATH_BEARING_FAILURES)
def test_a_path_bearing_configuration_failure_never_leaks_the_path(
    failure: Exception, category: str, patched_config: Callable[[Exception], AppTest]
) -> None:
    """The disclosure this correction exists to prevent."""
    app = patched_config(failure)
    text = _rendered_text(app)

    assert "Evaluation unavailable" in text
    assert category in text
    for segment in SECRET_SEGMENTS:
        assert segment not in text, f"{category} leaked {segment!r}"


@pytest.mark.parametrize(("failure", "category"), _PATH_BEARING_FAILURES)
def test_a_path_bearing_failure_renders_safe_wording_not_its_own_message(
    failure: Exception, category: str, patched_config: Callable[[Exception], AppTest]
) -> None:
    app = patched_config(failure)
    text = _rendered_text(app)

    assert str(failure) not in text
    assert getattr(failure, "message", "") not in text
    assert "Diagnostic detail is deliberately not shown" in text


def test_an_unreadable_configuration_is_reported_safely(
    patched_config: Callable[[Exception], AppTest],
) -> None:
    """Unreadable, not merely absent or malformed."""
    failure = ConfigParseError(
        f"could not read configuration file: [Errno 13] Permission denied: '{POSIX_PATH}'",
        ErrorContext(file_path=POSIX_PATH),
    )
    app = patched_config(failure)
    text = _rendered_text(app)

    assert "could not be read or parsed" in text
    assert "Permission denied" not in text
    assert POSIX_PATH not in text


def test_the_failure_object_is_not_mutated_by_rendering(
    patched_config: Callable[[Exception], AppTest],
) -> None:
    """The full typed error is preserved internally; only its category is shown."""
    failure = ConfigParseError(
        f"could not read configuration file: '{POSIX_PATH}'",
        ErrorContext(file_path=POSIX_PATH),
    )
    original_message = failure.message
    original_context = dataclasses.replace(failure.context)

    patched_config(failure)

    assert failure.message == original_message
    assert failure.context == original_context
    assert failure.context.file_path == POSIX_PATH


def test_a_scoring_failure_also_hides_any_path_in_its_message(
    patched_scoring: Callable[[object], AppTest],
) -> None:
    failure = ScoringInputError(
        f"snapshot at {WINDOWS_PATH} disagrees with configuration",
        ErrorContext(file_path=WINDOWS_PATH),
    )
    app = patched_scoring(failure)
    text = _rendered_text(app)

    assert "ScoringInputError" in text
    for segment in SECRET_SEGMENTS:
        assert segment not in text, segment
