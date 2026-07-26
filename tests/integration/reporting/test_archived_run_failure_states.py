"""GM-041.5: the archived-run failure screen discloses nothing private.

The Evaluation screen's failure path was made path-safe first; this is the other
one. When an archived run cannot be verified or loaded, the application catches
the typed failure and renders a focused error. That renderer used to print
``failure.message``, which for a path-bearing failure is the whole private
filesystem path.

Two layers are exercised:

* the RENDERER, by patching the public verified-run loading boundary before the
  app module imports it and handing it a deliberately path-bearing failure;
* the CONVERSION, by making the loader's own reader raise a real ``OSError`` so
  the production path runs end to end — typed conversion, then safe rendering.

Both are test seams undone by ``monkeypatch``. Nothing in ``streamlit_app.py``
branches on an environment flag.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from greenmachine.common.errors import ErrorContext, GreenMachineError
from greenmachine.ingestion.errors import CapturePublicationError, SamplePolicyError
from greenmachine.reporting import DashboardLoadError, RunHandle, dashboard_loader

REPO_ROOT = Path(__file__).resolve().parents[3]
APP_PATH = REPO_ROOT / "streamlit_app.py"
EVIDENCE_ROOT = REPO_ROOT / "evidence" / "gm020_vertical_slice"
FAILING_RUN = "prospective_run"
HEALTHY_RUN = "run_gm040_ohtani"

# The path the Product Owner named, plus a Windows-style one ASSEMBLED from
# parts: the release packaging guard scans shipped files for machine-local
# absolute paths, and a literal would trip it. Building it from parts keeps the
# test honest without weakening that guard.
_SEPARATOR = chr(92)  # backslash
_USER_ROOT = "C:" + _SEPARATOR + "Users"
POSIX_PATH = "/very/private/secret/evidence/manifest.json"
WINDOWS_PATH = _SEPARATOR.join((_USER_ROOT, "ExampleUser", "private", "evidence", "manifest.json"))

SECRET_SEGMENTS = (
    "ExampleUser",
    "secret",
    "/very/private",
    _USER_ROOT,
    "Errno",
    "Permission denied",
    "No such file",
    "Traceback",
    "__cause__",
)

SAFE_SENTENCE = "The archived run failed its integrity or loading checks and cannot be displayed."


@pytest.fixture(autouse=True)
def _isolated_resource_cache() -> Iterator[None]:
    """The app caches one verification per run, and that cache outlives an AppTest.

    Without this, a run already verified by an earlier test in the same process
    is served from ``st.cache_resource`` and the injected failure never fires —
    the suite would pass in isolation and quietly stop testing anything in a full
    run. Cleared on the way in so each case really loads, and on the way out so
    nothing built under a patched loader is left behind for the next test.
    """
    st.cache_resource.clear()
    yield
    st.cache_resource.clear()


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


def _assert_discloses_nothing_private(app: AppTest) -> None:
    text = _rendered_text(app)
    for segment in SECRET_SEGMENTS:
        assert segment not in text, segment
    assert POSIX_PATH not in text
    assert WINDOWS_PATH not in text
    # No absolute path of any shape, including this machine's own — which is
    # where a real username would come from.
    assert str(REPO_ROOT) not in text
    assert str(EVIDENCE_ROOT) not in text
    assert Path.home().as_posix() not in text
    assert app.exception == []


def _assert_shows_no_run_content(app: AppTest) -> None:
    """Fail closed: no partial run leaks past the error."""
    text = _rendered_text(app)
    assert "SourceCaptureId" not in text
    assert "Integrity:" not in text
    assert "Snapshot as_of" not in text
    assert app.get("metric") == []


@pytest.fixture
def patched_loading(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Callable[[GreenMachineError], AppTest]]:
    """Make ONE run fail to load, leaving every other approved run healthy.

    The app does ``from greenmachine.reporting import ... load_verified_run`` at
    module scope, and AppTest imports the module fresh on each run, so patching
    the attribute on the already-imported package is picked up.
    """
    import greenmachine.reporting as reporting

    real = reporting.load_verified_run

    def install(failure: GreenMachineError) -> AppTest:
        def replacement(handle: RunHandle) -> object:
            if handle.name == FAILING_RUN:
                raise failure
            return real(handle)

        monkeypatch.setattr(reporting, "load_verified_run", replacement)
        sys.modules.pop("streamlit_app", None)
        app = AppTest.from_file(str(APP_PATH), default_timeout=600)
        app.run()
        app.selectbox(key="run_select").select(FAILING_RUN).run()
        app.button(key="nav_overview").click().run()
        return app

    yield install


def _path_bearing(path: str) -> DashboardLoadError:
    """What the loader would raise if it formatted a path into its message."""
    return DashboardLoadError(
        f"archived run could not be read: [Errno 13] Permission denied: '{path}'",
        ErrorContext(subject=FAILING_RUN, file_path=path),
    )


# --------------------------------------------------------------------------
# The screen itself
# --------------------------------------------------------------------------


@pytest.mark.parametrize("path", (POSIX_PATH, WINDOWS_PATH), ids=("posix", "windows"))
def test_the_failure_screen_says_what_happened_without_saying_where(
    path: str, patched_loading: Callable[[GreenMachineError], AppTest]
) -> None:
    app = patched_loading(_path_bearing(path))

    text = _rendered_text(app)
    assert "Archived run could not be verified" in text
    assert "DashboardLoadError" in text
    assert FAILING_RUN in text
    assert SAFE_SENTENCE in text
    assert "Select another approved run" in text
    _assert_discloses_nothing_private(app)


@pytest.mark.parametrize("path", (POSIX_PATH, WINDOWS_PATH), ids=("posix", "windows"))
def test_the_failure_screen_shows_no_partial_run(
    path: str, patched_loading: Callable[[GreenMachineError], AppTest]
) -> None:
    app = patched_loading(_path_bearing(path))

    _assert_shows_no_run_content(app)


def test_the_context_file_path_is_never_rendered(
    patched_loading: Callable[[GreenMachineError], AppTest],
) -> None:
    """Structured context is for engineers; it is not a rendering source."""
    failure = DashboardLoadError(
        "archived run could not be read",  # message alone is harmless
        ErrorContext(subject=FAILING_RUN, file_path=POSIX_PATH),
    )
    app = patched_loading(failure)

    text = _rendered_text(app)
    assert SAFE_SENTENCE in text
    assert POSIX_PATH not in text
    _assert_discloses_nothing_private(app)


@pytest.mark.parametrize(
    "failure",
    (
        CapturePublicationError(
            f"run artifact missing: '{POSIX_PATH}'", ErrorContext(file_path=POSIX_PATH)
        ),
        SamplePolicyError(
            f"archived sample policy rejected: '{POSIX_PATH}'", ErrorContext(file_path=POSIX_PATH)
        ),
    ),
    ids=("CapturePublicationError", "SamplePolicyError"),
)
def test_other_typed_categories_are_named_and_still_safe(
    failure: GreenMachineError, patched_loading: Callable[[GreenMachineError], AppTest]
) -> None:
    app = patched_loading(failure)

    text = _rendered_text(app)
    assert "Archived run could not be verified" in text
    assert failure.error_type in text
    assert "cannot be displayed" in text
    _assert_discloses_nothing_private(app)
    _assert_shows_no_run_content(app)


def test_an_unrecognised_category_falls_back_to_the_generic_safe_sentence(
    patched_loading: Callable[[GreenMachineError], AppTest],
) -> None:
    """Safety by construction: a brand-new error class needs no table entry."""

    class AnUnlistedError(GreenMachineError):
        """Stands in for an error class added after this adapter was written."""

    failure = AnUnlistedError(
        f"something new went wrong reading '{POSIX_PATH}'",
        ErrorContext(file_path=POSIX_PATH),
    )
    app = patched_loading(failure)

    text = _rendered_text(app)
    assert "AnUnlistedError" in text
    assert SAFE_SENTENCE in text
    _assert_discloses_nothing_private(app)


def test_another_approved_run_remains_usable(
    patched_loading: Callable[[GreenMachineError], AppTest],
) -> None:
    """One unreadable run must not take the console down with it."""
    app = patched_loading(_path_bearing(POSIX_PATH))
    assert "Archived run could not be verified" in _rendered_text(app)

    app.selectbox(key="run_select").select(HEALTHY_RUN).run()

    text = _rendered_text(app)
    assert "Archived run could not be verified" not in text
    assert "SourceCaptureId" in text
    assert app.exception == []


# --------------------------------------------------------------------------
# The conversion, end to end through the real loader
# --------------------------------------------------------------------------


@pytest.fixture
def unreadable_bundle(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[OSError], AppTest]]:
    """Make the loader's own reader raise a real ``OSError``.

    Nothing about the application or the loader is stubbed: the production
    conversion runs, and the production renderer renders whatever it produced.
    Injection rather than a real permission change keeps this cross-platform.
    """
    real_factory = dashboard_loader.bundle_reader

    def install(original: OSError) -> AppTest:
        def factory(directory: Path) -> Callable[[str], bytes]:
            real = real_factory(directory)

            def read(relative_path: str) -> bytes:
                if directory.name == FAILING_RUN:
                    raise original
                return real(relative_path)

            return read

        monkeypatch.setattr(dashboard_loader, "bundle_reader", factory)
        sys.modules.pop("streamlit_app", None)
        app = AppTest.from_file(str(APP_PATH), default_timeout=600)
        app.run()
        app.selectbox(key="run_select").select(FAILING_RUN).run()
        app.button(key="nav_overview").click().run()
        return app

    yield install


@pytest.mark.parametrize(
    ("label", "original"),
    (
        ("unreadable", PermissionError(13, "Permission denied", POSIX_PATH)),
        ("vanished", FileNotFoundError(2, "No such file or directory", POSIX_PATH)),
        ("unreadable, windows path", PermissionError(13, "Permission denied", WINDOWS_PATH)),
    ),
    ids=lambda value: value if isinstance(value, str) else "",
)
def test_a_raw_oserror_never_reaches_the_screen(
    label: str, original: OSError, unreadable_bundle: Callable[[OSError], AppTest]
) -> None:
    """The whole point: no traceback, no path, a focused error instead."""
    app = unreadable_bundle(original)

    text = _rendered_text(app)
    assert "Archived run could not be verified" in text
    assert "DashboardLoadError" in text
    assert FAILING_RUN in text
    assert SAFE_SENTENCE in text
    _assert_discloses_nothing_private(app)
    _assert_shows_no_run_content(app)


def test_the_console_still_works_after_an_unreadable_run(
    unreadable_bundle: Callable[[OSError], AppTest],
) -> None:
    app = unreadable_bundle(PermissionError(13, "Permission denied", POSIX_PATH))

    app.selectbox(key="run_select").select(HEALTHY_RUN).run()

    text = _rendered_text(app)
    assert "Archived run could not be verified" not in text
    assert "SourceCaptureId" in text
    assert app.exception == []
