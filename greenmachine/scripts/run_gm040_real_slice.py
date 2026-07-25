"""GM-040 real-data vertical-slice operator runner.

One explicit selection — slate date, game, hitter, lineup status — flows
through the unchanged GM-020 pipeline (capture, raw archive, verification,
normalization, mapping) plus the GM-040 operator layer (classification,
operator report, pitcher cross-check, idempotent publication). Replay mode
performs no network access and uses the bundle's own archived inputs.

``SystemClock`` and the real transport are composed **only here**. The hosted
Streamlit app never captures: it remains a verified read-only viewer, and any
bundle published beneath the configured evidence root appears in its run
selector automatically.

Nothing is guessed: an ambiguous or unresolvable game, hitter, or pitcher is
a fail-closed error, never a substitution. Retrospective-development captures
require the explicit ``--capture-mode retrospective`` permission and are
always labeled as such — never as locked pregame predictions.

Usage::

    python scripts/run_gm040_real_slice.py capture \\
        --slate-date 2026-07-25 --game-pk 823650 --batter-id 665742 \\
        --lineup-status projected \\
        --output-dir evidence/gm020_vertical_slice/run_gm040_example \\
        --sample-policy tests/fixtures/ingestion/gm020_nonproduction_sample_policy.json \\
        --capture-mode prospective

    python scripts/run_gm040_real_slice.py replay \\
        --run-dir evidence/gm020_vertical_slice/run_gm040_example
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
    source = str(_REPO_ROOT / "src")
    if source not in sys.path:
        sys.path.insert(0, source)


def _parse_arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="run_gm040_real_slice.py",
        description="GM-040 real-data vertical slice: one game, one hitter, one pitcher.",
    )
    subparsers = parser.add_subparsers(dest="mode", required=True)

    capture = subparsers.add_parser("capture", help="run one explicit real-data capture")
    capture.add_argument("--slate-date", required=True, metavar="YYYY-MM-DD")
    capture.add_argument("--game-pk", required=True, type=int, metavar="GAMEPK")
    capture.add_argument("--batter-id", required=True, type=int, metavar="MLBAM_ID")
    capture.add_argument(
        "--lineup-status",
        required=True,
        choices=("projected", "confirmed"),
        help="operator-supplied hitter lineup status (recorded in the operator report only)",
    )
    capture.add_argument("--output-dir", required=True, type=Path, metavar="DIR")
    capture.add_argument("--sample-policy", required=True, type=Path, metavar="POLICY_JSON")
    capture.add_argument(
        "--capture-mode",
        required=True,
        choices=("prospective", "retrospective"),
        help=(
            "prospective requires a pregame game with recorded timing before first "
            "pitch; retrospective is the explicit development permission and is "
            "always labeled retrospective-development"
        ),
    )
    capture.add_argument(
        "--expected-pitcher-id",
        type=int,
        default=None,
        metavar="MLBAM_ID",
        help=(
            "optional cross-check only: manifest v1 always records the feed-resolved "
            "pitcher, so a mismatch fails closed and publishes nothing"
        ),
    )
    capture.add_argument(
        "--operator-note",
        default="",
        metavar="TEXT",
        help="optional free-text note recorded in the operator report",
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


def _run_capture(arguments: argparse.Namespace) -> int:
    from greenmachine.common.clock import SystemClock
    from greenmachine.ingestion.capture import RetryPolicy
    from greenmachine.ingestion.errors import SamplePolicyError
    from greenmachine.ingestion.models import CaptureMode
    from greenmachine.ingestion.operator import (
        LineupStatus,
        OperatorSelection,
        execute_real_slice,
        publish_or_verify,
    )
    from greenmachine.ingestion.policy import load_sample_policy
    from greenmachine.ingestion.transport import SystemSleeper, UrllibTransport

    try:
        policy_bytes = arguments.sample_policy.read_bytes()
    except OSError as failure:
        raise SamplePolicyError(f"the sample policy could not be read: {failure}") from failure
    load_sample_policy(policy_bytes)  # validate strictly before any network activity

    selection = OperatorSelection(
        slate_date=date.fromisoformat(arguments.slate_date),
        game_pk=arguments.game_pk,
        batter_id=arguments.batter_id,
        lineup_status=LineupStatus(arguments.lineup_status),
        capture_mode=(
            CaptureMode.PROSPECTIVE
            if arguments.capture_mode == "prospective"
            else CaptureMode.RETROSPECTIVE_RECONSTRUCTION
        ),
        expected_pitcher_id=arguments.expected_pitcher_id,
        operator_note=arguments.operator_note,
    )
    run = execute_real_slice(
        selection,
        transport=UrllibTransport(),
        clock=SystemClock(),
        sleeper=SystemSleeper(),
        retry_policy=RetryPolicy(timeout_seconds=30, max_attempts=3, backoff_seconds=(2, 4)),
        sample_policy_bytes=policy_bytes,
    )
    disposition = publish_or_verify(arguments.output_dir, run.files)
    if not run.published:
        print("capture NOT published; failure evidence preserved:", file=sys.stderr)
        for blocker in run.outcome.eligibility.blockers:  # type: ignore[union-attr]
            print(f"  blocker: {blocker}", file=sys.stderr)
        return 3
    assert run.classification is not None
    print(f"{disposition}: {arguments.output_dir.as_posix()}")
    print(f"classification: {run.classification.label}")
    print(f"manifest_id: {run.outcome.manifest_id}")  # type: ignore[union-attr]
    print(f"source_capture_id: {run.outcome.source_capture_id.value}")  # type: ignore[union-attr]
    print("operator report: OPERATOR_REPORT.md / reports/operator_report.json")
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
