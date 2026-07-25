"""Provider-neutral ingestion records: the smallest typed layer before domain mapping.

Everything here is immutable, runtime-validated, and provider-neutral: no CSV or
JSON column name from Savant or the MLB Stats API appears on any record — those
stay confined to the parser modules. Numeric measurements are ``Decimal``
(constructed from provider strings, never floats), optionality is explicit, and
every collection is an ordered tuple.

These records deliberately duplicate **nothing** from the frozen domain
contracts: :class:`~greenmachine.domain.InputSnapshot`, ``GameContext``,
``Batter``, ``Pitcher``, and the observation types remain the only home for
those shapes. Nothing here knows about scoring, points, grades, or signals.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import TypeVar

from greenmachine.domain import ComponentId, PitcherRole, WindowProfile

from .errors import IngestionModelError, SamplePolicyError

__all__ = [
    "AttemptOutcome",
    "AttemptRecord",
    "BatterEventRecord",
    "CaptureManifest",
    "CaptureMode",
    "CaptureProvider",
    "EventWindowReport",
    "ExpectedPitcherRecord",
    "GameRecord",
    "IngestionEligibilityResult",
    "PitcherEventRecord",
    "ProviderRequest",
    "RawCaptureEntry",
    "SampleMinimumPolicy",
    "SlateRecord",
]


class CaptureProvider(Enum):
    """Ingestion-level provider identity for raw captures.

    Distinct from the frozen domain ``ProviderId`` (which names the provenance
    of *metric observations*): the MLB Stats API supplies identity and context,
    not metric values, so it exists only at this layer.
    """

    MLB_STATS_API = "mlb_stats_api"
    BASEBALL_SAVANT = "baseball_savant"


class CaptureMode(Enum):
    """Whether a capture is genuine pregame evidence or a reconstruction."""

    PROSPECTIVE = "PROSPECTIVE"
    RETROSPECTIVE_RECONSTRUCTION = "RETROSPECTIVE_RECONSTRUCTION"


class AttemptOutcome(Enum):
    """The outcome of one retrieval attempt."""

    SUCCESS = "SUCCESS"
    RETRYABLE_TRANSPORT_ERROR = "RETRYABLE_TRANSPORT_ERROR"
    RETRYABLE_HTTP_STATUS = "RETRYABLE_HTTP_STATUS"
    FATAL_HTTP_STATUS = "FATAL_HTTP_STATUS"


# The disclaimer wording preserved verbatim for retrospective evidence (ruling 19).
RETROSPECTIVE_DISCLAIMER = (
    "Retrospectively reconstructed from currently available provider data; not a "
    "prospectively archived point-in-time capture."
)

_STABLE_LABEL = re.compile(r"[a-z][a-z0-9_]*")
_SHA256_HEX = re.compile(r"[0-9a-f]{64}")


def _non_blank(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise IngestionModelError(f"{field_name} must be a string, got {type(value).__name__}")
    if not value.strip():
        raise IngestionModelError(f"{field_name} must be a non-empty, non-blank string")
    return value


def _optional_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _non_blank(value, field_name)


def _stable_label(value: object, field_name: str) -> str:
    text = _non_blank(value, field_name)
    if _STABLE_LABEL.fullmatch(text) is None:
        raise IngestionModelError(
            f"{field_name} must be a stable lowercase label matching [a-z][a-z0-9_]*, got {text!r}"
        )
    return text


def _non_negative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise IngestionModelError(f"{field_name} must be an int, got {type(value).__name__}")
    if value < 0:
        raise IngestionModelError(f"{field_name} must be >= 0, got {value}")
    return value


def _positive_int(value: object, field_name: str) -> int:
    number = _non_negative_int(value, field_name)
    if number == 0:
        raise IngestionModelError(f"{field_name} must be >= 1, got 0")
    return number


def _utc_datetime(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise IngestionModelError(f"{field_name} must be a datetime, got {type(value).__name__}")
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        # Normalisation is the caller's job; requiring UTC keeps manifests uniform.
        raise IngestionModelError(f"{field_name} must be a UTC datetime")
    return value


def _plain_date(value: object, field_name: str) -> date:
    if isinstance(value, datetime) or not isinstance(value, date):
        raise IngestionModelError(
            f"{field_name} must be a datetime.date (not a datetime), got {type(value).__name__}"
        )
    return value


def _optional_decimal(value: object, field_name: str) -> Decimal | None:
    if value is None:
        return None
    if not isinstance(value, Decimal):
        raise IngestionModelError(f"{field_name} must be a Decimal, got {type(value).__name__}")
    if not value.is_finite():
        raise IngestionModelError(f"{field_name} must be finite, got {value}")
    return value


def _optional_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    return _non_negative_int(value, field_name)


_T = TypeVar("_T")


def _instance(value: object, expected: type[_T], field_name: str) -> _T:
    if not isinstance(value, expected):
        raise IngestionModelError(
            f"{field_name} must be a {expected.__name__}, got {type(value).__name__}"
        )
    return value


def _tuple_of(value: object, expected: type[_T], field_name: str) -> tuple[_T, ...]:
    if not isinstance(value, tuple):
        raise IngestionModelError(f"{field_name} must be a tuple, got {type(value).__name__}")
    for index, item in enumerate(value):
        _instance(item, expected, f"{field_name}[{index}]")
    return value


def _relative_artifact_path(value: object, field_name: str) -> str:
    text = _non_blank(value, field_name)
    if "\\" in text or text.startswith("/") or ".." in text.split("/") or ":" in text:
        raise IngestionModelError(
            f"{field_name} must be a forward-slash relative path inside the run "
            f"directory, got {text!r}"
        )
    return text


# --------------------------------------------------------------------------
# Requests, attempts, captures, manifest
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    """One canonical provider request: label, endpoint identity, sorted parameters.

    ``parameters`` are the canonical request parameters as an ordered tuple of
    unique ``(key, value)`` string pairs sorted by key — the identity-bearing
    projection, independent of URL encoding details.
    """

    label: str
    provider: CaptureProvider
    endpoint: str
    parameters: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        _stable_label(self.label, "ProviderRequest.label")
        _instance(self.provider, CaptureProvider, "ProviderRequest.provider")
        _stable_label(self.endpoint, "ProviderRequest.endpoint")
        if not isinstance(self.parameters, tuple):
            raise IngestionModelError("ProviderRequest.parameters must be a tuple")
        keys: list[str] = []
        for index, pair in enumerate(self.parameters):
            candidate: object = pair
            if not (isinstance(candidate, tuple) and len(candidate) == 2):
                raise IngestionModelError(
                    f"ProviderRequest.parameters[{index}] must be a (key, value) pair"
                )
            key, value = candidate
            _non_blank(key, f"ProviderRequest.parameters[{index}] key")
            if not isinstance(value, str):
                raise IngestionModelError(
                    f"ProviderRequest.parameters[{index}] value must be a string"
                )
            keys.append(key)
        if keys != sorted(keys):
            raise IngestionModelError("ProviderRequest.parameters must be sorted by key")
        if len(set(keys)) != len(keys):
            raise IngestionModelError("ProviderRequest.parameters must have unique keys")


@dataclass(frozen=True, slots=True)
class AttemptRecord:
    """One retrieval attempt: when it ran, how it ended."""

    index: int
    started_at: datetime
    completed_at: datetime
    outcome: AttemptOutcome
    http_status: int | None
    error_category: str | None

    def __post_init__(self) -> None:
        _positive_int(self.index, "AttemptRecord.index")
        started = _utc_datetime(self.started_at, "AttemptRecord.started_at")
        completed = _utc_datetime(self.completed_at, "AttemptRecord.completed_at")
        if completed < started:
            raise IngestionModelError("AttemptRecord.completed_at must be >= started_at")
        _instance(self.outcome, AttemptOutcome, "AttemptRecord.outcome")
        _optional_int(self.http_status, "AttemptRecord.http_status")
        if self.error_category is not None:
            _stable_label(self.error_category, "AttemptRecord.error_category")
        if self.outcome is AttemptOutcome.SUCCESS and self.error_category is not None:
            raise IngestionModelError(
                "AttemptRecord.error_category must be None on a successful attempt"
            )


@dataclass(frozen=True, slots=True)
class RawCaptureEntry:
    """One archived raw response and everything needed to trust it later."""

    request: ProviderRequest
    capture_mode: CaptureMode
    retrieval_started_at: datetime
    retrieval_completed_at: datetime
    http_status: int
    content_type: str | None
    byte_length: int
    sha256: str
    schema_fingerprint: str
    required_field_contract_version: str
    attempts: tuple[AttemptRecord, ...]
    artifact_relative_path: str
    participates_in_snapshot: bool
    error_category: str | None = None

    def __post_init__(self) -> None:
        _instance(self.request, ProviderRequest, "RawCaptureEntry.request")
        _instance(self.capture_mode, CaptureMode, "RawCaptureEntry.capture_mode")
        started = _utc_datetime(self.retrieval_started_at, "RawCaptureEntry.retrieval_started_at")
        completed = _utc_datetime(
            self.retrieval_completed_at, "RawCaptureEntry.retrieval_completed_at"
        )
        if completed < started:
            raise IngestionModelError(
                "RawCaptureEntry.retrieval_completed_at must be >= retrieval_started_at"
            )
        _non_negative_int(self.http_status, "RawCaptureEntry.http_status")
        _optional_text(self.content_type, "RawCaptureEntry.content_type")
        _non_negative_int(self.byte_length, "RawCaptureEntry.byte_length")
        digest = _non_blank(self.sha256, "RawCaptureEntry.sha256")
        if _SHA256_HEX.fullmatch(digest) is None:
            raise IngestionModelError("RawCaptureEntry.sha256 must be 64 lowercase hex characters")
        _non_blank(self.schema_fingerprint, "RawCaptureEntry.schema_fingerprint")
        _non_blank(
            self.required_field_contract_version,
            "RawCaptureEntry.required_field_contract_version",
        )
        attempts = _tuple_of(self.attempts, AttemptRecord, "RawCaptureEntry.attempts")
        if not attempts:
            raise IngestionModelError("RawCaptureEntry.attempts must not be empty")
        indexes = [attempt.index for attempt in attempts]
        if indexes != sorted(indexes) or len(set(indexes)) != len(indexes):
            raise IngestionModelError(
                "RawCaptureEntry.attempts must be ordered by unique attempt index"
            )
        _relative_artifact_path(
            self.artifact_relative_path, "RawCaptureEntry.artifact_relative_path"
        )
        if not isinstance(self.participates_in_snapshot, bool):
            raise IngestionModelError("RawCaptureEntry.participates_in_snapshot must be a bool")
        if self.error_category is not None:
            _stable_label(self.error_category, "RawCaptureEntry.error_category")


@dataclass(frozen=True, slots=True)
class CaptureManifest:
    """The immutable record of one coordinated capture run."""

    manifest_schema_version: int
    slate_date: date
    game_id: str
    batter_id: str
    capture_mode: CaptureMode
    run_started_at: datetime
    run_completed_at: datetime
    entries: tuple[RawCaptureEntry, ...]

    def __post_init__(self) -> None:
        if self.manifest_schema_version != 1:
            raise IngestionModelError(
                f"CaptureManifest.manifest_schema_version must be 1, got "
                f"{self.manifest_schema_version!r}"
            )
        _plain_date(self.slate_date, "CaptureManifest.slate_date")
        _non_blank(self.game_id, "CaptureManifest.game_id")
        _non_blank(self.batter_id, "CaptureManifest.batter_id")
        _instance(self.capture_mode, CaptureMode, "CaptureManifest.capture_mode")
        started = _utc_datetime(self.run_started_at, "CaptureManifest.run_started_at")
        completed = _utc_datetime(self.run_completed_at, "CaptureManifest.run_completed_at")
        if completed < started:
            raise IngestionModelError("CaptureManifest.run_completed_at must be >= run_started_at")
        entries = _tuple_of(self.entries, RawCaptureEntry, "CaptureManifest.entries")
        if not entries:
            raise IngestionModelError("CaptureManifest.entries must not be empty")
        labels = [entry.request.label for entry in entries]
        if labels != sorted(labels):
            raise IngestionModelError("CaptureManifest.entries must be sorted by label")
        if len(set(labels)) != len(labels):
            raise IngestionModelError("CaptureManifest.entries must have unique labels")

    def entry(self, label: str) -> RawCaptureEntry:
        for candidate in self.entries:
            if candidate.request.label == label:
                return candidate
        raise IngestionModelError(f"CaptureManifest has no entry labelled {label!r}")

    @property
    def participating_entries(self) -> tuple[RawCaptureEntry, ...]:
        return tuple(entry for entry in self.entries if entry.participates_in_snapshot)


# --------------------------------------------------------------------------
# Parsed provider-neutral records
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GameRecord:
    """One scheduled game, provider-neutrally."""

    game_pk: int
    game_type: str
    official_date: date
    scheduled_start_utc: datetime
    status_abstract: str
    status_detailed: str
    home_team_id: int
    away_team_id: int
    venue_id: int
    venue_name: str

    def __post_init__(self) -> None:
        _positive_int(self.game_pk, "GameRecord.game_pk")
        _non_blank(self.game_type, "GameRecord.game_type")
        _plain_date(self.official_date, "GameRecord.official_date")
        _utc_datetime(self.scheduled_start_utc, "GameRecord.scheduled_start_utc")
        _non_blank(self.status_abstract, "GameRecord.status_abstract")
        _non_blank(self.status_detailed, "GameRecord.status_detailed")
        _positive_int(self.home_team_id, "GameRecord.home_team_id")
        _positive_int(self.away_team_id, "GameRecord.away_team_id")
        _positive_int(self.venue_id, "GameRecord.venue_id")
        _non_blank(self.venue_name, "GameRecord.venue_name")


@dataclass(frozen=True, slots=True)
class SlateRecord:
    """All games the provider scheduled for one official slate date."""

    slate_date: date
    games: tuple[GameRecord, ...]

    def __post_init__(self) -> None:
        _plain_date(self.slate_date, "SlateRecord.slate_date")
        games = _tuple_of(self.games, GameRecord, "SlateRecord.games")
        pks = [game.game_pk for game in games]
        if len(set(pks)) != len(pks):
            raise IngestionModelError("SlateRecord.games must have unique game_pk values")

    def game(self, game_pk: int) -> GameRecord:
        for candidate in self.games:
            if candidate.game_pk == game_pk:
                return candidate
        raise IngestionModelError(f"SlateRecord has no game with game_pk {game_pk}")


@dataclass(frozen=True, slots=True)
class ExpectedPitcherRecord:
    """The expected opposing pitcher known at the capture instant."""

    game_pk: int
    pitcher_id: int
    full_name: str
    role: PitcherRole
    batter_team_side: str
    note: str | None

    def __post_init__(self) -> None:
        _positive_int(self.game_pk, "ExpectedPitcherRecord.game_pk")
        _positive_int(self.pitcher_id, "ExpectedPitcherRecord.pitcher_id")
        _non_blank(self.full_name, "ExpectedPitcherRecord.full_name")
        _instance(self.role, PitcherRole, "ExpectedPitcherRecord.role")
        if self.batter_team_side not in ("home", "away"):
            raise IngestionModelError(
                f"ExpectedPitcherRecord.batter_team_side must be 'home' or 'away', got "
                f"{self.batter_team_side!r}"
            )
        _optional_text(self.note, "ExpectedPitcherRecord.note")


@dataclass(frozen=True, slots=True)
class BatterEventRecord:
    """One Statcast pitch-level row for the selected batter, provider-neutrally.

    Optional fields are genuinely optional in the source: ``None`` always means
    the provider supplied no value, never zero.
    """

    game_pk: int
    at_bat_number: int
    pitch_number: int
    game_date: date
    game_type: str | None
    batter_id: int
    pitcher_id: int
    stand: str | None
    bb_type: str | None
    launch_speed: Decimal | None
    launch_angle: Decimal | None
    launch_speed_angle: str | None
    bat_speed: Decimal | None
    attack_angle: Decimal | None
    hit_x: Decimal | None
    hit_y: Decimal | None

    def __post_init__(self) -> None:
        _positive_int(self.game_pk, "BatterEventRecord.game_pk")
        _non_negative_int(self.at_bat_number, "BatterEventRecord.at_bat_number")
        _non_negative_int(self.pitch_number, "BatterEventRecord.pitch_number")
        _plain_date(self.game_date, "BatterEventRecord.game_date")
        _optional_text(self.game_type, "BatterEventRecord.game_type")
        _positive_int(self.batter_id, "BatterEventRecord.batter_id")
        _positive_int(self.pitcher_id, "BatterEventRecord.pitcher_id")
        _optional_text(self.stand, "BatterEventRecord.stand")
        _optional_text(self.bb_type, "BatterEventRecord.bb_type")
        _optional_decimal(self.launch_speed, "BatterEventRecord.launch_speed")
        _optional_decimal(self.launch_angle, "BatterEventRecord.launch_angle")
        _optional_text(self.launch_speed_angle, "BatterEventRecord.launch_speed_angle")
        _optional_decimal(self.bat_speed, "BatterEventRecord.bat_speed")
        _optional_decimal(self.attack_angle, "BatterEventRecord.attack_angle")
        _optional_decimal(self.hit_x, "BatterEventRecord.hit_x")
        _optional_decimal(self.hit_y, "BatterEventRecord.hit_y")

    @property
    def event_key(self) -> tuple[int, int, int]:
        return (self.game_pk, self.at_bat_number, self.pitch_number)


@dataclass(frozen=True, slots=True)
class PitcherEventRecord:
    """One Statcast pitch-level row for the expected pitcher (audit only)."""

    game_pk: int
    at_bat_number: int
    pitch_number: int
    game_date: date
    game_type: str | None
    pitcher_id: int
    stand: str | None
    pitch_type: str | None
    strikes: int | None
    description: str | None
    events: str | None

    def __post_init__(self) -> None:
        _positive_int(self.game_pk, "PitcherEventRecord.game_pk")
        _non_negative_int(self.at_bat_number, "PitcherEventRecord.at_bat_number")
        _non_negative_int(self.pitch_number, "PitcherEventRecord.pitch_number")
        _plain_date(self.game_date, "PitcherEventRecord.game_date")
        _optional_text(self.game_type, "PitcherEventRecord.game_type")
        _positive_int(self.pitcher_id, "PitcherEventRecord.pitcher_id")
        _optional_text(self.stand, "PitcherEventRecord.stand")
        _optional_text(self.pitch_type, "PitcherEventRecord.pitch_type")
        _optional_int(self.strikes, "PitcherEventRecord.strikes")
        _optional_text(self.description, "PitcherEventRecord.description")
        _optional_text(self.events, "PitcherEventRecord.events")

    @property
    def event_key(self) -> tuple[int, int, int]:
        return (self.game_pk, self.at_bat_number, self.pitch_number)


@dataclass(frozen=True, slots=True)
class EventWindowReport:
    """The filtering story for one profile's event set — every exclusion counted."""

    profile: WindowProfile
    window_start: date
    window_end_exclusive: date
    rows_received: int
    duplicates_collapsed: int
    excluded_by_game_type: tuple[tuple[str, int], ...]
    excluded_missing_game_type: int
    excluded_outside_window: int
    excluded_selected_game: int
    rows_eligible: int

    def __post_init__(self) -> None:
        _instance(self.profile, WindowProfile, "EventWindowReport.profile")
        _plain_date(self.window_start, "EventWindowReport.window_start")
        _plain_date(self.window_end_exclusive, "EventWindowReport.window_end_exclusive")
        for name in (
            "rows_received",
            "duplicates_collapsed",
            "excluded_missing_game_type",
            "excluded_outside_window",
            "excluded_selected_game",
            "rows_eligible",
        ):
            _non_negative_int(getattr(self, name), f"EventWindowReport.{name}")
        if not isinstance(self.excluded_by_game_type, tuple):
            raise IngestionModelError("EventWindowReport.excluded_by_game_type must be a tuple")
        types = [game_type for game_type, _ in self.excluded_by_game_type]
        if types != sorted(types) or len(set(types)) != len(types):
            raise IngestionModelError(
                "EventWindowReport.excluded_by_game_type must be sorted and unique by type"
            )
        for game_type, count in self.excluded_by_game_type:
            _non_blank(game_type, "EventWindowReport.excluded_by_game_type type")
            _non_negative_int(count, f"EventWindowReport.excluded_by_game_type[{game_type}]")


