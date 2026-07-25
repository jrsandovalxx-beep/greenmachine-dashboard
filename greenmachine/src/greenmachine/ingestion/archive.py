"""Filesystem publication and reading of capture bundles.

The only ingestion module that writes files. Publication is atomic **and
path-safe**: the complete file plan is validated by one centralized
bundle-relative path validator before any directory is created or any byte is
written, every file is written into a sibling staging directory with its
resolved destination re-verified against the staging root (so symlinks or
other path tricks cannot redirect a write), and the staging directory is
renamed into place in one ``os.replace`` — a published run directory either
exists completely or not at all, and an existing directory is never
overwritten (a refresh is a new run directory with a new manifest). A
validation failure writes nothing, inside or outside the requested run.

The replay report is the one additive artifact and it is **idempotent**: an
identical report may be re-verified any number of times, a missing report is
written atomically, and a *different* report fails closed without touching
the existing one.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from pathlib import Path

from .errors import CapturePublicationError

__all__ = [
    "bundle_reader",
    "publish_bundle",
    "validate_bundle_paths",
    "write_replay_report",
]

REPLAY_REPORT_RELATIVE_PATH = "reports/replay.json"


def _reject(path: object, detail: str) -> CapturePublicationError:
    return CapturePublicationError(f"bundle-relative path {path!r} is rejected: {detail}")


def validate_bundle_paths(paths: Sequence[str]) -> None:
    """The one bundle-relative path contract, enforced before anything is written.

    Accepts only nonblank, forward-slash-separated, strictly relative paths:
    no absolute paths, no empty/``.``/``..`` segments, no backslashes, no
    drive prefixes or colons, no NUL characters. Duplicate destinations are
    rejected, including normalized collisions (case-insensitive, because the
    common publication filesystems are) and a file colliding with another
    file's directory.
    """
    seen: dict[str, str] = {}
    directories: set[str] = set()
    for path in paths:
        candidate: object = path
        if not isinstance(candidate, str) or not candidate.strip():
            raise _reject(path, "a destination must be a nonblank string")
        if "\x00" in candidate:
            raise _reject(path, "NUL characters are forbidden")
        if "\\" in candidate:
            raise _reject(path, "backslashes are forbidden; use forward slashes")
        if ":" in candidate:
            raise _reject(path, "colons and drive prefixes are forbidden")
        if candidate.startswith("/"):
            raise _reject(path, "absolute paths are forbidden")
        segments = candidate.split("/")
        for segment in segments:
            if segment == "":
                raise _reject(path, "empty path segments are forbidden")
            if segment == ".":
                raise _reject(path, "'.' segments are forbidden")
            if segment == "..":
                raise _reject(path, "'..' segments are forbidden")
        normalized = candidate.casefold()
        if normalized in seen:
            raise _reject(path, f"duplicate destination (collides with {seen[normalized]!r})")
        if normalized in directories:
            raise _reject(path, "a file may not collide with another file's directory")
        seen[normalized] = candidate
        parent = ""
        for segment in segments[:-1]:
            parent = segment.casefold() if not parent else f"{parent}/{segment.casefold()}"
            if parent in seen:
                raise _reject(path, f"its directory collides with the file {seen[parent]!r}")
            directories.add(parent)


def publish_bundle(directory: Path, files: tuple[tuple[str, bytes], ...]) -> None:
    """Write a bundle atomically into ``directory``; never overwrite an existing run.

    The complete plan is validated first: on any invalid path, nothing is
    created or modified anywhere.
    """
    if not files:
        raise CapturePublicationError("a bundle must contain at least one file")
    validate_bundle_paths([relative_path for relative_path, _ in files])
    if directory.exists():
        raise CapturePublicationError(
            f"run directory '{directory.name}' already exists; published runs are "
            f"immutable and a refresh must use a new directory"
        )
    staging = directory.with_name(directory.name + ".staging")
    if staging.exists():
        raise CapturePublicationError(
            f"staging directory '{staging.name}' already exists; remove the remnant of "
            f"the interrupted publication first"
        )
    directory.parent.mkdir(parents=True, exist_ok=True)
    staging.mkdir()
    staging_root = staging.resolve()
    for relative_path, data in files:
        target = staging / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        # Belt over the validator's suspenders: the resolved destination must
        # still be inside the staging root at write time, so no filesystem
        # trick (a planted symlink, a reparse point) can redirect the write.
        resolved_parent = target.parent.resolve()
        if not resolved_parent.is_relative_to(staging_root):
            raise CapturePublicationError(
                f"publication destination {relative_path!r} resolves outside the "
                f"staging root; refusing to write"
            )
        target.write_bytes(data)
    os.replace(staging, directory)


def bundle_reader(directory: Path) -> Callable[[str], bytes]:
    """A run-relative byte reader confined to the run directory."""
    resolved_root = directory.resolve()

    def read(relative_path: str) -> bytes:
        if "\\" in relative_path or relative_path.startswith("/") or ":" in relative_path:
            raise CapturePublicationError(
                f"run-relative path {relative_path!r} is not a forward-slash relative path"
            )
        target = (resolved_root / relative_path).resolve()
        if not target.is_relative_to(resolved_root):
            raise CapturePublicationError(
                f"run-relative path {relative_path!r} escapes the run directory"
            )
        if not target.is_file():
            raise CapturePublicationError(
                f"run artifact {relative_path!r} does not exist in the run directory"
            )
        return target.read_bytes()

    return read


def write_replay_report(directory: Path, report_bytes: bytes) -> None:
    """Record the replay report idempotently (additive audit artifact only).

    The replay report never participates in any identity and is not part of
    the captured manifest. A missing report is written atomically; an
    existing **byte-identical** report is left untouched and counts as
    success, so the documented replay command is repeatable; an existing
    *different* report fails closed and is never overwritten.
    """
    target = directory / REPLAY_REPORT_RELATIVE_PATH
    if target.exists():
        if target.read_bytes() == report_bytes:
            return
        raise CapturePublicationError(
            "a different replay report already exists for this run; reports are "
            "never overwritten, so the conflict must be inspected by hand"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(target.name + ".staging")
    staging.write_bytes(report_bytes)
    os.replace(staging, target)
