"""The immutable enumerated vocabulary shared by the specification and the code.

Every member's ``value`` is the exact identifier used in ``GLOSSARY.md`` and
``MODEL_SPEC.md`` (a drift test enforces the match), so the ``value`` doubles as
the canonical serialized form. Members are plain :class:`enum.Enum` values, not
bare strings: a :class:`WindowProfile` is not interchangeable with ``"RECENT_7D"``,
which lets the type checker catch a raw string used where an enum belongs.

No enum here carries a threshold, allocation, or sample minimum — those are
configuration (``MODEL_SPEC.md`` §3, §19). These are names only.
"""

from __future__ import annotations

from enum import Enum

__all__ = [
    "AcquisitionMethod",
    "Category",
    "ComponentId",
    "CoverageStatus",
    "EvaluationStatus",
    "Grade",
    "MeasurementId",
    "MissingReason",
    "PitcherRole",
    "ProviderId",
    "SampleStatus",
    "SampleType",
    "Signal",
    "ValidationInputId",
    "WindowProfile",
]


class WindowProfile(Enum):
    """A selectable evaluation window. Profiles are separate evaluations, never
    blended (``MODEL_SPEC.md`` §6). One snapshot carries exactly one profile."""

    RECENT_7D = "RECENT_7D"
    LONG_TERM_2Y = "LONG_TERM_2Y"

    @property
    def display_name(self) -> str:
        """Human-facing label defined in ``MODEL_SPEC.md`` §6.1."""
        return _WINDOW_PROFILE_DISPLAY_NAMES[self]


_WINDOW_PROFILE_DISPLAY_NAMES: dict[WindowProfile, str] = {
    WindowProfile.RECENT_7D: "Recent — Last 7 Days",
    WindowProfile.LONG_TERM_2Y: "Long-Term — Rolling 2 Years",
}


class Category(Enum):
    """The five scored categories (``MODEL_SPEC.md`` §2).

    Category *maximums* are configuration, not attributes of this enum; this is an
    identity only. The mapping of components to categories is also configuration
    (``MODEL_SPEC.md`` §19, invariant 14), so a :class:`ComponentId` deliberately
    does not know its category.
    """

    POWER_PROFILE = "power_profile"
    PITCHER_MATCHUP = "pitcher_matchup"
    FORM = "form"
    PULL_POWER = "pull_power"
    ENVIRONMENT = "environment"

    @property
    def display_name(self) -> str:
        """Human-facing label defined in ``MODEL_SPEC.md`` §2."""
        return _CATEGORY_DISPLAY_NAMES[self]


_CATEGORY_DISPLAY_NAMES: dict[Category, str] = {
    Category.POWER_PROFILE: "Power Profile",
    Category.PITCHER_MATCHUP: "Pitcher Matchup",
    Category.FORM: "Form",
    Category.PULL_POWER: "Pull Power",
    Category.ENVIRONMENT: "Environment",
}


class ComponentId(Enum):
    """The eleven scored components (``MODEL_SPEC.md`` §2, ``GLOSSARY.md`` §1).

    The retired Form metrics — Chase Rate, Zone Contact %, Whiff Rate — are
    deliberately absent and must never be reintroduced. ``attack_angle_quality``
    is the scored component; its two Savant/proxy *measurements* live in
    :class:`MeasurementId`, never here.
    """

    EXIT_VELOCITY = "exit_velocity"
    BARREL_PCT = "barrel_pct"
    HARD_HIT_PCT = "hard_hit_pct"
    PITCH_MIX_PRESSURE = "pitch_mix_pressure"
    PUT_AWAY_PITCH_EXPLOITATION = "put_away_pitch_exploitation"
    SWEET_SPOT_PCT = "sweet_spot_pct"
    ATTACK_ANGLE_QUALITY = "attack_angle_quality"
    BAT_SPEED = "bat_speed"
    PULL_PCT_AIR_BALLS = "pull_pct_air_balls"
    PARK = "park"
    WEATHER = "weather"


class MeasurementId(Enum):
    """The mutually exclusive measurements of ``attack_angle_quality``.

    Exactly one may satisfy the component in a given evaluation (``MODEL_SPEC.md``
    §9.1). These are the only measurement identifiers in the model: every other
    component has a single implicit measurement identical to the component itself
    (``GLOSSARY.md`` terminology note), represented by ``measurement_id=None``.
    """

    IDEAL_ATTACK_ANGLE_PCT = "ideal_attack_angle_pct"
    ATTACK_ANGLE_THRESHOLD_PROXY = "attack_angle_threshold_proxy"


