"""Versioned records, the read-only registry, and the modified-after-use seal.

The registry resolves versions by identifier and refuses to guess between two
records that claim the same one. The seal reloads a used configuration's source
and reports exactly how it has diverged — a changed meaning, a swapped label, an
edited comment, or a source that has gone missing — without ever rewriting the
seal or the file.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
from config_fixtures import valid_text

from greenmachine.config import (
    ConfigHash,
    ConfigParseError,
    ConfigSchemaError,
    ConfigurationUseSeal,
    ConfigurationVersionRegistry,
    ConfigVersionError,
    ConflictingConfigVersionError,
    DuplicateConfigVersionError,
    ModifiedAfterUseError,
    SourceModifiedError,
    SourceUnavailableError,
    UnknownConfigVersionError,
    VersionedConfiguration,
    VersionLabelReplacedError,
    config_hash,
    load_versioned_config,
    load_versioned_config_text,
)

VALID = valid_text()
LABEL_LINE = 'model_configuration_version: "synthetic-fixture-0"'
CONFIG = load_versioned_config_text(VALID).configuration
CONFIG_HASH = config_hash(CONFIG)


def absolute(name: str = "config.yaml") -> str:
    """A platform-absolute path string; the file need not exist."""
    return str((Path.cwd() / name).resolve())


def relabel(label: str, text: str = VALID) -> str:
    return text.replace(LABEL_LINE, f'model_configuration_version: "{label}"')


def with_changed_threshold(text: str = VALID) -> str:
    """A valid rule change: move one shared bucket boundary in both neighbours."""
    return text.replace('upper: "62.4", points: "0" }', 'upper: "63.4", points: "0" }').replace(
        'lower: "62.4", upper: "88.1"', 'lower: "63.4", upper: "88.1"'
    )


def write(directory: Path, name: str, text: str, *, newline: str = "\n") -> Path:
    path = directory / name
    path.write_bytes(text.replace("\n", newline).encode("utf-8"))
    return path


# --------------------------------------------------------------------------
# VersionedConfiguration
# --------------------------------------------------------------------------


def test_a_text_load_produces_a_record_with_no_source_path() -> None:
    record = load_versioned_config_text(VALID, file_path="label.yaml")

    assert record.version_identifier == "synthetic-fixture-0"
    assert isinstance(record.config_hash, ConfigHash)
    assert record.configuration.model_configuration_version == "synthetic-fixture-0"
    assert record.source_path is None
    assert record.source_digest is not None


def test_a_file_load_records_its_source(tmp_path: Path) -> None:
    path = write(tmp_path, "config.yaml", VALID)

    record = load_versioned_config(path)

    assert record.source_path is not None
    assert Path(record.source_path).is_absolute()
    assert Path(record.source_path) == path.resolve()
    assert record.source_digest is not None
    assert record.config_hash == load_versioned_config_text(VALID).config_hash


def test_a_versioned_record_is_frozen_and_hashable() -> None:
    record = load_versioned_config_text(VALID)

    assert isinstance(hash(record), int)
    with pytest.raises(dataclasses.FrozenInstanceError):
        record.version_identifier = "x"  # type: ignore[misc]


def test_two_text_loads_of_the_same_bytes_are_equal() -> None:
    assert load_versioned_config_text(VALID) == load_versioned_config_text(VALID)


def test_a_blank_version_identifier_is_refused() -> None:
    """Defends the record even if a blank label somehow bypassed the loader."""
    config = load_versioned_config_text(VALID).configuration
    with pytest.raises(ConfigVersionError):
        VersionedConfiguration(
            version_identifier="   ",
            config_hash=ConfigHash("a" * 64),
            configuration=config,
        )


def test_a_non_confighash_is_refused() -> None:
    config = load_versioned_config_text(VALID).configuration
    with pytest.raises(ConfigVersionError):
        VersionedConfiguration(
            version_identifier="v1",
            config_hash="a" * 64,  # type: ignore[arg-type]
            configuration=config,
        )


def test_gm003_errors_propagate_from_a_versioned_text_load() -> None:
    broken = VALID.replace("schema_version: 1", "schema_version: 1\nsurprise: nope")
    with pytest.raises(ConfigSchemaError):
        load_versioned_config_text(broken, file_path="x.yaml")


@pytest.mark.parametrize("bad_path", [123, object()])
def test_a_bad_path_type_is_a_parse_error(bad_path: object) -> None:
    with pytest.raises(ConfigParseError, match=r"path must be a str or path-like"):
        load_versioned_config(bad_path)  # type: ignore[arg-type]


def test_a_missing_file_is_a_parse_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigParseError):
        load_versioned_config(tmp_path / "does-not-exist.yaml")


# --------------------------------------------------------------------------
# ConfigurationVersionRegistry
# --------------------------------------------------------------------------


def test_one_version_resolves() -> None:
    record = load_versioned_config_text(VALID)
    registry = ConfigurationVersionRegistry.from_versioned([record])

    assert registry.resolve("synthetic-fixture-0") is record
    assert "synthetic-fixture-0" in registry
    assert len(registry) == 1


def test_multiple_versions_coexist_independently() -> None:
    one = load_versioned_config_text(relabel("alpha"))
    two = load_versioned_config_text(relabel("beta", with_changed_threshold()))
    registry = ConfigurationVersionRegistry.from_versioned([one, two])

    assert registry.resolve("alpha") is one
    assert registry.resolve("beta") is two
    assert registry.resolve("alpha").config_hash != registry.resolve("beta").config_hash


def test_identifier_listing_is_sorted_and_deterministic() -> None:
    records = [load_versioned_config_text(relabel(name)) for name in ("gamma", "alpha", "beta")]
    registry = ConfigurationVersionRegistry.from_versioned(records)

    assert registry.identifiers() == ("alpha", "beta", "gamma")


def test_an_unknown_identifier_raises_the_typed_error() -> None:
    registry = ConfigurationVersionRegistry.from_versioned(
        [load_versioned_config_text(relabel("a"))]
    )

    with pytest.raises(UnknownConfigVersionError) as caught:
        registry.resolve("missing")

    assert caught.value.context.subject == "missing"
    assert "a" in str(caught.value)  # the known identifier is reported
    assert caught.value.__cause__ is None  # translated, not a wrapped KeyError


def test_a_duplicate_identifier_is_rejected() -> None:
    record = load_versioned_config_text(relabel("dup"))
    with pytest.raises(DuplicateConfigVersionError):
        ConfigurationVersionRegistry.from_versioned([record, record])


def test_a_reused_identifier_with_different_rules_is_a_conflict() -> None:
    same_label_a = load_versioned_config_text(relabel("shared"))
    same_label_b = load_versioned_config_text(relabel("shared", with_changed_threshold()))

    with pytest.raises(ConflictingConfigVersionError) as caught:
        ConfigurationVersionRegistry.from_versioned([same_label_a, same_label_b])

    assert isinstance(caught.value, DuplicateConfigVersionError)  # the specific kind of duplicate
    assert caught.value.context.expected != caught.value.context.observed


def test_identical_rules_under_different_labels_are_allowed_and_share_the_hash() -> None:
    one = load_versioned_config_text(relabel("label-one"))
    two = load_versioned_config_text(relabel("label-two"))
    registry = ConfigurationVersionRegistry.from_versioned([one, two])

    assert registry.identifiers() == ("label-one", "label-two")
    assert registry.resolve("label-one").config_hash == registry.resolve("label-two").config_hash


def test_the_registry_is_immutable() -> None:
    registry = ConfigurationVersionRegistry.from_versioned([load_versioned_config_text(VALID)])

    with pytest.raises(AttributeError):
        registry._by_identifier = {}  # type: ignore[misc]
    with pytest.raises(AttributeError):
        del registry._by_identifier  # type: ignore[misc]
    with pytest.raises(TypeError):
        registry._by_identifier["x"] = 1  # type: ignore[index]


def test_a_non_utf8_file_is_a_parse_error(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_bytes(b"\xff\xfe not valid utf-8 \x80\x81")

    with pytest.raises(ConfigParseError, match=r"UTF-8"):
        load_versioned_config(path)


def test_from_paths_loads_each_file(tmp_path: Path) -> None:
    first = write(tmp_path, "a.yaml", relabel("from-a"))
    second = write(tmp_path, "b.yaml", relabel("from-b"))

    registry = ConfigurationVersionRegistry.from_paths([first, second])

    assert registry.identifiers() == ("from-a", "from-b")
    assert registry.resolve("from-a").source_path == str(first.resolve())


def test_an_empty_registry_is_coherent() -> None:
    registry = ConfigurationVersionRegistry.from_versioned([])

    assert registry.identifiers() == ()
    assert len(registry) == 0
    with pytest.raises(UnknownConfigVersionError):
        registry.resolve("anything")


# --------------------------------------------------------------------------
# ConfigurationUseSeal
# --------------------------------------------------------------------------


def sealed(tmp_path: Path, text: str = VALID, name: str = "config.yaml") -> ConfigurationUseSeal:
    record = load_versioned_config(write(tmp_path, name, text))
    return ConfigurationUseSeal.over(record)


def test_an_unchanged_file_verifies(tmp_path: Path) -> None:
    seal = sealed(tmp_path)

    reloaded = seal.verify_unchanged()

    assert reloaded.config_hash == seal.config_hash


def test_a_seal_is_frozen_and_hashable(tmp_path: Path) -> None:
    seal = sealed(tmp_path)

    assert isinstance(hash(seal), int)
    with pytest.raises(dataclasses.FrozenInstanceError):
        seal.version_identifier = "x"  # type: ignore[misc]


def test_a_threshold_change_is_a_semantic_modification(tmp_path: Path) -> None:
    seal = sealed(tmp_path)
    write(tmp_path, "config.yaml", with_changed_threshold())

    with pytest.raises(ModifiedAfterUseError) as caught:
        seal.verify_unchanged()

    assert caught.value.context.expected != caught.value.context.observed


def test_a_replaced_label_is_reported_specifically(tmp_path: Path) -> None:
    seal = sealed(tmp_path)
    write(tmp_path, "config.yaml", relabel("a-new-label"))

    with pytest.raises(VersionLabelReplacedError) as caught:
        seal.verify_unchanged()

    assert caught.value.context.observed == "a-new-label"


def test_a_comment_only_edit_is_a_source_modification(tmp_path: Path) -> None:
    seal = sealed(tmp_path)
    write(tmp_path, "config.yaml", VALID.replace("schema_version: 1", "schema_version: 1  # note"))

    with pytest.raises(SourceModifiedError) as caught:
        seal.verify_unchanged()

    # The meaning is intact; only the fingerprint moved.
    assert caught.value.context.expected != caught.value.context.observed


def test_crlf_rewrite_is_not_a_false_modification(tmp_path: Path) -> None:
    seal = sealed(tmp_path)
    write(tmp_path, "config.yaml", VALID, newline="\r\n")

    reloaded = seal.verify_unchanged()

    assert reloaded.config_hash == seal.config_hash


def test_a_deleted_file_is_source_unavailable(tmp_path: Path) -> None:
    seal = sealed(tmp_path)
    (tmp_path / "config.yaml").unlink()

    with pytest.raises(SourceUnavailableError):
        seal.verify_unchanged()


def test_a_source_that_becomes_non_utf8_is_source_unavailable(tmp_path: Path) -> None:
    seal = sealed(tmp_path)
    (tmp_path / "config.yaml").write_bytes(b"\xff\xfe\x80")

    with pytest.raises(SourceUnavailableError, match=r"UTF-8"):
        seal.verify_unchanged()


def test_a_directory_source_is_source_unavailable(tmp_path: Path) -> None:
    record = load_versioned_config(write(tmp_path, "config.yaml", VALID))
    seal = ConfigurationUseSeal(
        version_identifier=record.version_identifier,
        config_hash=record.config_hash,
        source_digest=record.source_digest,
        source_path=str(tmp_path),  # a directory, not a file
    )

    with pytest.raises(SourceUnavailableError):
        seal.verify_unchanged()


def test_a_text_only_seal_reports_verification_unavailable() -> None:
    seal = ConfigurationUseSeal.over(load_versioned_config_text(VALID))

    assert seal.source_path is None
    with pytest.raises(SourceUnavailableError):
        seal.verify_unchanged()


def test_the_seal_is_unchanged_after_a_failed_verification(tmp_path: Path) -> None:
    seal = sealed(tmp_path)
    before = dataclasses.astuple(seal)
    write(tmp_path, "config.yaml", with_changed_threshold())

    with pytest.raises(ModifiedAfterUseError):
        seal.verify_unchanged()

    assert dataclasses.astuple(seal) == before


# --------------------------------------------------------------------------
# r1: identity coherence
# --------------------------------------------------------------------------


def _direct(**overrides: object) -> VersionedConfiguration:
    """Construct a record that is coherent unless an override makes it otherwise."""
    fields: dict[str, object] = {
        "version_identifier": CONFIG.model_configuration_version,
        "config_hash": CONFIG_HASH,
        "configuration": CONFIG,
    }
    fields.update(overrides)
    return VersionedConfiguration(**fields)  # type: ignore[arg-type]


def test_a_coherent_direct_record_is_constructable() -> None:
    record = _direct()

    assert record.version_identifier == CONFIG.model_configuration_version
    assert record.source_path is None
    assert record.source_digest is None


def test_a_semantic_only_record_with_no_source_fields_is_supported() -> None:
    record = _direct()

    assert (record.source_path, record.source_digest) == (None, None)


def test_a_text_backed_record_keeps_a_digest_without_a_path() -> None:
    record = load_versioned_config_text(VALID)

    assert record.source_path is None
    assert record.source_digest is not None


def test_a_mismatched_version_label_is_rejected() -> None:
    with pytest.raises(ConfigVersionError, match=r"does not match") as caught:
        _direct(version_identifier="not-the-real-label")

    assert caught.value.context.expected == CONFIG.model_configuration_version
    assert caught.value.context.observed == "not-the-real-label"


def test_a_mismatched_config_hash_is_rejected() -> None:
    with pytest.raises(ConfigVersionError, match=r"does not describe") as caught:
        _direct(config_hash=ConfigHash("a" * 64))

    assert caught.value.context.expected != caught.value.context.observed


def test_a_non_config_configuration_is_rejected() -> None:
    with pytest.raises(ConfigVersionError, match=r"GreenMachineConfig"):
        _direct(configuration="not a config")


# --------------------------------------------------------------------------
# r1: source-field validation on the record
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source_path", "source_digest", "match"),
    [
        (123, "a" * 64, r"source_path"),
        ("   ", "a" * 64, r"source_path"),
        ("relative/config.yaml", "a" * 64, r"absolute"),
        (absolute(), None, r"requires a source_digest"),
    ],
)
def test_a_malformed_source_field_on_a_record_is_rejected(
    source_path: object, source_digest: object, match: str
) -> None:
    with pytest.raises(ConfigVersionError, match=match):
        _direct(source_path=source_path, source_digest=source_digest)


@pytest.mark.parametrize(
    "bad_digest", ["NOTHEX", "A" * 64, "a" * 63, "a" * 65, "  " + "a" * 62, 123]
)
def test_a_malformed_source_digest_on_a_record_is_rejected(bad_digest: object) -> None:
    with pytest.raises(ConfigVersionError, match=r"source_digest"):
        _direct(source_path=absolute(), source_digest=bad_digest)


# --------------------------------------------------------------------------
# r1: registry input and lookup boundaries
# --------------------------------------------------------------------------


def test_a_non_versioned_registry_member_is_rejected() -> None:
    with pytest.raises(ConfigVersionError, match=r"VersionedConfiguration"):
        ConfigurationVersionRegistry.from_versioned(["not a record"])  # type: ignore[list-item]


@pytest.mark.parametrize("bad", [["a"], {"a": 1}, 5, True, None, "   "])
def test_resolve_rejects_a_non_string_or_blank_identifier(bad: object) -> None:
    registry = ConfigurationVersionRegistry.from_versioned([load_versioned_config_text(VALID)])

    with pytest.raises(ConfigVersionError):
        registry.resolve(bad)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", [["a"], {"a": 1}, 5, object(), None, "   "])
def test_contains_is_false_for_malformed_candidates_without_raising(bad: object) -> None:
    registry = ConfigurationVersionRegistry.from_versioned([load_versioned_config_text(VALID)])

    assert (bad in registry) is False


# --------------------------------------------------------------------------
# r1: seal validation
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"version_identifier": "   ", "config_hash": CONFIG_HASH}, r"non-blank"),
        ({"version_identifier": "v", "config_hash": "a" * 64}, r"ConfigHash"),
        (
            {"version_identifier": "v", "config_hash": CONFIG_HASH, "source_digest": "NOTHEX"},
            r"source_digest",
        ),
        (
            {
                "version_identifier": "v",
                "config_hash": CONFIG_HASH,
                "source_path": "relative.yaml",
                "source_digest": "a" * 64,
            },
            r"absolute",
        ),
        (
            {"version_identifier": "v", "config_hash": CONFIG_HASH, "source_path": absolute()},
            r"requires a source_digest",
        ),
    ],
)
def test_a_malformed_seal_is_rejected(kwargs: dict[str, object], match: str) -> None:
    with pytest.raises(ConfigVersionError, match=match):
        ConfigurationUseSeal(**kwargs)  # type: ignore[arg-type]


def test_over_requires_a_versioned_configuration() -> None:
    with pytest.raises(ConfigVersionError, match=r"VersionedConfiguration"):
        ConfigurationUseSeal.over("not a record")  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# r1: absolute paths make verification working-directory independent
# --------------------------------------------------------------------------


def test_a_relative_load_stores_an_absolute_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write(tmp_path, "config.yaml", VALID)
    monkeypatch.chdir(tmp_path)

    record = load_versioned_config("config.yaml")

    assert record.source_path is not None
    assert Path(record.source_path).is_absolute()
    assert Path(record.source_path) == (tmp_path / "config.yaml").resolve()


def test_a_seal_verifies_after_the_working_directory_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_file = write(tmp_path, "config.yaml", VALID)
    monkeypatch.chdir(tmp_path)
    seal = ConfigurationUseSeal.over(load_versioned_config("config.yaml"))

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    # Unchanged: verifies from a different working directory.
    assert seal.verify_unchanged().config_hash == seal.config_hash

    # A semantic change is still detected after the cwd moved.
    config_file.write_bytes(with_changed_threshold().encode("utf-8"))
    with pytest.raises(ModifiedAfterUseError):
        seal.verify_unchanged()


def test_a_source_only_edit_is_detected_after_the_working_directory_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_file = write(tmp_path, "config.yaml", VALID)
    monkeypatch.chdir(tmp_path)
    seal = ConfigurationUseSeal.over(load_versioned_config("config.yaml"))

    monkeypatch.chdir(tmp_path.parent)
    config_file.write_bytes(
        VALID.replace("schema_version: 1", "schema_version: 1  # note").encode("utf-8")
    )

    with pytest.raises(SourceModifiedError):
        seal.verify_unchanged()
