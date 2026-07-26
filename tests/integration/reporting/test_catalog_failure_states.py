"""GM-041.5: the archived-run catalog screen discloses nothing private.

The last failure surface, and the earliest one. Discovery runs **before** a run
has been selected, so the run-level boundary cannot protect it: an ``OSError``
from resolving or enumerating the evidence root travelled out of
``discover_runs`` untyped, past ``except GreenMachineError``, and onto the
screen as a traceback naming the configured root.

Two layers are exercised:

* the RENDERER, by patching the public discovery boundary before the app module
  imports it and handing it a deliberately path-bearing failure;
* the CONVERSION, by making the real ``discover_runs`` implementation meet a
  genuine ``PermissionError`` so the production path runs end to end.

Both are test seams undone by ``monkeypatch``, plus an anti-vacuity control
proving the same seam still permits normal discovery.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from greenmachine.common.errors import ErrorContext, GreenMachineError
from greenmachine.reporting import DashboardLoadError, dashboard_loader

REPO_ROOT = Path(__file__).resolve().parents[3]
APP_PATH = REPO_ROOT / "streamlit_app.py"
EVIDENCE_ROOT = REPO_ROOT / "evidence" / "gm020_vertical_slice"

# The evidence root a real deployment would name, plus a Windows-style one
# ASSEMBLED from parts: the release packaging guard scans shipped files for
# machine-local absolute paths, and a literal would trip it. Building it from
# parts keeps the test honest without weakening that guard.
_SEPARATOR = chr(92)  # backslash
_USER_ROOT = "C:" + _SEPARATOR + "Users"
POSIX_ROOT = "/very/private/secret/evidence"
WINDOWS_ROOT = _SEPARATOR.join((_USER_ROOT, "ExampleUser", "private", "evidence"))

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

HEADING = "Archived-run catalog unavailable"
SAFE_SENTENCE = "The approved archived-run catalog could not be read safely."


@pytest.fixture(autouse=True)
def _isolated_resource_cache() -> Iterator[None]:
    """The app's per-run verification cache outlives an AppTest.

    Cleared on the way in so each case really runs, and on the way out so
    nothing built under a patched seam is left for the next test.
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
    assert POSIX_ROOT not in text
    assert WINDOWS_ROOT not in text
    # No absolute path of any shape, including this machine's own -- which is
    # where a real username would come from.
    assert str(REPO_ROOT) not in text
    assert str(EVIDENCE_ROOT) not in text
    assert Path.home().as_posix() not in text
    assert app.exception == []


def _assert_no_selector_and_no_dashboard(app: AppTest) -> None:
    """Nothing may be offered or shown: there is no catalog to choose from."""
    assert app.get("selectbox") == []
    assert app.get("metric") == []
    text = _rendered_text(app)
    assert "SourceCaptureId" not in text
    assert "Integrity:" not in text
    # It must not blame a run, because no run was ever selected.
    assert "Archived run could not be verified" not in text
    assert "prospective_run" not in text
    assert "run_gm040_ohtani" not in text


def _path_bearing(root: str) -> DashboardLoadError:
    """What discovery would raise if it formatted the root into its message."""
    return DashboardLoadError(
        f"catalog could not be read: [Errno 13] Permission denied: '{root}'",
        ErrorContext(subject="archived-run-catalog", file_path=root),
    )


@pytest.fixture
def patched_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Callable[[GreenMachineError | None], AppTest]]:
    """Replace ``greenmachine.reporting.discover_runs`` for the app's import.

    Passing ``None`` injects no failure at all — the control that proves this
    seam still permits normal discovery.
    """
    import greenmachine.reporting as reporting

    real = reporting.discover_runs

    def install(failure: GreenMachineError | None) -> AppTest:
        def replacement(evidence_root: Path) -> object:
            if failure is not None:
                raise failure
            return real(evidence_root)

        monkeypatch.setattr(reporting, "discover_runs", replacement)
        sys.modules.pop("streamlit_app", None)
        app = AppTest.from_file(str(APP_PATH), default_timeout=600)
        app.run()
        return app

    yield install


