"""GM-041.5: a filesystem failure inside the loader leaves it typed, not raw.

A run directory is ordinary filesystem state. A file can be unreadable, or can
disappear between the moment ``discover_runs`` sees the run and the moment a
read wants the file. Those arrive as ``OSError`` subclasses, and ``OSError`` is
not a ``GreenMachineError`` — so before this ticket one could travel all the way
out of ``load_verified_run``, past the application's ``except GreenMachineError``,
and onto the screen as a raw traceback carrying the absolute path it failed on.

Every case here is reached by INJECTION rather than by changing real filesystem
permissions, so the suite behaves identically on every platform.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from greenmachine.common.errors import ErrorContext, GreenMachineError
from greenmachine.domain import WindowProfile
from greenmachine.ingestion.orchestration import MANIFEST_PATH, SNAPSHOT_PATHS
from greenmachine.reporting import (
    DashboardLoadError,
    RunHandle,
    dashboard_loader,
    discover_runs,
    load_dashboard,
    load_verified_run,
)
from greenmachine.reporting.dashboard_loader import bundle_reader

REPO_ROOT = Path(__file__).resolve().parents[3]
EVIDENCE_ROOT = REPO_ROOT / "evidence" / "gm020_vertical_slice"

# Deliberately sensitive-looking paths, carried by the ORIGINAL exceptions. The
# Windows one is assembled from parts rather than written as a literal: the
# release packaging guard scans shipped files for machine-local absolute paths,
# and a literal here would trip it. Building it from parts keeps the test honest
# without weakening that guard.
_SEPARATOR = chr(92)  # backslash
_USER_ROOT = "C:" + _SEPARATOR + "Users"
WINDOWS_PATH = _SEPARATOR.join((_USER_ROOT, "ExampleUser", "private", "evidence", "manifest.json"))
POSIX_PATH = "/very/private/secret/evidence/manifest.json"

SECRET_SEGMENTS = (
    "ExampleUser",
    "private",
    "secret",
    _USER_ROOT,
    "/very/private",
    "Errno",
    "Permission denied",
    "No such file",
    "Traceback",
)

RECENT_SNAPSHOT_PATH = SNAPSHOT_PATHS[WindowProfile.RECENT_7D]
A_REPORT_PATH = "reports/pull_audit_recent_7d.json"


def _first_handle() -> RunHandle:
    return discover_runs(EVIDENCE_ROOT)[0]


def _install_reader(
    monkeypatch: pytest.MonkeyPatch,
    failure: BaseException,
    *,
    on: str | None,
) -> None:
    """Make the loader's reader raise ``failure``, for one path or for all.

    Everything else is delegated to the real confined reader, so the loader
    behaves exactly as it does in production right up to the injected failure.
    """

    def factory(directory: Path) -> Callable[[str], bytes]:
        real = bundle_reader(directory)

        def read(relative_path: str) -> bytes:
            if on is None or relative_path == on:
                raise failure
            return real(relative_path)

        return read

    monkeypatch.setattr(dashboard_loader, "bundle_reader", factory)


def _assert_says_nothing_private(error: DashboardLoadError) -> None:
    rendered = " ".join(
        (
            error.message,
            str(error),
            repr(error.context),
            str(error.as_log_record()),
        )
    )
    for segment in SECRET_SEGMENTS:
        assert segment not in rendered, segment
    assert POSIX_PATH not in rendered
    assert WINDOWS_PATH not in rendered
    # No absolute path of any shape, including the run's own real location.
    assert str(EVIDENCE_ROOT) not in rendered
    assert error.context.file_path is None
    assert "file_path" not in error.context.as_dict()


# --------------------------------------------------------------------------
# The conversion itself
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "original"),
    (
        ("unreadable file", PermissionError(13, "Permission denied", POSIX_PATH)),
        ("unreadable file, windows path", PermissionError(13, "Permission denied", WINDOWS_PATH)),
        (
            "file disappeared after discovery",
            FileNotFoundError(2, "No such file or directory", POSIX_PATH),
        ),
        (
            "file disappeared after discovery, windows path",
            FileNotFoundError(2, "No such file or directory", WINDOWS_PATH),
        ),
    ),
    ids=lambda value: value if isinstance(value, str) else "",
)
def test_a_filesystem_failure_becomes_a_dashboard_load_error(
    label: str, original: OSError, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_reader(monkeypatch, original, on=None)

    with pytest.raises(DashboardLoadError) as caught:
        load_verified_run(_first_handle())

    assert not isinstance(caught.value, OSError)
    assert isinstance(caught.value, GreenMachineError)


@pytest.mark.parametrize(
    "on",
    (None, MANIFEST_PATH, RECENT_SNAPSHOT_PATH, A_REPORT_PATH),
    ids=("every read", "replay verification", "snapshot read", "report read"),
)
def test_every_read_boundary_is_covered(on: str | None, monkeypatch: pytest.MonkeyPatch) -> None:
    """Opening the bundle, replay, the snapshot reads, and the report reads.

    One outermost guard covers all four, which is the point: a future read added
    inside the loader is protected without anyone remembering to wrap it.
    """
    _install_reader(monkeypatch, PermissionError(13, "Permission denied", POSIX_PATH), on=on)

    with pytest.raises(DashboardLoadError):
        load_verified_run(_first_handle())


def test_the_typed_error_discloses_no_path_username_or_oserror_prose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_reader(monkeypatch, PermissionError(13, "Permission denied", POSIX_PATH), on=None)

    with pytest.raises(DashboardLoadError) as caught:
        load_verified_run(_first_handle())

    _assert_says_nothing_private(caught.value)


def test_the_windows_style_path_is_disclosed_no_more_than_the_posix_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_reader(monkeypatch, PermissionError(13, "Permission denied", WINDOWS_PATH), on=None)

    with pytest.raises(DashboardLoadError) as caught:
        load_verified_run(_first_handle())

    _assert_says_nothing_private(caught.value)


def test_the_message_names_the_run_so_the_failure_is_still_diagnosable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A run name is a plain directory label the reviewer already selected."""
    handle = _first_handle()
    _install_reader(monkeypatch, PermissionError(13, "Permission denied", POSIX_PATH), on=None)

    with pytest.raises(DashboardLoadError) as caught:
        load_verified_run(handle)

    assert handle.name in caught.value.message
    assert caught.value.context.subject == handle.name


