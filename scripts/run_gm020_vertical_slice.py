"""GM-020 vertical-slice developer runner: one capture or one offline replay.

Not a CLI product — a focused developer tool. Every capture selection is
explicit: the slate date, the game, the batter, the output directory, and the
sample-minimum policy path are all required arguments; nothing is inferred,
defaulted, or read from the environment. The supplied policy bytes are
validated strictly, archived verbatim inside the published bundle, and
digest-pinned there.

``SystemClock`` and the real transport are composed **only here**, at the
composition root. Replay mode performs no network access and takes **no
policy argument**: a published bundle is self-contained, and replay loads,
digest-verifies, and uses the bundle's own archived policy — a different
policy cannot be substituted. Exit is nonzero if regeneration is not
byte-identical.

Usage::

    python scripts/run_gm020_vertical_slice.py capture \\
        --slate-date 2026-07-24 --game-pk 776543 --batter-id 665742 \\
        --output-dir evidence/gm020_vertical_slice/run_001 \\
        --sample-policy tests/fixtures/ingestion/gm020_nonproduction_sample_policy.json \\
        --capture-mode prospective

    python scripts/run_gm020_vertical_slice.py replay \\
        --run-dir evidence/gm020_vertical_slice/run_001
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _ensure_import_path() -> None:
    entry = str(_REPO_ROOT)
    if entry not in sys.path:
        sys.path.insert(0, entry)


def _parse_arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="run_gm020_vertical_slice.py",
        description="GM-020 thin ingestion vertical slice: capture or offline replay.",
    )
    subparsers = parser.add_subparsers(dest="mode", required=True)

    capture = subparsers.add_parser("capture", help="run one coordinated capture")
    capture.add_argument("--slate-date", required=True, metavar="YYYY-MM-DD")
    capture.add_argument("--game-pk", required=True, type=int, metavar="GAMEPK")
    capture.add_argument("--batter-id", required=True, type=int, metavar="MLBAM_ID")
    capture.add_argument("--output-dir", required=True, type=Path, metavar="DIR")
    capture.add_argument("--sample-policy", required=True, type=Path, metavar="POLICY_JSON")
    capture.add_argument(
        "--capture-mode",
        required=True,
        choices=("prospective", "retrospective"),
        help="prospective requires a pregame game; retrospective marks a reconstruction",
    )

    replay = subparsers.add_parser(
        "replay",
        help=(
            "offline replay of a published run; the bundle's own archived, "
            "digest-verified sample policy is used automatically"
        ),
    )
    replay.add_argument("--run-dir", required=True, type=Path, metavar="DIR")

    return parser.parse_args(argv)


def _read_sample_policy_bytes(path: Path) -> bytes:
    """The exact policy bytes, validated strictly before any network activity."""
    from greenmachine.ingestion.errors import SamplePolicyError
    from greenmachine.ingestion.policy import load_sample_policy

    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise SamplePolicyError(f"the sample policy could not be read: {exc}") from exc
    load_sample_policy(raw)
    return raw


def _run_capture(arguments: argparse.Namespace) -> int:
    from greenmachine.common.clock import SystemClock
    from greenmachine.ingestion.archive import publish_bundle
    from greenmachine.ingestion.capture import RetryPolicy
    from greenmachine.ingestion.models import CaptureMode
    from greenmachine.ingestion.orchestration import VerticalSliceRequest, run_capture
    from greenmachine.ingestion.transport import SystemSleeper, UrllibTransport

    policy_bytes = _read_sample_policy_bytes(arguments.sample_policy)
    request = VerticalSliceRequest(
        slate_date=date.fromisoformat(arguments.slate_date),
        game_pk=arguments.game_pk,
        batter_id=arguments.batter_id,
        capture_mode=(
            CaptureMode.PROSPECTIVE
            if arguments.capture_mode == "prospective"
            else CaptureMode.RETROSPECTIVE_RECONSTRUCTION
        ),
    )
    outcome = run_capture(
        request,
        transport=UrllibTransport(),
        clock=SystemClock(),
        sleeper=SystemSleeper(),
        retry_policy=RetryPolicy(timeout_seconds=30, max_attempts=3, backoff_seconds=(2, 4)),
        sample_policy_bytes=policy_bytes,
    )
    publish_bundle(arguments.output_dir, outcome.files)
    if not outcome.published:
        print("capture NOT published; failure evidence preserved:", file=sys.stderr)
        for blocker in outcome.eligibility.blockers:  # type: ignore[union-attr]
            print(f"  blocker: {blocker}", file=sys.stderr)
        return 3
    print(f"published run to {arguments.output_dir.as_posix()}")
    print(f"manifest_id: {outcome.manifest_id}")  # type: ignore[union-attr]
    print(f"source_capture_id: {outcome.source_capture_id.value}")  # type: ignore[union-attr]
    return 0


def _run_replay(arguments: argparse.Namespace) -> int:
    from greenmachine.common.serialization import canonical_bytes
    from greenmachine.ingestion.archive import bundle_reader, write_replay_report
    from greenmachine.ingestion.orchestration import replay_run

    reader = bundle_reader(arguments.run_dir)
    result = replay_run(reader)
    write_replay_report(arguments.run_dir, canonical_bytes(result.report_document))
    print(f"manifest_id: {result.manifest_id}")
    print(f"source_capture_id: {result.source_capture_id.value}")
    print(f"recent snapshot byte-identical: {result.recent_identical}")
    print(f"long-term snapshot byte-identical: {result.long_term_identical}")
    if not result.byte_identical:
        print("replay FAILED: regenerated snapshots are not byte-identical", file=sys.stderr)
        return 4
    print("replay OK: both snapshots regenerated byte-identically offline")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    _ensure_import_path()
    from greenmachine.common.errors import GreenMachineError

    arguments = _parse_arguments(argv)
    try:
        if arguments.mode == "capture":
            return _run_capture(arguments)
        return _run_replay(arguments)
    except GreenMachineError as failure:
        print(f"error [{failure.error_type}]: {failure.message}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
