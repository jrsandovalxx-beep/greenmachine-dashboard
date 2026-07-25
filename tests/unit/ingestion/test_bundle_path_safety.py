"""Path-safe publication: the centralized validator and atomic staging."""

from __future__ import annotations

from pathlib import Path

import pytest

from greenmachine.ingestion.archive import (
    bundle_reader,
    publish_bundle,
    validate_bundle_paths,
    write_replay_report,
)
from greenmachine.ingestion.errors import CapturePublicationError

# --------------------------------------------------------------------------
# The validator: every enumerated rejection
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "hostile",
    [
        "../escape",
        "a/../../escape",
        "/absolute/path",
        "C:/escape",
        "C:\\escape",
        "a\\b",
        ".",
        "",
        "   ",
        "a//b",
        "a/./b",
        "a/../b",
        "..",
        "a/..",
        "nul\x00byte",
        "drive:colon",
    ],
    ids=repr,
)
def test_every_hostile_path_shape_is_rejected(hostile: str) -> None:
    with pytest.raises(CapturePublicationError, match="rejected"):
        validate_bundle_paths(["ok/file.txt", hostile])


def test_duplicate_destinations_are_rejected() -> None:
    with pytest.raises(CapturePublicationError, match="duplicate destination"):
        validate_bundle_paths(["a/b.txt", "a/b.txt"])


def test_case_insensitive_normalized_collisions_are_rejected() -> None:
    """Common publication filesystems are case-insensitive: A.txt == a.txt."""
    with pytest.raises(CapturePublicationError, match="duplicate destination"):
        validate_bundle_paths(["reports/A.txt", "reports/a.txt"])


def test_a_file_colliding_with_a_directory_is_rejected() -> None:
    with pytest.raises(CapturePublicationError, match="collide"):
        validate_bundle_paths(["a", "a/b.txt"])
    with pytest.raises(CapturePublicationError, match="collide"):
        validate_bundle_paths(["a/b.txt", "a"])


def test_a_valid_nested_plan_passes() -> None:
    validate_bundle_paths(
        ["manifest.json", "raw/a.json", "reports/deep/nested/file.json", "inputs/policy.json"]
    )


# --------------------------------------------------------------------------
# Publication: whole-plan validation before any byte is written
# --------------------------------------------------------------------------


def test_a_traversal_path_publishes_nothing_inside_or_outside(tmp_path: Path) -> None:
    """The independent-review reproduction: it must now write NOTHING."""
    parent = tmp_path / "runs"
    parent.mkdir()
    run_directory = parent / "run_001"

    with pytest.raises(CapturePublicationError, match=r"'\.\.' segments are forbidden"):
        publish_bundle(
            run_directory,
            (
                ("ok/file.txt", b"ok"),
                ("../escaped.txt", b"ESCAPED"),
            ),
        )

    assert not run_directory.exists()  # the run was not published
    assert not (parent / "escaped.txt").exists()  # nothing escaped
    assert not (tmp_path / "escaped.txt").exists()
    assert list(parent.iterdir()) == []  # no staging remnant, no partial state


def test_an_absolute_destination_publishes_nothing(tmp_path: Path) -> None:
    outside = tmp_path / "outside.txt"
    run_directory = tmp_path / "run_abs"
    with pytest.raises(CapturePublicationError, match="rejected"):
        publish_bundle(run_directory, ((str(outside).replace("\\", "/"), b"x"),))
    assert not outside.exists()
    assert not run_directory.exists()


def test_a_duplicate_destination_publishes_nothing(tmp_path: Path) -> None:
    run_directory = tmp_path / "run_dup"
    with pytest.raises(CapturePublicationError, match="duplicate destination"):
        publish_bundle(run_directory, (("a.txt", b"1"), ("a.txt", b"2")))
    assert not run_directory.exists()
    assert list(tmp_path.iterdir()) == []


def test_a_valid_nested_bundle_still_publishes_atomically(tmp_path: Path) -> None:
    run_directory = tmp_path / "run_ok"
    publish_bundle(
        run_directory,
        (
            ("manifest.json", b"{}"),
            ("raw/deep/nested/artifact.csv", b"a,b\n"),
            ("inputs/policy.json", b"{}"),
        ),
    )
    assert (run_directory / "raw" / "deep" / "nested" / "artifact.csv").read_bytes() == b"a,b\n"
    assert not run_directory.with_name(run_directory.name + ".staging").exists()

    reader = bundle_reader(run_directory)
    assert reader("raw/deep/nested/artifact.csv") == b"a,b\n"
    # Reader confinement remains intact.
    with pytest.raises(CapturePublicationError, match=r"escapes|not a forward-slash"):
        reader("../outside")


# --------------------------------------------------------------------------
# Idempotent replay report
# --------------------------------------------------------------------------


def test_the_replay_report_is_idempotent(tmp_path: Path) -> None:
    run_directory = tmp_path / "run_report"
    publish_bundle(run_directory, (("manifest.json", b"{}"),))

    write_replay_report(run_directory, b'{"ok": true}')
    first = (run_directory / "reports" / "replay.json").read_bytes()
    write_replay_report(run_directory, b'{"ok": true}')  # identical: succeeds silently
    assert (run_directory / "reports" / "replay.json").read_bytes() == first


def test_a_conflicting_replay_report_fails_closed_without_overwriting(tmp_path: Path) -> None:
    run_directory = tmp_path / "run_conflict"
    publish_bundle(run_directory, (("manifest.json", b"{}"),))
    write_replay_report(run_directory, b'{"verdict": "original"}')

    with pytest.raises(CapturePublicationError, match="different replay report"):
        write_replay_report(run_directory, b'{"verdict": "tampered"}')
    assert (run_directory / "reports" / "replay.json").read_bytes() == b'{"verdict": "original"}'
