"""The semantic ``config_hash`` and the source fingerprint.

Two questions, kept apart: :func:`config_hash` answers *did the meaning change?*
and must ignore everything textual; :func:`source_digest` answers *did the file
change?* and must notice a reworded comment. The tests below pin both, plus the
:class:`ConfigHash` value object that carries the first.

Behavior-changing mutations are applied to the *parsed* configuration and reloaded
through the real validator, so every "different hash" case is a configuration that
genuinely loads — never one that would have been rejected before it was hashed.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
import yaml
from config_fixtures import mutate, valid_text

from greenmachine.config import (
    ConfigHash,
    GreenMachineConfig,
    MalformedConfigHashError,
    config_hash,
    load_config_text,
    semantic_projection,
    source_digest,
)

VALID = valid_text()
BASELINE = config_hash(load_config_text(VALID))


# --------------------------------------------------------------------------
# ConfigHash value object
# --------------------------------------------------------------------------


def _digest() -> str:
    return BASELINE.value


def test_a_valid_digest_is_accepted_and_exposed() -> None:
    hexed = "a" * 64
    assert ConfigHash(hexed).value == hexed
    assert str(ConfigHash(hexed)) == hexed


def test_the_constructor_does_not_compute_a_hash() -> None:
    """A ConfigHash can be rebuilt from a stored string with no config present."""
    stored = _digest()
    assert ConfigHash(stored).value == stored


def test_equal_digests_are_equal_and_hash_alike() -> None:
    assert ConfigHash(_digest()) == ConfigHash(_digest())
    assert hash(ConfigHash(_digest())) == hash(ConfigHash(_digest()))


def test_a_config_hash_is_frozen() -> None:
    hashed = ConfigHash(_digest())
    with pytest.raises(Exception):  # noqa: B017 - dataclasses.FrozenInstanceError
        hashed.value = "b" * 64  # type: ignore[misc]


@pytest.mark.parametrize(
    "bad",
    [
        "A" * 64,  # uppercase
        "a" * 63,  # too short
        "a" * 65,  # too long
        "a" * 63 + "g",  # non-hex
        " " + "a" * 63,  # leading space
        "a" * 63 + " ",  # trailing space
        "a" * 63 + "\n",  # trailing newline
        "",  # empty
    ],
)
def test_a_malformed_digest_is_rejected(bad: str) -> None:
    with pytest.raises(MalformedConfigHashError):
        ConfigHash(bad)


@pytest.mark.parametrize("bad", [123, b"a" * 64, None, ["a" * 64]])
def test_a_non_string_digest_is_rejected(bad: object) -> None:
    with pytest.raises(MalformedConfigHashError):
        ConfigHash(bad)  # type: ignore[arg-type]


def test_config_hash_returns_lowercase_hex_of_length_64() -> None:
    value = BASELINE.value
    assert len(value) == 64
    assert value == value.lower()
    assert all(character in "0123456789abcdef" for character in value)


# --------------------------------------------------------------------------
# Semantic projection: which fields participate
# --------------------------------------------------------------------------


def test_the_projection_excludes_the_version_label_and_keeps_everything_else() -> None:
    """The one excluded field is the human label; every other field participates.

    Built by removal, not by an allow-list, so a behavior-affecting field cannot
    be silently dropped when the schema grows.
    """
    projection = semantic_projection(load_config_text(VALID))
    expected = set(GreenMachineConfig.model_fields) - {"model_configuration_version"}

    assert "model_configuration_version" not in projection
    assert set(projection) == expected
    assert expected == {
        "schema_version",
        "specification_version",
        "fuzzy_scoring",
        "allocations",
        "components",
    }


def test_the_projection_carries_nested_behavior_values() -> None:
    projection = semantic_projection(load_config_text(VALID))

    assert projection["allocations"]["total_max_points"] is not None
    assert projection["components"][0]["profiles"][0]["scoring"][0]["buckets"]


def test_the_projection_rejects_a_non_config() -> None:
    with pytest.raises(TypeError):
        semantic_projection({"not": "a config"})  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# config_hash is blind to everything textual (same hash)
# --------------------------------------------------------------------------


def _hash_of(text: str) -> ConfigHash:
    return config_hash(load_config_text(text))


def test_two_separate_loader_calls_agree() -> None:
    assert _hash_of(VALID) == _hash_of(VALID) == BASELINE


def test_an_inserted_comment_does_not_change_the_hash() -> None:
    text = mutate("schema_version: 1", "schema_version: 1  # a note the grader ignores")
    assert _hash_of(text) == BASELINE


def test_reindentation_and_key_reordering_do_not_change_the_hash() -> None:
    """A full re-serialization strips comments, reindents, and sorts every key."""
    reserialized = yaml.safe_dump(yaml.safe_load(VALID), sort_keys=True, default_flow_style=False)

    assert reserialized != VALID
    assert _hash_of(reserialized) == BASELINE


def test_reordering_root_mapping_keys_does_not_change_the_hash() -> None:
    document = yaml.safe_load(VALID)
    reversed_root = {key: document[key] for key in reversed(list(document))}

    assert _hash_of(yaml.safe_dump(reversed_root)) == BASELINE


def test_crlf_and_lf_produce_the_same_hash() -> None:
    crlf = VALID.replace("\n", "\r\n")

    assert "\r\n" in crlf
    assert _hash_of(crlf) == BASELINE


@pytest.mark.parametrize("respelled", ['"12.0"', '"12.00"', '"12.000"'])
def test_equivalent_decimal_spellings_produce_the_same_hash(respelled: str) -> None:
    text = mutate('total_max_points: "12"', f"total_max_points: {respelled}")

    assert _hash_of(text) == BASELINE


def test_a_different_version_label_with_identical_rules_shares_the_hash() -> None:
    text = mutate(
        'model_configuration_version: "synthetic-fixture-0"',
        'model_configuration_version: "a-completely-different-label-1"',
    )

    assert _hash_of(text) == BASELINE


# --------------------------------------------------------------------------
# config_hash changes on any behavior-affecting change (different hash)
# --------------------------------------------------------------------------


def _reload(data: dict[str, object]) -> GreenMachineConfig:
    """Re-serialize a mutated projection and load it through the real validator."""
    return load_config_text(yaml.safe_dump(data))


def _category(data: dict, name: str) -> dict:
    return next(c for c in data["allocations"]["categories"] if c["category"] == name)


def _component(data: dict, component_id: str) -> dict:
    return next(c for c in data["components"] if c["component_id"] == component_id)


def _profile(component: dict, window: str) -> dict:
    return next(p for p in component["profiles"] if p["window_profile"] == window)


def _bucket_threshold(data: dict) -> None:
    profile = _profile(_component(data, "exit_velocity"), "RECENT_7D")
    buckets = profile["scoring"][0]["buckets"]
    buckets[0]["upper"] = "63.4"
    buckets[1]["lower"] = "63.4"


def _bucket_points(data: dict) -> None:
    profile = _profile(_component(data, "exit_velocity"), "RECENT_7D")
    profile["scoring"][0]["buckets"][1]["points"] = "0.5"


def _component_allocation(data: dict) -> None:
    # Swap two component maxima within one category (its total stays 2.7), moving
    # each strongest bucket to match — a genuine reallocation among components.
    barrel, hard_hit = _component(data, "barrel_pct"), _component(data, "hard_hit_pct")
    barrel["max_points"], hard_hit["max_points"] = "0.7", "1.1"
    for profile in barrel["profiles"]:
        profile["scoring"][0]["buckets"][-1]["points"] = "0.7"
    for profile in hard_hit["profiles"]:
        profile["scoring"][0]["buckets"][-1]["points"] = "1.1"


def _category_maximum(data: dict) -> None:
    # Move 0.1 from pull_power to environment, keeping the total at 12 and each
    # category's component sum consistent.
    _category(data, "pull_power")["max_points"] = "2.3"
    _category(data, "environment")["max_points"] = "1.8"
    pull = _component(data, "pull_pct_air_balls")
    pull["max_points"] = "2.3"
    for profile in pull["profiles"]:
        profile["scoring"][0]["buckets"][-1]["points"] = "2.3"
    weather = _component(data, "weather")
    weather["max_points"] = "0.9"
    for profile in weather["profiles"]:
        profile["scoring"][0]["qualified_points"] = "0.9"


def _grade_cutoff(data: dict) -> None:
    cutoffs = data["allocations"]["grade_cutoffs"]
    cutoffs[0]["upper"] = "3.4"  # D upper
    cutoffs[1]["lower"] = "3.4"  # C lower


def _minimum_sample(data: dict) -> None:
    _profile(_component(data, "exit_velocity"), "RECENT_7D")["minimum_sample_required"] = 4


def _missing_data_policy(data: dict) -> None:
    _component(data, "exit_velocity")["missing_data"]["policy"] = "record_missing"


def _profile_applicability(data: dict) -> None:
    park = _component(data, "park")
    park["applicable_profiles"] = ["RECENT_7D"]
    park["profiles"] = [p for p in park["profiles"] if p["window_profile"] == "RECENT_7D"]


def _direction(data: dict) -> None:
    # Direction cannot change in isolation: reversing it requires the bucket
    # points to follow, or monotonicity would fail. Both change together, and the
    # hash must move.
    exit_velocity = _component(data, "exit_velocity")
    exit_velocity["direction"] = "lower_is_better"
    for profile in exit_velocity["profiles"]:
        buckets = profile["scoring"][0]["buckets"]
        points = [bucket["points"] for bucket in buckets]
        for bucket, point in zip(buckets, reversed(points), strict=True):
            bucket["points"] = point


def _measurement_definition(data: dict) -> None:
    # A boundary inside attack_angle_quality's proxy-measurement bucket set only.
    profile = _profile(_component(data, "attack_angle_quality"), "RECENT_7D")
    proxy = next(
        d for d in profile["scoring"] if d.get("measurement_id") == "attack_angle_threshold_proxy"
    )
    proxy["buckets"][0]["upper"] = "13.6"
    proxy["buckets"][1]["lower"] = "13.6"


CHANGE_FAMILIES: dict[str, Callable[[dict], None]] = {
    "bucket_threshold": _bucket_threshold,
    "bucket_points": _bucket_points,
    "component_allocation": _component_allocation,
    "category_maximum": _category_maximum,
    "grade_cutoff": _grade_cutoff,
    "minimum_sample_requirement": _minimum_sample,
    "missing_data_policy": _missing_data_policy,
    "profile_applicability": _profile_applicability,
    "direction": _direction,
    "measurement_definition": _measurement_definition,
}


@pytest.mark.parametrize("family", sorted(CHANGE_FAMILIES), ids=sorted(CHANGE_FAMILIES))
def test_a_single_behavior_change_moves_the_hash(family: str) -> None:
    data = load_config_text(VALID).model_dump(mode="json")
    CHANGE_FAMILIES[family](data)

    # Reloading proves the mutation is still a *valid* configuration, so the hash
    # change is the reason, not a load failure.
    changed = config_hash(_reload(data))

    assert changed != BASELINE, f"{family} did not change config_hash"


def test_the_baseline_mutation_harness_round_trips_unchanged() -> None:
    """Guard: an unmutated round-trip must reproduce the baseline hash, so a
    'different hash' above is the mutation's doing and not the harness's."""
    data = load_config_text(VALID).model_dump(mode="json")

    assert config_hash(_reload(data)) == BASELINE


# --------------------------------------------------------------------------
# source_digest: the file fingerprint, deliberately not the semantic hash
# --------------------------------------------------------------------------


def test_source_digest_is_lowercase_hex_of_length_64() -> None:
    digest = source_digest(VALID)
    assert len(digest) == 64
    assert digest == digest.lower()


def test_source_digest_is_newline_normalized() -> None:
    lf = source_digest(VALID)
    crlf = source_digest(VALID.replace("\n", "\r\n"))
    cr = source_digest(VALID.replace("\n", "\r"))

    assert lf == crlf == cr


def test_source_digest_moves_when_a_comment_changes() -> None:
    commented = mutate("schema_version: 1", "schema_version: 1  # note")

    assert source_digest(commented) != source_digest(VALID)
    # ...while the semantic hash does not.
    assert _hash_of(commented) == BASELINE


def test_source_digest_rejects_non_text() -> None:
    with pytest.raises(TypeError):
        source_digest(b"bytes")  # type: ignore[arg-type]