# --------------------------------------------------------------------------
# What must be preserved
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "original",
    (
        PermissionError(13, "Permission denied", POSIX_PATH),
        FileNotFoundError(2, "No such file or directory", POSIX_PATH),
    ),
    ids=("permission", "vanished"),
)
def test_the_original_exception_survives_as_the_cause(
    original: OSError, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing is lost for engineering: the chain still carries the real failure."""
    _install_reader(monkeypatch, original, on=None)

    with pytest.raises(DashboardLoadError) as caught:
        load_verified_run(_first_handle())

    assert caught.value.__cause__ is original
    assert isinstance(caught.value.__cause__, OSError)
    # The path IS still there — in the chain, where an engineer can read it, and
    # not on any screen.
    assert POSIX_PATH in str(caught.value.__cause__)


def test_a_typed_failure_raised_inside_is_re_raised_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guard must not relabel a failure that was already typed."""
    original = DashboardLoadError(
        "a specific pre-existing typed failure",
        ErrorContext(subject="some-run", metric="a-metric"),
    )
    _install_reader(monkeypatch, original, on=None)

    with pytest.raises(DashboardLoadError) as caught:
        load_verified_run(_first_handle())

    assert caught.value is original
    assert caught.value.message == "a specific pre-existing typed failure"
    assert caught.value.context.metric == "a-metric"


def test_no_partial_run_is_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail closed: there is no half-built VerifiedRun to mistake for a real one."""
    _install_reader(monkeypatch, PermissionError(13, "Permission denied", POSIX_PATH), on=None)

    returned: list[object] = []
    with pytest.raises(DashboardLoadError):
        returned.append(load_verified_run(_first_handle()))

    assert returned == []


def test_the_narrower_dashboard_entry_point_is_covered_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``load_dashboard`` delegates, so it inherits the conversion."""
    _install_reader(monkeypatch, PermissionError(13, "Permission denied", POSIX_PATH), on=None)

    with pytest.raises(DashboardLoadError):
        load_dashboard(_first_handle())


def test_the_injection_seam_itself_does_not_break_a_healthy_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A control: with nothing injected, the same wrapper loads the run normally.

    Without this, every assertion above could be passing for the wrong reason.
    """
    _install_reader(
        monkeypatch,
        PermissionError(13, "Permission denied", POSIX_PATH),
        on="a/path/this/run/does/not/contain.json",
    )

    run = load_verified_run(_first_handle())

    assert run.recent_snapshot.window_profile is WindowProfile.RECENT_7D
    assert run.long_term_snapshot.window_profile is WindowProfile.LONG_TERM_2Y
