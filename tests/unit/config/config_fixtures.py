"""Helpers for building invalid configurations from the known-good fixture.

Every invalid case is a **one-line diff** from ``complete_synthetic.yaml``. That
keeps the expected key path obvious and stops a hand-written invalid fixture
from drifting out of sync with the schema.

:func:`mutate` asserts the text it is about to replace occurs exactly as many
times as expected. Without that, editing the valid fixture would silently turn a
negative test into one that asserts nothing.
"""

from __future__ import annotations

from pathlib import Path

FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "config"
VALID_DIR = FIXTURE_ROOT / "valid"
INVALID_DIR = FIXTURE_ROOT / "invalid"
VALID_PATH = VALID_DIR / "complete_synthetic.yaml"


def valid_text() -> str:
    """The complete, valid synthetic configuration as text."""
    return VALID_PATH.read_text(encoding="utf-8")


def invalid_path(name: str) -> Path:
    """Path to a standalone invalid-dialect fixture."""
    return INVALID_DIR / name


def mutate(old: str, new: str, *, count: int = 1) -> str:
    """Return the valid fixture with ``old`` replaced by ``new``.

    Raises:
        AssertionError: if ``old`` does not appear exactly ``count`` times, which
            means the valid fixture changed and this negative test would no
            longer be testing what it claims.
    """
    text = valid_text()
    found = text.count(old)
    assert found == count, (
        f"expected {count} occurrence(s) of {old!r} in the valid fixture, found {found}; "
        "the fixture changed and this negative test needs updating"
    )
    return text.replace(old, new)


def drop_line(containing: str) -> str:
    """Return the valid fixture with the single line containing ``containing`` removed."""
    lines = valid_text().splitlines(keepends=True)
    matches = [index for index, line in enumerate(lines) if containing in line]
    assert len(matches) == 1, (
        f"expected exactly one line containing {containing!r}, found {len(matches)}"
    )
    del lines[matches[0]]
    return "".join(lines)


# Anchors into the valid fixture, named so a test reads as intent rather than
# as a string literal.
FUZZY_DISABLED = "  enabled: false"
TOTAL_MAX = '  total_max_points: "12"'
STRONG_FRACTION = '  strong_category_fraction: "0.62"'
POWER_CATEGORY = """    - category: power_profile
      max_points: "2.7"
      components: [exit_velocity, barrel_pct, hard_hit_pct]"""
GRADE_D = '    - { grade: D, lower: "0",   upper: "3.3", terminal: false }'
GRADE_C = '    - { grade: C, lower: "3.3", upper: "5.1", terminal: false }'
GRADE_S = '    - { grade: S, lower: "9.4", upper: "12",  terminal: true }'

# exit_velocity's RECENT_7D bucket set — the workhorse for bucket invariants.
EV_BUCKETS = """              - { lower: "0",    upper: "62.4", points: "0" }
              - { lower: "62.4", upper: "88.1", points: "0.4" }
              - { lower: "88.1", upper: "125",  points: "0.9" }"""

EV_PROFILE_RECENT = """      - window_profile: RECENT_7D
        minimum_sample_required: 3
        scoring:
          - method: bucketed
            domain_min: "0"
            domain_max: "125"
            buckets:
              - { lower: "0",    upper: "62.4", points: "0" }
              - { lower: "62.4", upper: "88.1", points: "0.4" }
              - { lower: "88.1", upper: "125",  points: "0.9" }"""

# put_away_pitch_exploitation's descending bucket set (lower_is_better).
DESCENDING_BUCKETS = """              - { lower: "0",    upper: "19.2", points: "1.9" }
              - { lower: "19.2", upper: "44.6", points: "0.8" }
              - { lower: "44.6", upper: "100",  points: "0" }"""

# attack_angle_quality's RECENT_7D proxy measurement definition.
PROXY_DEFINITION = """          - method: bucketed
            measurement_id: attack_angle_threshold_proxy
            domain_min: "0"
            domain_max: "60"
            buckets:
              - { lower: "0",    upper: "12.6", points: "0" }
              - { lower: "12.6", upper: "33.7", points: "0.35" }
              - { lower: "33.7", upper: "60",   points: "0.8" }"""

WEATHER_BINARY = """          - method: binary
            qualified_points: "0.8"
            predicate:
              all_of:
                - { input_name: synthetic_input_a, operator: at_least, value: "41.7" }
                - { input_name: synthetic_input_b, operator: greater_than, value: "3.9" }"""

AVOID_RULE = """    - priority: 1
      signal: AVOID
      override_reason: synthetic_power_veto"""

PASS_RULE = """    - priority: 4
      signal: PASS
      any_of:
        - all_of:
            - { type: always }"""

ENVIRONMENT_CATEGORY = """    - category: environment
      max_points: "1.7"
      components: [park, weather]"""

# The whole weather component block, so a test can remove the definition while
# leaving (or also removing) the category's reference to it.
WEATHER_COMPONENT = """  - component_id: weather
    scoring_method: binary
    direction: higher_is_better
    max_points: "0.8"
    sample_type: games
    missing_data:
      policy: record_missing
      reasons: [WEATHER_UNAVAILABLE]
    applicable_profiles: [RECENT_7D, LONG_TERM_2Y]
    profiles:
      - window_profile: RECENT_7D
        minimum_sample_required: 1
        scoring:
          - method: binary
            qualified_points: "0.8"
            predicate:
              all_of:
                - { input_name: synthetic_input_a, operator: at_least, value: "41.7" }
                - { input_name: synthetic_input_b, operator: greater_than, value: "3.9" }
      - window_profile: LONG_TERM_2Y
        minimum_sample_required: 1
        scoring:
          - method: binary
            qualified_points: "0.8"
            predicate:
              all_of:
                - { input_name: synthetic_input_a, operator: at_least, value: "41.7" }
                - { input_name: synthetic_input_b, operator: greater_than, value: "3.9" }
"""