class ValidationInputId(Enum):
    """Advisory Validation Layer inputs (``GLOSSARY.md`` §2, ``MODEL_SPEC.md`` §17).

    Enumerated separately from :class:`ComponentId` because these award zero
    points and can never influence the score, grade, or signal.
    """

    WOBA_WINDOW = "woba_window"
    RELIEF_VULNERABILITY = "relief_vulnerability"
    BULLPEN_NOTES = "bullpen_notes"
    SAMPLE_WARNINGS = "sample_warnings"
    COVERAGE_WARNINGS = "coverage_warnings"
    FALLBACK_STATUS = "fallback_status"


class SampleType(Enum):
    """The true denominator a component's sample is counted over (``MODEL_SPEC.md``
    §8.1). A single generic sample count is never shared across components."""

    BATTED_BALL_EVENTS = "batted_ball_events"
    SWINGS = "swings"
    AIR_BALLS = "air_balls"
    PLATE_APPEARANCES = "plate_appearances"
    PITCHES = "pitches"
    GAMES = "games"


class SampleStatus(Enum):
    """Whether a *present* value met its configured minimum sample (``MODEL_SPEC.md``
    §8.2). Distinct from :class:`MissingReason`: an ``INSUFFICIENT`` value is still
    scored, and ``INSUFFICIENT`` is never a missing reason."""

    SUFFICIENT = "SUFFICIENT"
    INSUFFICIENT = "INSUFFICIENT"


class MissingReason(Enum):
    """Why a required value is absent (``MODEL_SPEC.md`` §8.2, ``GLOSSARY.md`` §5).

    Note there is deliberately no insufficient-sample member: insufficiency is a
    :class:`SampleStatus`, not a reason a value is missing.
    """

    NO_EVENTS_IN_WINDOW = "NO_EVENTS_IN_WINDOW"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    TRACKING_UNAVAILABLE = "TRACKING_UNAVAILABLE"
    PLAYER_NOT_COVERED = "PLAYER_NOT_COVERED"
    INVALID_SOURCE_VALUE = "INVALID_SOURCE_VALUE"
    EXPECTED_PITCHER_UNKNOWN = "EXPECTED_PITCHER_UNKNOWN"
    WEATHER_UNAVAILABLE = "WEATHER_UNAVAILABLE"
    UNSUPPORTED_HISTORICAL_PERIOD = "UNSUPPORTED_HISTORICAL_PERIOD"


class ProviderId(Enum):
    """Stable data-provider identifier carried in core and stored records
    (``MODEL_SPEC.md`` §10). Only providers named in the approved documentation
    are defined; more are added as they are approved."""

    BASEBALL_SAVANT = "baseball_savant"


class AcquisitionMethod(Enum):
    """How a value was obtained, in nominal priority order (``MODEL_SPEC.md`` §9.4).

    Priority is subordinate to point-in-time eligibility (§11.2), so the resolved
    method is not always the highest-priority one. Unavailability is *not* a
    member here — that is a :class:`MissingReason`.
    """

    DIRECT_AGGREGATE = "direct_aggregate"
    STRUCTURED_EXTRACT = "structured_extract"
    RENDERED_SCRAPE = "rendered_scrape"
    EVENT_DERIVED = "event_derived"
    CONFIGURED_PROXY = "configured_proxy"


class PitcherRole(Enum):
    """How the evaluated pitcher was known at snapshot time (``MODEL_SPEC.md``
    §7.1). Bullpen games record ``OPENER`` or ``UNCERTAIN``."""

    OPENER = "opener"
    EXPECTED_STARTER = "expected_starter"
    UNCERTAIN = "uncertain"


class EvaluationStatus(Enum):
    """Terminal status of an evaluation (``MODEL_SPEC.md`` §15). ``NOT_EVALUABLE``
    is not a grade and carries no manufactured score."""

    EVALUATED = "EVALUATED"
    NOT_EVALUABLE = "NOT_EVALUABLE"


class Grade(Enum):
    """Letter grade assigned from the internal Decimal score (``MODEL_SPEC.md``
    §14). The score intervals live in configuration, not on this enum."""

    S = "S"
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class Signal(Enum):
    """Betting signal resolved in strict priority order (``MODEL_SPEC.md`` §16).

    **Members are declared in evaluation-priority order: AVOID, STRONG_BET, LEAN,
    PASS.** ``AVOID`` is evaluated first and the first match wins, so a high grade
    can still resolve to ``AVOID`` with an override reason (§16.1, Q27). Declaring
    them in any other order invites a reader to infer the wrong precedence.

    Declaration order is vocabulary, not behaviour: signal resolution itself is
    Sprint 2.
    """

    AVOID = "AVOID"
    STRONG_BET = "STRONG_BET"
    LEAN = "LEAN"
    PASS = "PASS"


class CoverageStatus(Enum):
    """How completely the requested window was actually covered (``MODEL_SPEC.md``
    §11.1). Partial coverage must stay visible and is never presented as complete."""

    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    NONE = "NONE"
