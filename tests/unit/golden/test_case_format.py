"""Strict golden case-format validation: every malformed shape is rejected loudly.

Each test builds a case directory in ``tmp_path`` from valid canonical fixture
bytes, breaks exactly one thing, and asserts the focused
:class:`GoldenCaseError` names the case directory and the offending key.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import synthetic_golden_cases
import synthetic_records
from tests.golden.runner import (
    MANIFEST_FILENAME,
    GoldenCase,
    GoldenCaseError,
    discover_cases,
    load_case,
)
from tests.golden.stub_scorer import score_snapshot

from greenmachine.domain import WindowProfile
from greenmachine.evaluation import serialize_record

CONFIG_VERSION = synthetic_golden_cases.GOLDEN_CONFIG_VERSION

RECENT_SNAPSHOT_BYTES = serialize_record(synthetic_records.input_snapshot())
RECENT_EXPECTED_BYTES = serialize_record(
    score_snapshot(synthetic_records.input_snapshot(), CONFIG_VERSION)
)
LONG_TERM_SNAPSHOT_BYTES = serialize_record(synthetic_records.input_snapshot_long_term())
LONG_TERM_EXPECTED_BYTES = serialize_record(
    score_snapshot(synthetic_records.input_snapshot_long_term(), CONFIG_VERSION)
)
ENVELOPE_BYTES = serialize_record(synthetic_records.evaluation_envelope())


def write_case(
    directory: Path,
    *,
    case_id: str = "synthetic-case",
    profile: str = "RECENT_7D",
    snapshot_bytes: bytes = RECENT_SNAPSHOT_BYTES,
    expected_bytes: bytes = RECENT_EXPECTED_BYTES,
    manifest_overrides: dict[str, object] | None = None,
    manifest_bytes: bytes | None = None,
    omit_files: frozenset[str] = frozenset(),
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, object] = {
        "case_id": case_id,
        "config_version_identifier": CONFIG_VERSION,
        "window_profile": profile,
        "snapshot_file": "input_snapshot.json",
        "expected_file": "expected_grade_result.json",
    }
    if manifest_overrides:
        for key, value in manifest_overrides.items():
            if value is None:
                manifest.pop(key, None)
            else:
                manifest[key] = value
    if manifest_bytes is None:
        manifest_bytes = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8")
    (directory / MANIFEST_FILENAME).write_bytes(manifest_bytes)
    if "input_snapshot.json" not in omit_files:
        (directory / "input_snapshot.json").write_bytes(snapshot_bytes)
    if "expected_grade_result.json" not in omit_files:
        (directory / "expected_grade_result.json").write_bytes(expected_bytes)
    return directory


# --------------------------------------------------------------------------
# Valid cases load
# --------------------------------------------------------------------------


def test_valid_recent_case_loads(tmp_path: Path) -> None:
    directory = write_case(tmp_path / "recent-case", case_id="synthetic-recent")
    case = load_case(directory)

    assert isinstance(case, GoldenCase)
    assert case.case_id == "synthetic-recent"
    assert case.config_version_identifier == CONFIG_VERSION
    assert case.window_profile is WindowProfile.RECENT_7D
    assert case.snapshot.window_profile is WindowProfile.RECENT_7D
    assert case.expected_result.window_profile is WindowProfile.RECENT_7D
    assert case.directory == directory.resolve()
    assert case.snapshot_filename == "input_snapshot.json"
    assert case.expected_filename == "expected_grade_result.json"


def test_valid_long_term_case_loads(tmp_path: Path) -> None:
    directory = write_case(
        tmp_path / "long-term-case",
        case_id="synthetic-long-term",
        profile="LONG_TERM_2Y",
        snapshot_bytes=LONG_TERM_SNAPSHOT_BYTES,
        expected_bytes=LONG_TERM_EXPECTED_BYTES,
    )
    case = load_case(directory)

    assert case.window_profile is WindowProfile.LONG_TERM_2Y
    assert case.snapshot.window_profile is WindowProfile.LONG_TERM_2Y


def test_loaded_case_is_immutable(tmp_path: Path) -> None:
    case = load_case(write_case(tmp_path / "case"))
    with pytest.raises(AttributeError):
        case.case_id = "other"  # type: ignore[misc]


# --------------------------------------------------------------------------
# Manifest rejections
# --------------------------------------------------------------------------


def test_malformed_manifest_json_is_rejected(tmp_path: Path) -> None:
    directory = write_case(tmp_path / "case", manifest_bytes=b'{"case_id": ')
    with pytest.raises(GoldenCaseError, match="not valid JSON"):
        load_case(directory)


def test_non_object_manifest_root_is_rejected(tmp_path: Path) -> None:
    directory = write_case(tmp_path / "case", manifest_bytes=b'["not", "an", "object"]')
    with pytest.raises(GoldenCaseError, match="root must be a JSON object"):
        load_case(directory)


def test_float_in_manifest_is_rejected(tmp_path: Path) -> None:
    directory = write_case(
        tmp_path / "case",
        manifest_bytes=(
            b'{"case_id": 1.5, "config_version_identifier": "x", "window_profile": '
            b'"RECENT_7D", "snapshot_file": "a", "expected_file": "b"}'
        ),
    )
    with pytest.raises(GoldenCaseError, match="floating-point"):
        load_case(directory)


def test_unknown_manifest_key_is_rejected(tmp_path: Path) -> None:
    directory = write_case(tmp_path / "case", manifest_overrides={"extra_key": "value"})
    with pytest.raises(GoldenCaseError, match=r"unknown manifest field\(s\).*extra_key"):
        load_case(directory)


@pytest.mark.parametrize(
    "key",
    ["case_id", "config_version_identifier", "window_profile", "snapshot_file", "expected_file"],
)
def test_each_missing_manifest_key_is_rejected(tmp_path: Path, key: str) -> None:
    directory = write_case(tmp_path / "case", manifest_overrides={key: None})
    with pytest.raises(GoldenCaseError, match=f"missing required manifest field.*{key}"):
        load_case(directory)


def test_blank_case_id_is_rejected(tmp_path: Path) -> None:
    directory = write_case(tmp_path / "case", manifest_overrides={"case_id": "   "})
    with pytest.raises(GoldenCaseError, match="case_id must be a stable identifier"):
        load_case(directory)


def test_non_string_case_id_is_rejected(tmp_path: Path) -> None:
    directory = write_case(tmp_path / "case", manifest_overrides={"case_id": 7})
    with pytest.raises(GoldenCaseError, match="case_id must be a string"):
        load_case(directory)


# --------------------------------------------------------------------------
# The case_id stable-identifier convention: ^[a-z][a-z0-9_-]*$
# --------------------------------------------------------------------------

ACCEPTED_CASE_IDS = ["synthetic-recent-evaluated", "case_2", "a", "a0", "a-b_c-9"]

REJECTED_CASE_IDS = [
    "not stable!",
    " has-space",
    "has space",
    "UPPER",
    "Mixed-Case",
    "-starts-with-dash",
    "_starts_with_underscore",
    "ends.",
    "dotted.name",
    "",
    "   ",
    "\t\n",
    "café",
    "0-starts-with-digit",
]


@pytest.mark.parametrize("case_id", ACCEPTED_CASE_IDS)
def test_stable_case_ids_are_accepted(tmp_path: Path, case_id: str) -> None:
    directory = write_case(tmp_path / "case", manifest_overrides={"case_id": case_id})
    assert load_case(directory).case_id == case_id


@pytest.mark.parametrize("case_id", REJECTED_CASE_IDS, ids=repr)
def test_unstable_case_ids_are_rejected(tmp_path: Path, case_id: str) -> None:
    directory = write_case(tmp_path / "case", manifest_overrides={"case_id": case_id})
    with pytest.raises(GoldenCaseError, match="case_id must be a stable identifier") as failure:
        load_case(directory)
    message = str(failure.value)
    assert repr(case_id) in message  # the received value is named
    assert str(directory / MANIFEST_FILENAME) in message  # the owning case is named


def test_case_id_error_documents_the_convention(tmp_path: Path) -> None:
    directory = write_case(tmp_path / "case", manifest_overrides={"case_id": "UPPER"})
    with pytest.raises(GoldenCaseError, match=r"\^\[a-z\]\[a-z0-9_-\]\*\$"):
        load_case(directory)


@pytest.mark.parametrize("case_id", REJECTED_CASE_IDS, ids=repr)
def test_direct_golden_case_construction_applies_the_same_rule(
    tmp_path: Path, case_id: str
) -> None:
    template = load_case(write_case(tmp_path / "case"))
    with pytest.raises(GoldenCaseError, match="case_id must be a stable identifier"):
        GoldenCase(
            case_id=case_id,
            directory=template.directory,
            config_version_identifier=template.config_version_identifier,
            window_profile=template.window_profile,
            snapshot_filename=template.snapshot_filename,
            expected_filename=template.expected_filename,
            snapshot=template.snapshot,
            expected_result=template.expected_result,
        )


def test_blank_config_version_is_rejected(tmp_path: Path) -> None:
    directory = write_case(tmp_path / "case", manifest_overrides={"config_version_identifier": ""})
    with pytest.raises(GoldenCaseError, match="config_version_identifier must be a non-empty"):
        load_case(directory)


def test_invalid_window_profile_is_rejected(tmp_path: Path) -> None:
    directory = write_case(tmp_path / "case", manifest_overrides={"window_profile": "SEASON"})
    with pytest.raises(GoldenCaseError, match="window_profile 'SEASON' is not a valid"):
        load_case(directory)


def test_error_messages_name_the_case_directory(tmp_path: Path) -> None:
    directory = write_case(tmp_path / "named-case", manifest_overrides={"case_id": ""})
    with pytest.raises(GoldenCaseError, match="named-case"):
        load_case(directory)


# --------------------------------------------------------------------------
# Fixture-path rejections
# --------------------------------------------------------------------------


def test_absolute_snapshot_path_is_rejected(tmp_path: Path) -> None:
    absolute = str((tmp_path / "outside.json").resolve())
    (tmp_path / "outside.json").write_bytes(RECENT_SNAPSHOT_BYTES)
    directory = write_case(tmp_path / "case", manifest_overrides={"snapshot_file": absolute})
    with pytest.raises(GoldenCaseError, match="snapshot_file"):
        load_case(directory)


@pytest.mark.parametrize("traversal", ["../input_snapshot.json", "..\\escape.json", ".."])
def test_parent_traversal_is_rejected(tmp_path: Path, traversal: str) -> None:
    (tmp_path / "input_snapshot.json").write_bytes(RECENT_SNAPSHOT_BYTES)
    directory = write_case(tmp_path / "case", manifest_overrides={"snapshot_file": traversal})
    with pytest.raises(GoldenCaseError, match="snapshot_file"):
        load_case(directory)


def test_missing_snapshot_file_is_rejected(tmp_path: Path) -> None:
    directory = write_case(tmp_path / "case", omit_files=frozenset({"input_snapshot.json"}))
    with pytest.raises(GoldenCaseError, match="does not exist as a regular file"):
        load_case(directory)


def test_missing_expected_file_is_rejected(tmp_path: Path) -> None:
    directory = write_case(tmp_path / "case", omit_files=frozenset({"expected_grade_result.json"}))
    with pytest.raises(GoldenCaseError, match="does not exist as a regular file"):
        load_case(directory)


def test_directory_as_fixture_file_is_rejected(tmp_path: Path) -> None:
    directory = write_case(tmp_path / "case", omit_files=frozenset({"input_snapshot.json"}))
    (directory / "input_snapshot.json").mkdir()
    with pytest.raises(GoldenCaseError, match="does not exist as a regular file"):
        load_case(directory)


# --------------------------------------------------------------------------
# Record-content rejections
# --------------------------------------------------------------------------


def test_wrong_record_type_in_snapshot_file_is_rejected(tmp_path: Path) -> None:
    directory = write_case(tmp_path / "case", snapshot_bytes=RECENT_EXPECTED_BYTES)
    with pytest.raises(GoldenCaseError, match=r"snapshot_file.*not a valid canonical"):
        load_case(directory)


def test_wrong_record_type_in_expected_file_is_rejected(tmp_path: Path) -> None:
    directory = write_case(tmp_path / "case", expected_bytes=RECENT_SNAPSHOT_BYTES)
    with pytest.raises(GoldenCaseError, match=r"expected_file.*must hold exactly"):
        load_case(directory)


def test_envelope_as_expected_record_is_rejected(tmp_path: Path) -> None:
    """An EvaluationEnvelope is not a golden output in GM-008."""
    directory = write_case(tmp_path / "case", expected_bytes=ENVELOPE_BYTES)
    with pytest.raises(GoldenCaseError, match=r"expected_file.*must hold exactly"):
        load_case(directory)


def test_tampered_snapshot_identity_is_rejected(tmp_path: Path) -> None:
    """The snapshot decodes through the GM-006 decoder, which verifies identity."""
    parsed = json.loads(RECENT_SNAPSHOT_BYTES.decode("utf-8"))
    stored = parsed["payload"]["snapshot_id"]["value"]
    parsed["payload"]["snapshot_id"]["value"] = stored[:-4] + (
        "0000" if not stored.endswith("0000") else "1111"
    )
    tampered = json.dumps(parsed).encode("utf-8")
    directory = write_case(tmp_path / "case", snapshot_bytes=tampered)
    with pytest.raises(GoldenCaseError, match="snapshot_file"):
        load_case(directory)


def test_manifest_snapshot_profile_mismatch_is_rejected(tmp_path: Path) -> None:
    directory = write_case(
        tmp_path / "case",
        profile="LONG_TERM_2Y",
        snapshot_bytes=RECENT_SNAPSHOT_BYTES,
        expected_bytes=LONG_TERM_EXPECTED_BYTES,
    )
    with pytest.raises(GoldenCaseError, match="snapshot record carries 'RECENT_7D'"):
        load_case(directory)


def test_manifest_result_profile_mismatch_is_rejected(tmp_path: Path) -> None:
    directory = write_case(
        tmp_path / "case",
        profile="RECENT_7D",
        snapshot_bytes=RECENT_SNAPSHOT_BYTES,
        expected_bytes=LONG_TERM_EXPECTED_BYTES,
    )
    with pytest.raises(GoldenCaseError, match="expected result carries 'LONG_TERM_2Y'"):
        load_case(directory)


# --------------------------------------------------------------------------
# Discovery
# --------------------------------------------------------------------------


def test_empty_case_root_returns_an_empty_tuple(tmp_path: Path) -> None:
    root = tmp_path / "cases"
    root.mkdir()
    assert discover_cases(root) == ()


def test_nonexistent_case_root_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(GoldenCaseError, match="does not exist"):
        discover_cases(tmp_path / "no-such-root")


def test_duplicate_case_ids_are_rejected(tmp_path: Path) -> None:
    root = tmp_path / "cases"
    write_case(root / "case-a", case_id="synthetic-duplicate")
    write_case(root / "case-b", case_id="synthetic-duplicate")
    with pytest.raises(GoldenCaseError, match="duplicate golden case_id 'synthetic-duplicate'"):
        discover_cases(root)


def test_partial_case_directory_fails_loudly(tmp_path: Path) -> None:
    root = tmp_path / "cases"
    write_case(root / "complete-case", case_id="synthetic-complete")
    partial = root / "partial-case"
    partial.mkdir()
    (partial / "input_snapshot.json").write_bytes(RECENT_SNAPSHOT_BYTES)
    with pytest.raises(GoldenCaseError, match=f"has no {MANIFEST_FILENAME}"):
        discover_cases(root)


def test_empty_subdirectory_fails_loudly(tmp_path: Path) -> None:
    root = tmp_path / "cases"
    (root / "empty-dir").mkdir(parents=True)
    with pytest.raises(GoldenCaseError, match=f"has no {MANIFEST_FILENAME}"):
        discover_cases(root)


def test_unrelated_plain_files_at_the_root_are_ignored(tmp_path: Path) -> None:
    root = tmp_path / "cases"
    write_case(root / "real-case", case_id="synthetic-real")
    (root / ".gitkeep").write_bytes(b"")
    (root / "notes.txt").write_bytes(b"not a case")
    cases = discover_cases(root)
    assert [case.case_id for case in cases] == ["synthetic-real"]


def test_discovery_orders_by_case_id_not_directory_name(tmp_path: Path) -> None:
    root = tmp_path / "cases"
    write_case(root / "zzz-directory", case_id="synthetic-aaa")
    write_case(root / "aaa-directory", case_id="synthetic-zzz")
    cases = discover_cases(root)
    assert [case.case_id for case in cases] == ["synthetic-aaa", "synthetic-zzz"]


def test_direct_construction_with_mismatched_profile_is_rejected(tmp_path: Path) -> None:
    """GoldenCase validates at runtime even when built directly."""
    case = load_case(write_case(tmp_path / "case"))
    with pytest.raises(GoldenCaseError, match="does not equal the case's declared profile"):
        GoldenCase(
            case_id=case.case_id,
            directory=case.directory,
            config_version_identifier=case.config_version_identifier,
            window_profile=WindowProfile.LONG_TERM_2Y,
            snapshot_filename=case.snapshot_filename,
            expected_filename=case.expected_filename,
            snapshot=case.snapshot,
            expected_result=case.expected_result,
        )
