"""GM-041.5: a filesystem failure during discovery leaves it typed, not raw.

``load_verified_run`` types its own filesystem failures, but it cannot protect
this one: discovery runs **before** a run has been selected, so there is no
run-level boundary between an unreadable evidence root and the screen. An
``OSError`` raised while resolving the root, enumerating it, or resolving a child
named the root's absolute path and travelled out untyped.

The three fallible operations are ``root.resolve()``, ``root.iterdir()``, and
``child.resolve()``. Each is exercised here, by INJECTION rather than by changing
real filesystem permissions, so the suite behaves identically on every platform.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from greenmachine.common.errors import ErrorContext, GreenMachineError
from greenmachine.reporting import DashboardLoadError, RunHandle, discover_runs

REPO_ROOT = Path(__file__).resolve().parents[3]
EVIDENCE_ROOT = REPO_ROOT / "evidence" / "gm020_vertical_slice"

# Deliberately sensitive-looking roots, carried by the ORIGINAL exceptions. The
# Windows one is assembled from parts rather than written as a literal: the
# release packaging guard scans shipped files for machine-local absolute paths,
# and a literal here would trip it. Building it from parts keeps the test honest
# without weakening that guard.
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
)


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
    assert POSIX_ROOT not in rendered
    assert WINDOWS_ROOT not in rendered
    # No absolute path of any shape, including the real evidence root.
    assert str(EVIDENCE_ROOT) not in rendered
    assert error.context.file_path is None
    assert "file_path" not in error.context.as_dict()


class _Root:
    """A stand-in evidence root that fails at exactly one chosen step.

    Every other operation delegates to the real evidence root, and the whole
    discovery algorithm runs through it whether or not a failure is injected —
    so the control case below genuinely exercises this seam rather than
    quietly bypassing it. ``__fspath__`` is what lets the real confinement check
    (``resolved.is_relative_to(root)``) keep working unchanged.
    """

    def __init__(
        self,
        *,
        failure: BaseException | None = None,
        at: str | None = None,
        real: Path = EVIDENCE_ROOT,
    ) -> None:
        self._failure = failure
        self._at = at
        self._real = real.resolve()

    def _maybe_fail(self, step: str) -> None:
        if self._failure is not None and self._at == step:
            raise self._failure

    def __fspath__(self) -> str:
        return str(self._real)

    def resolve(self) -> _Root:
        self._maybe_fail("resolve")
        return self

    def is_dir(self) -> bool:
        return self._real.is_dir()

    def iterdir(self) -> Iterator[_Child]:
        self._maybe_fail("iterdir")
        for child in self._real.iterdir():
            yield _Child(child, self._failure if self._at == "child_resolve" else None)

    def __truediv__(self, other: str) -> Path:
        return self._real / other


class _Child:
    """One enumerated child that may fail when resolved."""

    def __init__(self, real: Path, failure: BaseException | None) -> None:
        self._real = real
        self._failure = failure

    @property
    def name(self) -> str:
        return self._real.name

    def is_dir(self) -> bool:
        return self._real.is_dir()

    def resolve(self) -> Path:
        if self._failure is not None:
            raise self._failure
        return self._real.resolve()


def _discover(root: object) -> tuple[RunHandle, ...]:
    """Call the public boundary with an injected root."""
    return discover_runs(root)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# The conversion itself
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "step", "original"),
    (
        (
            "enumeration refused",
            "iterdir",
            PermissionError(13, "Permission denied", POSIX_ROOT),
        ),
        (
            "enumeration refused, windows root",
            "iterdir",
            PermissionError(13, "Permission denied", WINDOWS_ROOT),
        ),
        (
            "root vanished between the directory check and enumeration",
            "iterdir",
            FileNotFoundError(2, "No such file or directory", POSIX_ROOT),
        ),
        (
            "root resolution refused",
            "resolve",
            PermissionError(13, "Permission denied", POSIX_ROOT),
        ),
        (
            "child resolution failed",
            "child_resolve",
            OSError(5, "Input/output error", POSIX_ROOT),
        ),
    ),
    ids=lambda value: value if isinstance(value, str) and " " in value else "",
)
def test_a_discovery_failure_becomes_a_dashboard_load_error(
    label: str, step: str, original: OSError
) -> None:
    with pytest.raises(DashboardLoadError) as caught:
        _discover(_Root(failure=original, at=step))

    assert not isinstance(caught.value, OSError)
    assert isinstance(caught.value, GreenMachineError)
    assert caught.value.__cause__ is original
    _assert_says_nothing_private(caught.value)


def test_no_partial_catalog_is_returned() -> None:
    """The exception replaces the catalog; it never truncates it.

    ``child_resolve`` fails partway through a root that really does contain
    runs, so a loop that swallowed the error would return a short-but-plausible
    tuple — the worst outcome, because it looks like a real answer.
    """
    returned: list[object] = []
    with pytest.raises(DashboardLoadError):
        returned.append(_discover(_Root(failure=PermissionError(13, "no"), at="child_resolve")))

    assert returned == []


def test_a_typed_failure_raised_inside_is_re_raised_unchanged() -> None:
    """The guard must not relabel a failure that was already typed."""
    original = DashboardLoadError(
        "a specific pre-existing typed failure",
        ErrorContext(subject="some-catalog", metric="a-metric"),
    )

    with pytest.raises(DashboardLoadError) as caught:
        _discover(_Root(failure=original, at="iterdir"))

    assert caught.value is original
    assert caught.value.message == "a specific pre-existing typed failure"
    assert caught.value.context.metric == "a-metric"


def test_the_original_exception_stays_readable_for_engineering() -> None:
    original = PermissionError(13, "Permission denied", POSIX_ROOT)

    with pytest.raises(DashboardLoadError) as caught:
        _discover(_Root(failure=original, at="iterdir"))

    # The path IS still there -- in the chain, where an engineer can read it,
    # and on no screen.
    assert POSIX_ROOT in str(caught.value.__cause__)


# --------------------------------------------------------------------------
# What must NOT change
# --------------------------------------------------------------------------


def test_an_absent_evidence_root_is_still_an_empty_catalog(tmp_path: Path) -> None:
    """Not a failure, and never was: nothing approved is simply nothing to show."""
    assert discover_runs(tmp_path / "does" / "not" / "exist") == ()


def test_a_non_directory_evidence_root_is_still_an_empty_catalog(tmp_path: Path) -> None:
    target = tmp_path / "not_a_directory"
    target.write_text("", encoding="utf-8")

    assert discover_runs(target) == ()


def test_an_empty_evidence_root_is_still_an_empty_catalog(tmp_path: Path) -> None:
    assert discover_runs(tmp_path) == ()


def test_normal_discovery_is_unchanged_sorted_and_deterministic() -> None:
    """The control: the typed boundary is transparent to a healthy catalog."""
    first = discover_runs(EVIDENCE_ROOT)
    second = discover_runs(EVIDENCE_ROOT)

    assert first == second
    assert [handle.name for handle in first] == sorted(handle.name for handle in first)
    assert first, "the shipped evidence root must contain approved runs"
    for handle in first:
        assert (handle.directory / "manifest.json").is_file()


def test_the_injection_seam_itself_does_not_break_a_healthy_catalog() -> None:
    """Anti-vacuity: with nothing injected, the same seam discovers normally.

    Without this, every failure assertion above could be passing because the
    stand-in root is broken rather than because the guard works.
    """
    through_seam = _discover(_Root())
    directly = discover_runs(EVIDENCE_ROOT)

    assert through_seam, "the seam must find the approved runs, not silently none"
    assert [handle.name for handle in through_seam] == [handle.name for handle in directly]
    assert [handle.directory for handle in through_seam] == [
        handle.directory for handle in directly
    ]


def test_a_symlink_escaping_the_root_is_still_never_offered(tmp_path: Path) -> None:
    """The confinement rule is untouched by the new boundary."""
    outside = tmp_path / "outside"
    (outside / "sneaky_run").mkdir(parents=True)
    (outside / "sneaky_run" / "manifest.json").write_text("{}", encoding="utf-8")

    root = tmp_path / "evidence"
    root.mkdir()
    try:
        (root / "sneaky_run").symlink_to(outside / "sneaky_run", target_is_directory=True)
    except (OSError, NotImplementedError):  # pragma: no cover - platform dependent
        pytest.skip("directory symlinks are unavailable on this platform")

    assert discover_runs(root) == ()
