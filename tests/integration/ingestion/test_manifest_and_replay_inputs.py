"""Strict manifest replay and the self-contained, digest-pinned replay inputs.

Every mutation here targets the GreenMachine-owned documents (``manifest.json``
and ``inputs/``): no malformed member may be silently skipped or coerced, and
no policy other than the archived, digest-verified bytes can govern a replay.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest
from tests.fixtures.ingestion import synthetic_provider_fixtures as fixtures

from greenmachine.common.serialization import canonical_bytes
from greenmachine.ingestion.archive import bundle_reader, publish_bundle
from greenmachine.ingestion.capture import RetryPolicy
from greenmachine.ingestion.errors import ProviderResponseError, SamplePolicyError
from greenmachine.ingestion.models import CaptureMode
from greenmachine.ingestion.orchestration import (
    REPLAY_INPUTS_PATH,
    SAMPLE_POLICY_PATH,
    VerticalSliceRequest,
    replay_run,
    run_capture,
)

_JSON = dict[str, object]


def _published(tmp_path: Path, name: str = "run") -> Path:
    outcome = run_capture(
        VerticalSliceRequest(
            slate_date=date(2026, 7, 15),
            game_pk=fixtures.GAME_PK,
            batter_id=fixtures.BATTER_ID,
            capture_mode=CaptureMode.RETROSPECTIVE_RECONSTRUCTION,
        ),
        transport=fixtures.FakeTransport(routes=fixtures.default_routes()),
        clock=fixtures.SteppingClock(),
        sleeper=fixtures.RecordingSleeper(),
        retry_policy=RetryPolicy(timeout_seconds=10, max_attempts=3, backoff_seconds=(1, 2)),
        sample_policy_bytes=fixtures.sample_policy_bytes(),
    )
    assert outcome.published  # type: ignore[attr-defined]
    run_dir = tmp_path / name
    publish_bundle(run_dir, outcome.files)  # type: ignore[attr-defined]
    return run_dir


def _mutated_manifest_reader(
    run_dir: Path, mutate: Callable[[_JSON], None]
) -> Callable[[str], bytes]:
    document = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    mutate(document)
    replaced = canonical_bytes(document)
    inner = bundle_reader(run_dir)

    def reader(relative_path: str) -> bytes:
        if relative_path == "manifest.json":
            return replaced
        return inner(relative_path)

    return reader


def _first_entry(document: _JSON) -> _JSON:
    entries = document["entries"]
    assert isinstance(entries, list)
    entry = entries[0]
    assert isinstance(entry, dict)
    return entry


# --------------------------------------------------------------------------
# Manifest mutations: each fails closed with a deterministic typed error
# --------------------------------------------------------------------------


def test_a_changed_capture_id_is_rejected_before_raw_parsing(tmp_path: Path) -> None:
    run_dir = _published(tmp_path)

    def mutate(document: _JSON) -> None:
        _first_entry(document)["capture_id"] = "raw_capture-" + "0" * 64

    with pytest.raises(ProviderResponseError, match="not the entry that was published"):
        replay_run(_mutated_manifest_reader(run_dir, mutate))


def test_a_malformed_parameter_item_is_rejected_not_skipped(tmp_path: Path) -> None:
    run_dir = _published(tmp_path)

    def mutate(document: _JSON) -> None:
        parameters = _first_entry(document)["parameters"]
        assert isinstance(parameters, list)
        parameters.append(["orphan_key_without_value"])

    with pytest.raises(ProviderResponseError, match="malformed parameter item"):
        replay_run(_mutated_manifest_reader(run_dir, mutate))


def test_a_non_string_parameter_element_is_rejected_not_coerced(tmp_path: Path) -> None:
    run_dir = _published(tmp_path)

    def mutate(document: _JSON) -> None:
        parameters = _first_entry(document)["parameters"]
        assert isinstance(parameters, list)
        parameters.append(["numeric_value", 7])

    with pytest.raises(ProviderResponseError, match="must both be strings"):
        replay_run(_mutated_manifest_reader(run_dir, mutate))


def test_a_malformed_attempt_item_is_rejected_not_skipped(tmp_path: Path) -> None:
    run_dir = _published(tmp_path)

    def mutate(document: _JSON) -> None:
        attempts = _first_entry(document)["attempts"]
        assert isinstance(attempts, list)
        attempts.append("not-an-attempt-object")

    with pytest.raises(ProviderResponseError, match="malformed attempt item"):
        replay_run(_mutated_manifest_reader(run_dir, mutate))


def test_out_of_order_attempt_indexes_are_rejected(tmp_path: Path) -> None:
    run_dir = _published(tmp_path)

    def mutate(document: _JSON) -> None:
        attempts = _first_entry(document)["attempts"]
        assert isinstance(attempts, list)
        first = attempts[0]
        assert isinstance(first, dict)
        first["index"] = 5

    with pytest.raises(ProviderResponseError, match="consecutive ascending"):
        replay_run(_mutated_manifest_reader(run_dir, mutate))


def test_a_string_false_in_participates_in_snapshot_is_rejected(tmp_path: Path) -> None:
    """'false' as a string must not be coerced — truthiness would flip it."""
    run_dir = _published(tmp_path)

    def mutate(document: _JSON) -> None:
        _first_entry(document)["participates_in_snapshot"] = "false"

    with pytest.raises(ProviderResponseError, match="JSON boolean"):
        replay_run(_mutated_manifest_reader(run_dir, mutate))


def test_an_invalid_optional_http_status_is_rejected(tmp_path: Path) -> None:
    run_dir = _published(tmp_path)

    def mutate(document: _JSON) -> None:
        attempts = _first_entry(document)["attempts"]
        assert isinstance(attempts, list)
        first = attempts[0]
        assert isinstance(first, dict)
        first["http_status"] = "200"

    with pytest.raises(ProviderResponseError, match="must be an integer or null"):
        replay_run(_mutated_manifest_reader(run_dir, mutate))


def test_an_extra_unexpected_manifest_field_is_rejected(tmp_path: Path) -> None:
    run_dir = _published(tmp_path)

    def mutate(document: _JSON) -> None:
        document["unexpected_future_field"] = True

    with pytest.raises(ProviderResponseError, match="unknown field"):
        replay_run(_mutated_manifest_reader(run_dir, mutate))


def test_a_missing_manifest_field_is_rejected(tmp_path: Path) -> None:
    run_dir = _published(tmp_path)

    def mutate(document: _JSON) -> None:
        del document["run_completed_at"]

    with pytest.raises(ProviderResponseError, match="missing required field"):
        replay_run(_mutated_manifest_reader(run_dir, mutate))


def test_a_duplicate_entry_label_is_rejected(tmp_path: Path) -> None:
    run_dir = _published(tmp_path)

    def mutate(document: _JSON) -> None:
        entries = document["entries"]
        assert isinstance(entries, list)
        entries.append(json.loads(json.dumps(entries[0])))

    with pytest.raises(ProviderResponseError, match="duplicate entry label"):
        replay_run(_mutated_manifest_reader(run_dir, mutate))


def test_an_unknown_entry_field_is_rejected(tmp_path: Path) -> None:
    run_dir = _published(tmp_path)

    def mutate(document: _JSON) -> None:
        _first_entry(document)["surprise"] = 1

    with pytest.raises(ProviderResponseError, match="unknown field"):
        replay_run(_mutated_manifest_reader(run_dir, mutate))


# --------------------------------------------------------------------------
# Self-contained replay inputs
# --------------------------------------------------------------------------


def test_a_copied_run_directory_alone_is_sufficient_for_replay(tmp_path: Path) -> None:
    run_dir = _published(tmp_path)
    copy = tmp_path / "copied_elsewhere"
    shutil.copytree(run_dir, copy)
    result = replay_run(bundle_reader(copy))
    assert result.byte_identical


def test_one_byte_policy_corruption_fails_replay(tmp_path: Path) -> None:
    run_dir = _published(tmp_path)
    target = run_dir / SAMPLE_POLICY_PATH
    corrupted = bytearray(target.read_bytes())
    corrupted[-2] ^= 0x01
    target.write_bytes(bytes(corrupted))
    with pytest.raises(SamplePolicyError, match="not the policy the capture validated"):
        replay_run(bundle_reader(run_dir))


def test_a_different_valid_policy_fails_digest_verification(tmp_path: Path) -> None:
    run_dir = _published(tmp_path)
    substitute = fixtures.sample_policy_bytes(recent=999, long_term=999)
    (run_dir / SAMPLE_POLICY_PATH).write_bytes(substitute)
    with pytest.raises(SamplePolicyError, match="not the policy the capture validated"):
        replay_run(bundle_reader(run_dir))


def test_replay_inputs_reject_unknown_fields_and_wrong_versions(tmp_path: Path) -> None:
    run_dir = _published(tmp_path)
    inputs_path = run_dir / REPLAY_INPUTS_PATH
    document = json.loads(inputs_path.read_text(encoding="utf-8"))

    extra = dict(document)
    extra["surprise"] = 1
    inputs_path.write_bytes(canonical_bytes(extra))
    with pytest.raises(SamplePolicyError, match="unknown field"):
        replay_run(bundle_reader(run_dir))

    wrong_version = dict(document)
    wrong_version["replay_inputs_schema_version"] = 2
    inputs_path.write_bytes(canonical_bytes(wrong_version))
    with pytest.raises(SamplePolicyError, match="schema version"):
        replay_run(bundle_reader(run_dir))


# --------------------------------------------------------------------------
# Duplicate JSON keys are rejected at every nesting level
# --------------------------------------------------------------------------


def _duplicate_key_reader(
    run_dir: Path, relative_path: str, token: str, injected: str
) -> Callable[[str], bytes]:
    """Replace the first occurrence of ``token`` with ``injected + token``,
    duplicating a key inside the same JSON object."""
    original = (run_dir / relative_path).read_text(encoding="utf-8")
    assert token in original, f"token {token!r} not found in {relative_path}"
    replaced = original.replace(token, injected + token, 1).encode("utf-8")
    inner = bundle_reader(run_dir)

    def reader(path: str) -> bytes:
        if path == relative_path:
            return replaced
        return inner(path)

    return reader


def test_a_duplicate_top_level_manifest_field_is_rejected(tmp_path: Path) -> None:
    run_dir = _published(tmp_path)
    reader = _duplicate_key_reader(run_dir, "manifest.json", '"game_id":', '"game_id":"999999",')
    with pytest.raises(ProviderResponseError, match="duplicate JSON object key"):
        replay_run(reader)


def test_a_duplicate_entry_field_is_rejected(tmp_path: Path) -> None:
    run_dir = _published(tmp_path)
    reader = _duplicate_key_reader(run_dir, "manifest.json", '"label":', '"label":"zz_shadowed",')
    with pytest.raises(ProviderResponseError, match="duplicate JSON object key"):
        replay_run(reader)


def test_a_duplicate_attempt_field_is_rejected(tmp_path: Path) -> None:
    run_dir = _published(tmp_path)
    reader = _duplicate_key_reader(run_dir, "manifest.json", '"index":', '"index":99,')
    with pytest.raises(ProviderResponseError, match="duplicate JSON object key"):
        replay_run(reader)


def test_a_duplicate_replay_input_field_is_rejected(tmp_path: Path) -> None:
    run_dir = _published(tmp_path)
    reader = _duplicate_key_reader(
        run_dir,
        REPLAY_INPUTS_PATH,
        '"classification":',
        '"classification":"production",',
    )
    with pytest.raises(SamplePolicyError, match="duplicate JSON object key"):
        replay_run(reader)


def test_a_duplicate_sample_policy_component_is_rejected() -> None:
    document = json.loads(fixtures.sample_policy_bytes().decode("utf-8"))
    text = json.dumps(document)
    assert '"exit_velocity":' in text
    duplicated = text.replace(
        '"exit_velocity":',
        '"exit_velocity": {"RECENT_7D": 1, "LONG_TERM_2Y": 1}, "exit_velocity":',
        1,
    )
    from greenmachine.ingestion.policy import load_sample_policy

    with pytest.raises(SamplePolicyError, match="duplicate JSON object key"):
        load_sample_policy(duplicated.encode("utf-8"))


def test_a_duplicate_sample_policy_profile_is_rejected() -> None:
    text = fixtures.sample_policy_bytes().decode("utf-8")
    assert '"RECENT_7D":' in text
    duplicated = text.replace('"RECENT_7D":', '"RECENT_7D": 1, "RECENT_7D":', 1)
    from greenmachine.ingestion.policy import load_sample_policy

    with pytest.raises(SamplePolicyError, match="duplicate JSON object key"):
        load_sample_policy(duplicated.encode("utf-8"))


# --------------------------------------------------------------------------
# Replay-input metadata: exact values, exact types
# --------------------------------------------------------------------------


def _rewrite_replay_inputs(run_dir: Path, mutate: Callable[[dict[str, object]], None]) -> None:
    inputs_path = run_dir / REPLAY_INPUTS_PATH
    document = json.loads(inputs_path.read_text(encoding="utf-8"))
    mutate(document)
    inputs_path.write_bytes(canonical_bytes(document))


def test_a_production_classification_is_rejected(tmp_path: Path) -> None:
    run_dir = _published(tmp_path)

    def mutate(document: dict[str, object]) -> None:
        document["classification"] = "production"

    _rewrite_replay_inputs(run_dir, mutate)
    with pytest.raises(SamplePolicyError, match="'classification'"):
        replay_run(bundle_reader(run_dir))


def test_a_numeric_disclaimer_is_rejected(tmp_path: Path) -> None:
    run_dir = _published(tmp_path, name="numeric_disclaimer")

    def numeric(document: dict[str, object]) -> None:
        document["disclaimer"] = 7

    _rewrite_replay_inputs(run_dir, numeric)
    with pytest.raises(SamplePolicyError, match="'disclaimer' must be a string"):
        replay_run(bundle_reader(run_dir))


def test_a_null_statement_is_rejected(tmp_path: Path) -> None:
    run_dir = _published(tmp_path, name="null_statement")

    def null(document: dict[str, object]) -> None:
        document["statement"] = None

    _rewrite_replay_inputs(run_dir, null)
    with pytest.raises(SamplePolicyError, match="'statement' must be a string"):
        replay_run(bundle_reader(run_dir))


def test_a_weakened_statement_or_disclaimer_is_rejected(tmp_path: Path) -> None:
    run_dir = _published(tmp_path)

    def mutate(document: dict[str, object]) -> None:
        document["disclaimer"] = "fine to use in production"

    _rewrite_replay_inputs(run_dir, mutate)
    with pytest.raises(SamplePolicyError, match="exact required v1 value"):
        replay_run(bundle_reader(run_dir))


def test_a_malformed_digest_is_rejected(tmp_path: Path) -> None:
    run_dir = _published(tmp_path)

    def uppercase(document: dict[str, object]) -> None:
        digest = document["sample_policy_sha256"]
        assert isinstance(digest, str)
        document["sample_policy_sha256"] = digest.upper()

    _rewrite_replay_inputs(run_dir, uppercase)
    with pytest.raises(SamplePolicyError, match="lowercase"):
        replay_run(bundle_reader(run_dir))

    def truncated(document: dict[str, object]) -> None:
        document["sample_policy_sha256"] = "abc123"

    _rewrite_replay_inputs(run_dir, truncated)
    with pytest.raises(SamplePolicyError, match="64-character"):
        replay_run(bundle_reader(run_dir))


def test_source_capture_id_is_unaffected_by_the_policy(tmp_path: Path) -> None:
    """Different policy bytes: different snapshots, same SourceCaptureId."""

    def run_with(policy_bytes: bytes) -> object:
        return run_capture(
            VerticalSliceRequest(
                slate_date=date(2026, 7, 15),
                game_pk=fixtures.GAME_PK,
                batter_id=fixtures.BATTER_ID,
                capture_mode=CaptureMode.RETROSPECTIVE_RECONSTRUCTION,
            ),
            transport=fixtures.FakeTransport(routes=fixtures.default_routes()),
            clock=fixtures.SteppingClock(),
            sleeper=fixtures.RecordingSleeper(),
            retry_policy=RetryPolicy(timeout_seconds=10, max_attempts=3, backoff_seconds=(1, 2)),
            sample_policy_bytes=policy_bytes,
        )

    lenient = run_with(fixtures.sample_policy_bytes(recent=2, long_term=13))
    demanding = run_with(fixtures.sample_policy_bytes(recent=999, long_term=999))
    assert lenient.source_capture_id == demanding.source_capture_id  # type: ignore[attr-defined]
    assert (
        lenient.recent.snapshot.snapshot_id  # type: ignore[attr-defined]
        != demanding.recent.snapshot.snapshot_id  # type: ignore[attr-defined]
    )