@dataclass(frozen=True, slots=True)
class IngestionEligibilityResult:
    """The eligibility decision for one requested slice, with deterministic blockers."""

    eligible: bool
    blockers: tuple[str, ...]
    notes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.eligible, bool):
            raise IngestionModelError("IngestionEligibilityResult.eligible must be a bool")
        for index, blocker in enumerate(self.blockers):
            _non_blank(blocker, f"IngestionEligibilityResult.blockers[{index}]")
        for index, note in enumerate(self.notes):
            _non_blank(note, f"IngestionEligibilityResult.notes[{index}]")
        if self.eligible and self.blockers:
            raise IngestionModelError(
                "IngestionEligibilityResult cannot be eligible with blockers present"
            )
        if not self.eligible and not self.blockers:
            raise IngestionModelError(
                "IngestionEligibilityResult must name at least one blocker when ineligible"
            )


# --------------------------------------------------------------------------
# Sample-minimum policy (Q14 remains open — no defaults live here)
# --------------------------------------------------------------------------

# The components the GM-020 mapper can produce present observations for; the
# policy must cover every one of them under both profiles. There is no hidden
# or module-level default value anywhere: values come only from the caller.
POLICY_COMPONENTS: tuple[ComponentId, ...] = (
    ComponentId.EXIT_VELOCITY,
    ComponentId.BARREL_PCT,
    ComponentId.HARD_HIT_PCT,
    ComponentId.SWEET_SPOT_PCT,
    ComponentId.ATTACK_ANGLE_QUALITY,
    ComponentId.BAT_SPEED,
    ComponentId.PULL_PCT_AIR_BALLS,
)