@pytest.fixture
def unreadable_catalog(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[Callable[[OSError], AppTest]]:
    """Make the REAL enumeration meet a genuine ``OSError`` at its real call site.

    Nothing in ``greenmachine.reporting`` is replaced: a real evidence root is
    configured through the deployment override, and ``Path.iterdir`` raises for
    that one directory. So ``_discover_runs`` executes its own
    ``root.resolve()`` and ``root.is_dir()`` and then fails on its own
    ``root.iterdir()`` — the production conversion and the production renderer
    both run. Injection rather than a real permission change keeps this
    cross-platform, and the patch is scoped to a single temporary directory.
    """
    root = tmp_path / "evidence_root"
    root.mkdir()
    resolved_root = root.resolve()
    real_iterdir = Path.iterdir

    def install(original: OSError) -> AppTest:
        def iterdir(self: Path) -> Iterator[Path]:
            if self == resolved_root:
                raise original
            return real_iterdir(self)

        monkeypatch.setattr(Path, "iterdir", iterdir)
        monkeypatch.setenv("GREENMACHINE_EVIDENCE_ROOT", str(root))
        sys.modules.pop("streamlit_app", None)
        app = AppTest.from_file(str(APP_PATH), default_timeout=600)
        app.run()
        return app

    yield install


# --------------------------------------------------------------------------
# The renderer
# --------------------------------------------------------------------------


@pytest.mark.parametrize("root", (POSIX_ROOT, WINDOWS_ROOT), ids=("posix", "windows"))
def test_the_catalog_screen_says_what_happened_without_saying_where(
    root: str, patched_discovery: Callable[[GreenMachineError | None], AppTest]
) -> None:
    app = patched_discovery(_path_bearing(root))

    text = _rendered_text(app)
    assert HEADING in text
    assert "DashboardLoadError" in text
    assert SAFE_SENTENCE in text
    _assert_discloses_nothing_private(app)


@pytest.mark.parametrize("root", (POSIX_ROOT, WINDOWS_ROOT), ids=("posix", "windows"))
def test_the_catalog_screen_offers_no_selector_and_no_partial_dashboard(
    root: str, patched_discovery: Callable[[GreenMachineError | None], AppTest]
) -> None:
    app = patched_discovery(_path_bearing(root))

    _assert_no_selector_and_no_dashboard(app)


def test_the_catalog_screen_does_not_blame_a_selected_run(
    patched_discovery: Callable[[GreenMachineError | None], AppTest],
) -> None:
    """Selection has not happened yet, so claiming a run failed would be false."""
    app = patched_discovery(_path_bearing(POSIX_ROOT))

    text = _rendered_text(app)
    assert "No run was selected" in text
    assert "Select another approved run" not in text


def test_the_context_file_path_is_never_rendered(
    patched_discovery: Callable[[GreenMachineError | None], AppTest],
) -> None:
    """Structured context is for engineers; it is not a rendering source."""
    failure = DashboardLoadError(
        "catalog could not be read",  # message alone is harmless
        ErrorContext(subject="archived-run-catalog", file_path=POSIX_ROOT),
    )
    app = patched_discovery(failure)

    assert SAFE_SENTENCE in _rendered_text(app)
    _assert_discloses_nothing_private(app)


def test_an_unrecognised_category_falls_back_to_the_generic_safe_sentence(
    patched_discovery: Callable[[GreenMachineError | None], AppTest],
) -> None:
    """Safety by construction: a brand-new error class needs no table entry."""

    class AnUnlistedError(GreenMachineError):
        """Stands in for an error class added after this adapter was written."""

    failure = AnUnlistedError(
        f"something new went wrong reading '{POSIX_ROOT}'",
        ErrorContext(file_path=POSIX_ROOT),
    )
    app = patched_discovery(failure)

    text = _rendered_text(app)
    assert "AnUnlistedError" in text
    assert SAFE_SENTENCE in text
    _assert_discloses_nothing_private(app)


def test_the_patched_seam_still_permits_normal_discovery(
    patched_discovery: Callable[[GreenMachineError | None], AppTest],
) -> None:
    """Anti-vacuity: with no failure injected, the console comes up normally.

    Without this, every assertion above could be passing because the seam breaks
    the app rather than because the guard works.
    """
    app = patched_discovery(None)

    text = _rendered_text(app)
    assert HEADING not in text
    assert app.get("selectbox") != []
    assert app.exception == []


# --------------------------------------------------------------------------
# The conversion, end to end through the real boundary
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "original"),
    (
        ("enumeration refused", PermissionError(13, "Permission denied", POSIX_ROOT)),
        ("root vanished", FileNotFoundError(2, "No such file or directory", POSIX_ROOT)),
        (
            "enumeration refused, windows root",
            PermissionError(13, "Permission denied", WINDOWS_ROOT),
        ),
    ),
    ids=lambda value: value if isinstance(value, str) else "",
)
def test_a_raw_discovery_oserror_never_reaches_the_screen(
    label: str, original: OSError, unreadable_catalog: Callable[[OSError], AppTest]
) -> None:
    """The whole point: no traceback, no root path, a focused catalog state."""
    app = unreadable_catalog(original)

    text = _rendered_text(app)
    assert HEADING in text
    assert "DashboardLoadError" in text
    assert SAFE_SENTENCE in text
    _assert_discloses_nothing_private(app)
    _assert_no_selector_and_no_dashboard(app)


def test_the_same_evidence_root_without_an_injected_failure_is_merely_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Anti-vacuity for the end-to-end seam.

    The temporary evidence root above is empty, and an empty root is *not* a
    failure. Pointing the app at it with nothing injected must produce the
    ordinary no-runs message — proving the catalog error in the tests above
    comes from the injected ``OSError`` and not from the override itself.
    """
    root = tmp_path / "evidence_root"
    root.mkdir()
    monkeypatch.setenv("GREENMACHINE_EVIDENCE_ROOT", str(root))
    sys.modules.pop("streamlit_app", None)
    app = AppTest.from_file(str(APP_PATH), default_timeout=600)
    app.run()

    text = _rendered_text(app)
    assert HEADING not in text
    assert "No approved archived run was found" in text
    assert app.exception == []


def test_the_typed_boundary_is_the_public_discovery_function() -> None:
    """The conversion belongs to ``discover_runs``, not to a caller.

    Any caller of ``greenmachine.reporting.discover_runs`` — not only this app —
    is protected, which is the reason the guard lives in the loader rather than
    in ``main()``.
    """
    assert dashboard_loader.discover_runs is not dashboard_loader._discover_runs
    with pytest.raises(DashboardLoadError):
        dashboard_loader.discover_runs(_RaisingRoot())  # type: ignore[arg-type]


class _RaisingRoot:
    """The smallest thing that fails the way an unreadable root fails."""

    def resolve(self) -> _RaisingRoot:
        return self

    def is_dir(self) -> bool:
        return True

    def iterdir(self) -> Iterator[Path]:
        raise PermissionError(13, "Permission denied", POSIX_ROOT)