@dataclass(frozen=True, slots=True)
class SampleMinimumPolicy:
    """An explicit, complete minimum-sample policy supplied by the caller.

    Production minimums are unresolved (Q14): this type carries whatever the
    caller explicitly injects and refuses anything incomplete. ``disclaimer``
    is required so a non-production validation policy states what it is.
    """

    disclaimer: str
    entries: tuple[tuple[ComponentId, WindowProfile, int], ...]

    def __post_init__(self) -> None:
        disclaimer: object = self.disclaimer
        if not isinstance(disclaimer, str) or not disclaimer.strip():
            raise SamplePolicyError(
                "SampleMinimumPolicy.disclaimer must be a non-blank string stating the "
                "policy's provenance and limits"
            )
        if not isinstance(self.entries, tuple):
            raise SamplePolicyError("SampleMinimumPolicy.entries must be a tuple")
        seen: set[tuple[ComponentId, WindowProfile]] = set()
        for index, entry in enumerate(self.entries):
            candidate: object = entry
            if not (isinstance(candidate, tuple) and len(candidate) == 3):
                raise SamplePolicyError(
                    f"SampleMinimumPolicy.entries[{index}] must be "
                    f"(ComponentId, WindowProfile, int)"
                )
            component, profile, minimum = candidate
            if not isinstance(component, ComponentId):
                raise SamplePolicyError(
                    f"SampleMinimumPolicy.entries[{index}] component must be a ComponentId"
                )
            if not isinstance(profile, WindowProfile):
                raise SamplePolicyError(
                    f"SampleMinimumPolicy.entries[{index}] profile must be a WindowProfile"
                )
            if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 0:
                raise SamplePolicyError(
                    f"SampleMinimumPolicy.entries[{index}] minimum must be an int >= 0"
                )
            key = (component, profile)
            if key in seen:
                raise SamplePolicyError(
                    f"SampleMinimumPolicy has a duplicate entry for "
                    f"('{component.value}', '{profile.value}')"
                )
            seen.add(key)
        required = {
            (component, profile) for component in POLICY_COMPONENTS for profile in WindowProfile
        }
        missing = sorted(
            f"('{component.value}', '{profile.value}')" for component, profile in required - seen
        )
        if missing:
            raise SamplePolicyError(
                f"SampleMinimumPolicy is incomplete; missing minimum(s) for: {missing}"
            )

    def minimum_for(self, component: ComponentId, profile: WindowProfile) -> int:
        for entry_component, entry_profile, minimum in self.entries:
            if entry_component is component and entry_profile is profile:
                return minimum
        raise SamplePolicyError(
            f"SampleMinimumPolicy has no entry for ('{component.value}', '{profile.value}')"
        )
