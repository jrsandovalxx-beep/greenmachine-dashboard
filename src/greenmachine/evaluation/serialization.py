"""Content-derived snapshot identity and lossless canonical record serialization.

This module is the domain/evaluation boundary named by ADR-0003: it is where a
frozen :class:`~greenmachine.domain.snapshot.InputSnapshot` acquires its
content-derived identity, and where every GM-006 record is turned into — and
read back from — canonical bytes. It reuses GM-005 verbatim: hashing is
:func:`~greenmachine.common.ids.content_digest` and
:func:`~greenmachine.common.ids.deterministic_id`; encoding is
:func:`~greenmachine.common.serialization.canonical_bytes`. There is no second
canonical encoder and no second SHA-256.

**Identity.** :func:`freeze_input_snapshot` is the supported way to freeze a
snapshot: it canonically serializes the snapshot payload (everything *except* the
identity), computes ``input_hash`` and ``snapshot_id`` from it, and returns a
coherent record. A hand-built snapshot with caller-chosen identity is not
trusted — :func:`verify_snapshot_identity`, called on every decode, recomputes
both and rejects a mismatch with :class:`RecordIntegrityError`.

**Serialization.** Each record is wrapped as ``{record_type, schema_version,
payload}`` and encoded with :func:`canonical_bytes`. Decoding is explicit and
strictly typed: unknown record types, unknown/newer schema versions, unknown or
missing fields, wrong runtime types, and any floating-point number are all
refused, and no raw ``KeyError``/``ValueError``/``JSONDecodeError``/Decimal error
escapes — they become :class:`EvaluationSerializationError`. No filesystem I/O
happens here.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal, DecimalException
from typing import TypeVar

from greenmachine.common.ids import IdentifierError, content_digest, deterministic_id
from greenmachine.common.serialization import (
    CanonicalizationError,
    canonical_bytes,
    parse_canonical_decimal,
)
from greenmachine.domain import (
    AcquisitionMethod,
    AuditEntry,
    Batter,
    BucketHit,
    Category,
    CategoryScore,
    ComponentId,
    ComponentScore,
    CoverageStatus,
    CoverageWindow,
    DataCoverage,
    DomainValidationError,
    EvaluatedGradeResult,
    EvaluationEnvelope,
    EvaluationId,
    FallbackRecord,
    GameContext,
    GameId,
    Grade,
    GradeResult,
    InputSnapshot,
    MeasurementId,
    MethodIneligibility,
    MetricObservation,
    MissingObservation,
    MissingReason,
    NotEvaluableGradeResult,
    OutcomeRecord,
    Pitcher,
    PitcherRole,
    PlayerId,
    ProvenanceEntry,
    ProviderId,
    SampleStatus,
    SampleType,
    Sha256Digest,
    SnapshotId,
    SourceCaptureId,
    UnavailableRequiredInput,
    ValidationFinding,
    ValidationInputId,
    ValidationInputRecord,
    Venue,
    VenueId,
    WindowProfile,
)

# The module-private snapshot construction authority and the shared content
# validator (never re-exported): this module is the one holder, because only its
# two paths can guarantee identity — the factory validates the content and then
# derives the identity from it, and the decode path verifies the stored identity.
from greenmachine.domain.snapshot import (
    _SNAPSHOT_CONSTRUCTION_AUTHORITY,
    _validate_snapshot_content,
)

from .errors import (
    EvaluationSerializationError,
    RecordIntegrityError,
    UnsupportedRecordSchemaVersionError,
)

__all__ = [
    "RECORD_SCHEMA_VERSION",
    "Record",
    "deserialize_envelope",
    "deserialize_evaluated_result",
    "deserialize_not_evaluable_result",
    "deserialize_outcome",
    "deserialize_record",
    "deserialize_snapshot",
    "freeze_input_snapshot",
    "serialize_record",
    "verify_snapshot_identity",
]

# The wrapper schema version for pure records (snapshot, grade results, outcome).
# The envelope carries its own schema_version; the wrapper mirrors it.
RECORD_SCHEMA_VERSION = 1
SUPPORTED_SCHEMA_VERSIONS = frozenset({1})

# The single documented namespace that binds a snapshot id to snapshot content.
_SNAPSHOT_NAMESPACE = "input_snapshot"

# Record-type tags carried in the wrapper.
_SNAPSHOT = "input_snapshot"
_EVALUATED = "evaluated_grade_result"
_NOT_EVALUABLE = "not_evaluable_grade_result"
_ENVELOPE = "evaluation_envelope"
_OUTCOME = "outcome_record"

Record = (
    InputSnapshot
    | EvaluatedGradeResult
    | NotEvaluableGradeResult
    | EvaluationEnvelope
    | OutcomeRecord
)

T = TypeVar("T")


# --------------------------------------------------------------------------
# Snapshot identity (the domain/evaluation boundary)
# --------------------------------------------------------------------------


def _snapshot_identity_payload(
    *,
    source_capture_id: SourceCaptureId,
    game_context: GameContext,
    batter: Batter,
    expected_starting_pitcher: Pitcher,
    pitcher_role: PitcherRole,
    as_of: datetime,
    window_profile: WindowProfile,
    window_start: datetime,
    window_end: datetime,
    present_observations: tuple[MetricObservation, ...],
    missing_observations: tuple[MissingObservation, ...],
    validation_inputs: tuple[ValidationInputRecord, ...],
    weather_is_forecast: bool,
) -> dict[str, object]:
    """The canonical identity payload: every behavior-affecting input, no identity.

    Excludes ``snapshot_id`` and ``input_hash`` by construction — they are derived
    *from* this — and includes everything else the grade depends on. One function
    builds it for both freezing and verifying, so the two can never disagree.
    """
    return {
        "source_capture_id": source_capture_id,
        "game_context": game_context,
        "batter": batter,
        "expected_starting_pitcher": expected_starting_pitcher,
        "pitcher_role": pitcher_role,
        "as_of": as_of,
        "window_profile": window_profile,
        "window_start": window_start,
        "window_end": window_end,
        "present_observations": present_observations,
        "missing_observations": missing_observations,
        "validation_inputs": validation_inputs,
        "weather_is_forecast": weather_is_forecast,
    }


def freeze_input_snapshot(
    *,
    source_capture_id: SourceCaptureId,
    game_context: GameContext,
    batter: Batter,
    expected_starting_pitcher: Pitcher,
    pitcher_role: PitcherRole,
    as_of: datetime,
    window_profile: WindowProfile,
    window_start: datetime,
    window_end: datetime,
    present_observations: tuple[MetricObservation, ...],
    missing_observations: tuple[MissingObservation, ...],
    validation_inputs: tuple[ValidationInputRecord, ...],
    weather_is_forecast: bool,
) -> InputSnapshot:
    """Freeze inputs into an :class:`InputSnapshot` with content-derived identity.

    The supported constructor for a trusted snapshot: it computes both
    ``input_hash`` and ``snapshot_id`` from the canonical payload, so a caller can
    never supply an arbitrary identity pair. Two profile-specific snapshots frozen
    from one source capture share ``source_capture_id`` but differ everywhere the
    window touches, so their payloads — and therefore their identities — differ.

    Every input is structurally validated **before** canonical hashing — through
    the same shared implementation the constructor applies — so a malformed
    payload raises :class:`~greenmachine.domain.DomainValidationError`, never a
    canonicalization error.
    """
    _validate_snapshot_content(
        source_capture_id=source_capture_id,
        game_context=game_context,
        batter=batter,
        expected_starting_pitcher=expected_starting_pitcher,
        pitcher_role=pitcher_role,
        as_of=as_of,
        window_profile=window_profile,
        window_start=window_start,
        window_end=window_end,
        present_observations=present_observations,
        missing_observations=missing_observations,
        validation_inputs=validation_inputs,
        weather_is_forecast=weather_is_forecast,
    )
    payload = _snapshot_identity_payload(
        source_capture_id=source_capture_id,
        game_context=game_context,
        batter=batter,
        expected_starting_pitcher=expected_starting_pitcher,
        pitcher_role=pitcher_role,
        as_of=as_of,
        window_profile=window_profile,
        window_start=window_start,
        window_end=window_end,
        present_observations=present_observations,
        missing_observations=missing_observations,
        validation_inputs=validation_inputs,
        weather_is_forecast=weather_is_forecast,
    )
    input_hash = Sha256Digest(content_digest(payload))
    snapshot_id = SnapshotId(deterministic_id(_SNAPSHOT_NAMESPACE, payload))
    return InputSnapshot(
        snapshot_id=snapshot_id,
        input_hash=input_hash,
        source_capture_id=source_capture_id,
        game_context=game_context,
        batter=batter,
        expected_starting_pitcher=expected_starting_pitcher,
        pitcher_role=pitcher_role,
        as_of=as_of,
        window_profile=window_profile,
        window_start=window_start,
        window_end=window_end,
        present_observations=present_observations,
        missing_observations=missing_observations,
        validation_inputs=validation_inputs,
        weather_is_forecast=weather_is_forecast,
        _authority=_SNAPSHOT_CONSTRUCTION_AUTHORITY,
    )


def verify_snapshot_identity(snapshot: InputSnapshot) -> None:
    """Recompute a snapshot's identity and reject any inconsistency.

    The argument is validated first: a non-:class:`InputSnapshot` raises
    :class:`EvaluationSerializationError` rather than leaking an
    ``AttributeError``. A real snapshot whose stored ``input_hash`` or
    ``snapshot_id`` does not match its content raises
    :class:`RecordIntegrityError` — as does a tampered snapshot whose content
    cannot be canonically serialized at all, with the underlying failure
    preserved as ``__cause__``. A contradictory record is never silently
    repaired.
    """
    candidate: object = snapshot
    if not isinstance(candidate, InputSnapshot):
        raise EvaluationSerializationError(
            f"verify_snapshot_identity expects an InputSnapshot, got {type(candidate).__name__}"
        )
    payload = _snapshot_identity_payload(
        source_capture_id=candidate.source_capture_id,
        game_context=candidate.game_context,
        batter=candidate.batter,
        expected_starting_pitcher=candidate.expected_starting_pitcher,
        pitcher_role=candidate.pitcher_role,
        as_of=candidate.as_of,
        window_profile=candidate.window_profile,
        window_start=candidate.window_start,
        window_end=candidate.window_end,
        present_observations=candidate.present_observations,
        missing_observations=candidate.missing_observations,
        validation_inputs=candidate.validation_inputs,
        weather_is_forecast=candidate.weather_is_forecast,
    )
    try:
        expected_hash = content_digest(payload)
        expected_id = deterministic_id(_SNAPSHOT_NAMESPACE, payload)
    except (CanonicalizationError, IdentifierError) as exc:
        raise RecordIntegrityError(
            f"snapshot content could not be canonically serialized to verify its identity: {exc}"
        ) from exc

    # Widened so the guards stay live at runtime for a forged record: a snapshot
    # built through the authority always carries the right types, but this
    # function's contract is to *never* leak an incidental AttributeError.
    stored_hash: object = candidate.input_hash
    stored_id: object = candidate.snapshot_id
    if not isinstance(stored_hash, Sha256Digest) or not isinstance(stored_id, SnapshotId):
        raise RecordIntegrityError(
            f"snapshot identity fields are not the expected types (input_hash: "
            f"{type(stored_hash).__name__}, snapshot_id: {type(stored_id).__name__})"
        )
    if stored_hash.value != expected_hash:
        raise RecordIntegrityError(
            f"stored input_hash {stored_hash.value!r} does not match the recomputed "
            f"hash {expected_hash!r} of the snapshot content"
        )
    if stored_id.value != expected_id:
        raise RecordIntegrityError(
            f"stored snapshot_id {stored_id.value!r} does not match the recomputed "
            f"id {expected_id!r} of the snapshot content"
        )


# --------------------------------------------------------------------------
# Serialization
# --------------------------------------------------------------------------


def serialize_record(record: Record) -> bytes:
    """Serialize any GM-006 record to canonical UTF-8 JSON bytes.

    Equal records produce byte-identical output. The wrapper carries the record
    type and schema version; for an envelope the wrapper version mirrors
    ``envelope.schema_version``, for the pure records it is
    :data:`RECORD_SCHEMA_VERSION`.

    Dispatch is by **exact type** — an arbitrary subclass of a record contract is
    not a contract this system stores. A snapshot's identity is verified before
    any bytes are written, so a known-invalid snapshot raises
    :class:`RecordIntegrityError` instead of producing a self-invalid record; an
    envelope whose ``schema_version`` this build does not support raises
    :class:`UnsupportedRecordSchemaVersionError` rather than writing bytes this
    build could not read back.
    """
    if type(record) is InputSnapshot:
        verify_snapshot_identity(record)
        return _wrap(_SNAPSHOT, RECORD_SCHEMA_VERSION, record)
    if type(record) is EvaluatedGradeResult:
        return _wrap(_EVALUATED, RECORD_SCHEMA_VERSION, record)
    if type(record) is NotEvaluableGradeResult:
        return _wrap(_NOT_EVALUABLE, RECORD_SCHEMA_VERSION, record)
    if type(record) is EvaluationEnvelope:
        _require_supported(_ENVELOPE, record.schema_version)
        return _wrap(_ENVELOPE, record.schema_version, record)
    if type(record) is OutcomeRecord:
        return _wrap(_OUTCOME, RECORD_SCHEMA_VERSION, record)
    raise EvaluationSerializationError(
        f"cannot serialize {type(record).__name__}; expected exactly one of the GM-006 record types"
    )


def _wrap(record_type: str, schema_version: int, record: object) -> bytes:
    try:
        return canonical_bytes(
            {"record_type": record_type, "schema_version": schema_version, "payload": record}
        )
    except CanonicalizationError as exc:  # pragma: no cover - records are canonical by construction
        raise EvaluationSerializationError(
            f"{record_type} could not be canonically serialized: {exc}"
        ) from exc


# --------------------------------------------------------------------------
# Decoding toolkit
# --------------------------------------------------------------------------


def _reject_float(raw: str) -> float:
    raise EvaluationSerializationError(
        "a floating-point number is not permitted in a canonical record; exact values are "
        "carried as Decimal strings"
    )


def _mapping(value: object, ctx: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise EvaluationSerializationError(
            f"{ctx} must be a JSON object, got {type(value).__name__}"
        )
    return value


def _field(mapping: dict[str, object], key: str, ctx: str) -> object:
    if key not in mapping:
        raise EvaluationSerializationError(f"{ctx} is missing required field {key!r}")
    return mapping[key]


def _reject_unknown(mapping: dict[str, object], allowed: frozenset[str], ctx: str) -> None:
    unknown = sorted(set(mapping) - allowed)
    if unknown:
        raise EvaluationSerializationError(f"{ctx} has unknown field(s): {unknown}")


def _str(value: object, ctx: str) -> str:
    if not isinstance(value, str):
        raise EvaluationSerializationError(f"{ctx} must be a string, got {type(value).__name__}")
    return value


def _bool(value: object, ctx: str) -> bool:
    if not isinstance(value, bool):
        raise EvaluationSerializationError(f"{ctx} must be a boolean, got {type(value).__name__}")
    return value


def _int(value: object, ctx: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise EvaluationSerializationError(f"{ctx} must be an integer, got {type(value).__name__}")
    return value


def _decimal(value: object, ctx: str) -> Decimal:
    text = _str(value, ctx)
    try:
        return parse_canonical_decimal(text)
    except (CanonicalizationError, DecimalException) as exc:
        raise EvaluationSerializationError(f"{ctx} is not a canonical decimal: {text!r}") from exc


def _datetime(value: object, ctx: str) -> datetime:
    text = _str(value, ctx)
    try:
        moment = datetime.fromisoformat(text)
    except ValueError as exc:
        raise EvaluationSerializationError(f"{ctx} is not an ISO-8601 datetime: {text!r}") from exc
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise EvaluationSerializationError(f"{ctx} must be a timezone-aware datetime: {text!r}")
    return moment


def _date(value: object, ctx: str) -> date:
    text = _str(value, ctx)
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise EvaluationSerializationError(f"{ctx} is not an ISO-8601 date: {text!r}") from exc


def _enum(enum_cls: type[T], value: object, ctx: str) -> T:
    text = _str(value, ctx)
    try:
        return enum_cls(text)  # type: ignore[call-arg]
    except ValueError as exc:
        raise EvaluationSerializationError(
            f"{ctx} is not a valid {enum_cls.__name__}: {text!r}"
        ) from exc


def _optional(reader: Callable[[object, str], T], value: object, ctx: str) -> T | None:
    if value is None:
        return None
    return reader(value, ctx)


def _tuple(reader: Callable[[object, str], T], value: object, ctx: str) -> tuple[T, ...]:
    if not isinstance(value, list):
        raise EvaluationSerializationError(
            f"{ctx} must be a JSON array (an ordered sequence), got {type(value).__name__}"
        )
    return tuple(reader(item, f"{ctx}[{index}]") for index, item in enumerate(value))


def _build(factory: Callable[..., T], ctx: str, /, **fields: object) -> T:
    """Construct a domain object, translating its validation error."""
    try:
        return factory(**fields)
    except DomainValidationError as exc:
        raise EvaluationSerializationError(f"{ctx} is not a valid record: {exc}") from exc


def _object(value: object, allowed: frozenset[str], ctx: str) -> dict[str, object]:
    mapping = _mapping(value, ctx)
    _reject_unknown(mapping, allowed, ctx)
    return mapping


# --------------------------------------------------------------------------
# Per-type readers (each mirrors the dataclass's field names exactly)
# --------------------------------------------------------------------------


def _read_wrapper_value(factory: Callable[[str], T], value: object, ctx: str) -> T:
    data = _object(value, frozenset({"value"}), ctx)
    return _build(factory, ctx, value=_str(_field(data, "value", ctx), f"{ctx}.value"))


def _game_id(value: object, ctx: str) -> GameId:
    return _read_wrapper_value(GameId, value, ctx)


def _player_id(value: object, ctx: str) -> PlayerId:
    return _read_wrapper_value(PlayerId, value, ctx)


def _venue_id(value: object, ctx: str) -> VenueId:
    return _read_wrapper_value(VenueId, value, ctx)


def _snapshot_id(value: object, ctx: str) -> SnapshotId:
    return _read_wrapper_value(SnapshotId, value, ctx)


def _source_capture_id(value: object, ctx: str) -> SourceCaptureId:
    return _read_wrapper_value(SourceCaptureId, value, ctx)


def _evaluation_id(value: object, ctx: str) -> EvaluationId:
    return _read_wrapper_value(EvaluationId, value, ctx)


def _sha256(value: object, ctx: str) -> Sha256Digest:
    return _read_wrapper_value(Sha256Digest, value, ctx)


def _venue(value: object, ctx: str) -> Venue:
    data = _object(value, frozenset({"venue_id", "name", "timezone"}), ctx)
    return _build(
        Venue,
        ctx,
        venue_id=_venue_id(_field(data, "venue_id", ctx), f"{ctx}.venue_id"),
        name=_str(_field(data, "name", ctx), f"{ctx}.name"),
        timezone=_str(_field(data, "timezone", ctx), f"{ctx}.timezone"),
    )


def _game_context(value: object, ctx: str) -> GameContext:
    keys = frozenset(
        {"game_id", "slate_date", "scheduled_start_utc", "venue_local_scheduled_time", "venue"}
    )
    data = _object(value, keys, ctx)
    return _build(
        GameContext,
        ctx,
        game_id=_game_id(_field(data, "game_id", ctx), f"{ctx}.game_id"),
        slate_date=_date(_field(data, "slate_date", ctx), f"{ctx}.slate_date"),
        scheduled_start_utc=_datetime(
            _field(data, "scheduled_start_utc", ctx), f"{ctx}.scheduled_start_utc"
        ),
        venue_local_scheduled_time=_datetime(
            _field(data, "venue_local_scheduled_time", ctx), f"{ctx}.venue_local_scheduled_time"
        ),
        venue=_venue(_field(data, "venue", ctx), f"{ctx}.venue"),
    )


def _batter(value: object, ctx: str) -> Batter:
    data = _object(value, frozenset({"player_id", "full_name"}), ctx)
    return _build(
        Batter,
        ctx,
        player_id=_player_id(_field(data, "player_id", ctx), f"{ctx}.player_id"),
        full_name=_str(_field(data, "full_name", ctx), f"{ctx}.full_name"),
    )


def _pitcher(value: object, ctx: str) -> Pitcher:
    data = _object(value, frozenset({"player_id", "full_name", "role"}), ctx)
    return _build(
        Pitcher,
        ctx,
        player_id=_player_id(_field(data, "player_id", ctx), f"{ctx}.player_id"),
        full_name=_str(_field(data, "full_name", ctx), f"{ctx}.full_name"),
        role=_enum(PitcherRole, _field(data, "role", ctx), f"{ctx}.role"),
    )


def _coverage_window(value: object, ctx: str) -> CoverageWindow:
    data = _object(value, frozenset({"start", "end"}), ctx)
    return _build(
        CoverageWindow,
        ctx,
        start=_datetime(_field(data, "start", ctx), f"{ctx}.start"),
        end=_datetime(_field(data, "end", ctx), f"{ctx}.end"),
    )


def _data_coverage(value: object, ctx: str) -> DataCoverage:
    keys = frozenset({"requested", "actual", "status", "source_available", "sample_count"})
    data = _object(value, keys, ctx)
    return _build(
        DataCoverage,
        ctx,
        requested=_coverage_window(_field(data, "requested", ctx), f"{ctx}.requested"),
        actual=_optional(_coverage_window, _field(data, "actual", ctx), f"{ctx}.actual"),
        status=_enum(CoverageStatus, _field(data, "status", ctx), f"{ctx}.status"),
        source_available=_bool(_field(data, "source_available", ctx), f"{ctx}.source_available"),
        sample_count=_int(_field(data, "sample_count", ctx), f"{ctx}.sample_count"),
    )


def _method_ineligibility(value: object, ctx: str) -> MethodIneligibility:
    data = _object(value, frozenset({"method", "reason"}), ctx)
    return _build(
        MethodIneligibility,
        ctx,
        method=_enum(AcquisitionMethod, _field(data, "method", ctx), f"{ctx}.method"),
        reason=_str(_field(data, "reason", ctx), f"{ctx}.reason"),
    )


def _fallback_record(value: object, ctx: str) -> FallbackRecord:
    data = _object(value, frozenset({"selected_method", "higher_priority_ineligible"}), ctx)
    return _build(
        FallbackRecord,
        ctx,
        selected_method=_enum(
            AcquisitionMethod, _field(data, "selected_method", ctx), f"{ctx}.selected_method"
        ),
        higher_priority_ineligible=_tuple(
            _method_ineligibility,
            _field(data, "higher_priority_ineligible", ctx),
            f"{ctx}.higher_priority_ineligible",
        ),
    )


def _metric_observation(value: object, ctx: str) -> MetricObservation:
    keys = frozenset(
        {
            "component_id",
            "measurement_id",
            "window_profile",
            "window_start",
            "window_end",
            "as_of",
            "raw_value",
            "unit",
            "sample_type",
            "sample_count",
            "minimum_sample_required",
            "sample_status",
            "data_coverage",
            "provider_id",
            "acquisition_method",
            "source_as_of",
            "retrieved_at",
            "source_capture_id",
            "fallback_used",
        }
    )
    data = _object(value, keys, ctx)
    return _build(
        MetricObservation,
        ctx,
        component_id=_enum(ComponentId, _field(data, "component_id", ctx), f"{ctx}.component_id"),
        measurement_id=_optional(
            lambda v, c: _enum(MeasurementId, v, c),
            _field(data, "measurement_id", ctx),
            f"{ctx}.measurement_id",
        ),
        window_profile=_enum(
            WindowProfile, _field(data, "window_profile", ctx), f"{ctx}.window_profile"
        ),
        window_start=_datetime(_field(data, "window_start", ctx), f"{ctx}.window_start"),
        window_end=_datetime(_field(data, "window_end", ctx), f"{ctx}.window_end"),
        as_of=_datetime(_field(data, "as_of", ctx), f"{ctx}.as_of"),
        raw_value=_decimal(_field(data, "raw_value", ctx), f"{ctx}.raw_value"),
        unit=_str(_field(data, "unit", ctx), f"{ctx}.unit"),
        sample_type=_enum(SampleType, _field(data, "sample_type", ctx), f"{ctx}.sample_type"),
        sample_count=_int(_field(data, "sample_count", ctx), f"{ctx}.sample_count"),
        minimum_sample_required=_int(
            _field(data, "minimum_sample_required", ctx), f"{ctx}.minimum_sample_required"
        ),
        sample_status=_enum(
            SampleStatus, _field(data, "sample_status", ctx), f"{ctx}.sample_status"
        ),
        data_coverage=_data_coverage(_field(data, "data_coverage", ctx), f"{ctx}.data_coverage"),
        provider_id=_enum(ProviderId, _field(data, "provider_id", ctx), f"{ctx}.provider_id"),
        acquisition_method=_enum(
            AcquisitionMethod, _field(data, "acquisition_method", ctx), f"{ctx}.acquisition_method"
        ),
        source_as_of=_datetime(_field(data, "source_as_of", ctx), f"{ctx}.source_as_of"),
        retrieved_at=_datetime(_field(data, "retrieved_at", ctx), f"{ctx}.retrieved_at"),
        source_capture_id=_source_capture_id(
            _field(data, "source_capture_id", ctx), f"{ctx}.source_capture_id"
        ),
        fallback_used=_optional(
            _fallback_record, _field(data, "fallback_used", ctx), f"{ctx}.fallback_used"
        ),
    )


def _missing_observation(value: object, ctx: str) -> MissingObservation:
    keys = frozenset(
        {
            "component_id",
            "measurement_id",
            "window_profile",
            "window_start",
            "window_end",
            "as_of",
            "sample_type",
            "provider_id",
            "source_capture_id",
            "missing_reason",
            "data_coverage",
        }
    )
    data = _object(value, keys, ctx)
    return _build(
        MissingObservation,
        ctx,
        component_id=_enum(ComponentId, _field(data, "component_id", ctx), f"{ctx}.component_id"),
        measurement_id=_optional(
            lambda v, c: _enum(MeasurementId, v, c),
            _field(data, "measurement_id", ctx),
            f"{ctx}.measurement_id",
        ),
        window_profile=_enum(
            WindowProfile, _field(data, "window_profile", ctx), f"{ctx}.window_profile"
        ),
        window_start=_datetime(_field(data, "window_start", ctx), f"{ctx}.window_start"),
        window_end=_datetime(_field(data, "window_end", ctx), f"{ctx}.window_end"),
        as_of=_datetime(_field(data, "as_of", ctx), f"{ctx}.as_of"),
        sample_type=_enum(SampleType, _field(data, "sample_type", ctx), f"{ctx}.sample_type"),
        provider_id=_optional(
            lambda v, c: _enum(ProviderId, v, c),
            _field(data, "provider_id", ctx),
            f"{ctx}.provider_id",
        ),
        source_capture_id=_source_capture_id(
            _field(data, "source_capture_id", ctx), f"{ctx}.source_capture_id"
        ),
        missing_reason=_enum(
            MissingReason, _field(data, "missing_reason", ctx), f"{ctx}.missing_reason"
        ),
        data_coverage=_data_coverage(_field(data, "data_coverage", ctx), f"{ctx}.data_coverage"),
    )


def _bucket_hit(value: object, ctx: str) -> BucketHit:
    keys = frozenset({"lower_bound", "upper_bound", "is_terminal", "points_awarded"})
    data = _object(value, keys, ctx)
    return _build(
        BucketHit,
        ctx,
        lower_bound=_decimal(_field(data, "lower_bound", ctx), f"{ctx}.lower_bound"),
        upper_bound=_optional(_decimal, _field(data, "upper_bound", ctx), f"{ctx}.upper_bound"),
        is_terminal=_bool(_field(data, "is_terminal", ctx), f"{ctx}.is_terminal"),
        points_awarded=_decimal(_field(data, "points_awarded", ctx), f"{ctx}.points_awarded"),
    )


def _component_score(value: object, ctx: str) -> ComponentScore:
    keys = frozenset({"component_id", "measurement_id", "points_awarded", "bucket_hit"})
    data = _object(value, keys, ctx)
    return _build(
        ComponentScore,
        ctx,
        component_id=_enum(ComponentId, _field(data, "component_id", ctx), f"{ctx}.component_id"),
        measurement_id=_optional(
            lambda v, c: _enum(MeasurementId, v, c),
            _field(data, "measurement_id", ctx),
            f"{ctx}.measurement_id",
        ),
        points_awarded=_decimal(_field(data, "points_awarded", ctx), f"{ctx}.points_awarded"),
        bucket_hit=_optional(_bucket_hit, _field(data, "bucket_hit", ctx), f"{ctx}.bucket_hit"),
    )


def _category_score(value: object, ctx: str) -> CategoryScore:
    keys = frozenset({"category", "points_awarded", "component_scores"})
    data = _object(value, keys, ctx)
    return _build(
        CategoryScore,
        ctx,
        category=_enum(Category, _field(data, "category", ctx), f"{ctx}.category"),
        points_awarded=_decimal(_field(data, "points_awarded", ctx), f"{ctx}.points_awarded"),
        component_scores=_tuple(
            _component_score, _field(data, "component_scores", ctx), f"{ctx}.component_scores"
        ),
    )


def _validation_finding(value: object, ctx: str) -> ValidationFinding:
    data = _object(value, frozenset({"input_id", "message", "component_id"}), ctx)
    return _build(
        ValidationFinding,
        ctx,
        input_id=_enum(ValidationInputId, _field(data, "input_id", ctx), f"{ctx}.input_id"),
        message=_str(_field(data, "message", ctx), f"{ctx}.message"),
        component_id=_optional(
            lambda v, c: _enum(ComponentId, v, c),
            _field(data, "component_id", ctx),
            f"{ctx}.component_id",
        ),
    )


def _validation_input_record(value: object, ctx: str) -> ValidationInputRecord:
    data = _object(value, frozenset({"input_id", "summary", "component_id"}), ctx)
    return _build(
        ValidationInputRecord,
        ctx,
        input_id=_enum(ValidationInputId, _field(data, "input_id", ctx), f"{ctx}.input_id"),
        summary=_str(_field(data, "summary", ctx), f"{ctx}.summary"),
        component_id=_optional(
            lambda v, c: _enum(ComponentId, v, c),
            _field(data, "component_id", ctx),
            f"{ctx}.component_id",
        ),
    )


def _audit_entry(value: object, ctx: str) -> AuditEntry:
    keys = frozenset(
        {
            "sequence",
            "stage",
            "rule_reference",
            "input_summary",
            "output_summary",
            "explanation",
            "component_id",
            "category",
        }
    )
    data = _object(value, keys, ctx)
    return _build(
        AuditEntry,
        ctx,
        sequence=_int(_field(data, "sequence", ctx), f"{ctx}.sequence"),
        stage=_str(_field(data, "stage", ctx), f"{ctx}.stage"),
        rule_reference=_str(_field(data, "rule_reference", ctx), f"{ctx}.rule_reference"),
        input_summary=_str(_field(data, "input_summary", ctx), f"{ctx}.input_summary"),
        output_summary=_str(_field(data, "output_summary", ctx), f"{ctx}.output_summary"),
        explanation=_str(_field(data, "explanation", ctx), f"{ctx}.explanation"),
        component_id=_optional(
            lambda v, c: _enum(ComponentId, v, c),
            _field(data, "component_id", ctx),
            f"{ctx}.component_id",
        ),
        category=_optional(
            lambda v, c: _enum(Category, v, c), _field(data, "category", ctx), f"{ctx}.category"
        ),
    )


def _unavailable_required_input(value: object, ctx: str) -> UnavailableRequiredInput:
    keys = frozenset(
        {
            "component_id",
            "measurement_id",
            "missing_reason",
            "missing_observation",
            "attempted_methods",
        }
    )
    data = _object(value, keys, ctx)
    return _build(
        UnavailableRequiredInput,
        ctx,
        component_id=_enum(ComponentId, _field(data, "component_id", ctx), f"{ctx}.component_id"),
        measurement_id=_optional(
            lambda v, c: _enum(MeasurementId, v, c),
            _field(data, "measurement_id", ctx),
            f"{ctx}.measurement_id",
        ),
        missing_reason=_enum(
            MissingReason, _field(data, "missing_reason", ctx), f"{ctx}.missing_reason"
        ),
        missing_observation=_missing_observation(
            _field(data, "missing_observation", ctx), f"{ctx}.missing_observation"
        ),
        attempted_methods=_tuple(
            _method_ineligibility,
            _field(data, "attempted_methods", ctx),
            f"{ctx}.attempted_methods",
        ),
    )


def _provenance_entry(value: object, ctx: str) -> ProvenanceEntry:
    keys = frozenset(
        {
            "provider_id",
            "acquisition_method",
            "source_as_of",
            "retrieved_at",
            "component_id",
            "measurement_id",
        }
    )
    data = _object(value, keys, ctx)
    return _build(
        ProvenanceEntry,
        ctx,
        provider_id=_enum(ProviderId, _field(data, "provider_id", ctx), f"{ctx}.provider_id"),
        acquisition_method=_enum(
            AcquisitionMethod, _field(data, "acquisition_method", ctx), f"{ctx}.acquisition_method"
        ),
        source_as_of=_datetime(_field(data, "source_as_of", ctx), f"{ctx}.source_as_of"),
        retrieved_at=_datetime(_field(data, "retrieved_at", ctx), f"{ctx}.retrieved_at"),
        component_id=_optional(
            lambda v, c: _enum(ComponentId, v, c),
            _field(data, "component_id", ctx),
            f"{ctx}.component_id",
        ),
        measurement_id=_optional(
            lambda v, c: _enum(MeasurementId, v, c),
            _field(data, "measurement_id", ctx),
            f"{ctx}.measurement_id",
        ),
    )


_COMMON_RESULT_KEYS = frozenset(
    {
        "window_profile",
        "present_observations",
        "missing_observations",
        "validation_findings",
        "audit_derivation",
    }
)


def _common_result_fields(data: dict[str, object], ctx: str) -> dict[str, object]:
    return {
        "window_profile": _enum(
            WindowProfile, _field(data, "window_profile", ctx), f"{ctx}.window_profile"
        ),
        "present_observations": _tuple(
            _metric_observation,
            _field(data, "present_observations", ctx),
            f"{ctx}.present_observations",
        ),
        "missing_observations": _tuple(
            _missing_observation,
            _field(data, "missing_observations", ctx),
            f"{ctx}.missing_observations",
        ),
        "validation_findings": _tuple(
            _validation_finding,
            _field(data, "validation_findings", ctx),
            f"{ctx}.validation_findings",
        ),
        "audit_derivation": _tuple(
            _audit_entry, _field(data, "audit_derivation", ctx), f"{ctx}.audit_derivation"
        ),
    }


def _read_evaluated_result(data: dict[str, object], ctx: str) -> EvaluatedGradeResult:
    keys = _COMMON_RESULT_KEYS | frozenset(
        {"component_scores", "category_scores", "total_score", "grade"}
    )
    _reject_unknown(data, keys, ctx)
    common = _common_result_fields(data, ctx)
    return _build(
        EvaluatedGradeResult,
        ctx,
        **common,
        component_scores=_tuple(
            _component_score, _field(data, "component_scores", ctx), f"{ctx}.component_scores"
        ),
        category_scores=_tuple(
            _category_score, _field(data, "category_scores", ctx), f"{ctx}.category_scores"
        ),
        total_score=_decimal(_field(data, "total_score", ctx), f"{ctx}.total_score"),
        grade=_enum(Grade, _field(data, "grade", ctx), f"{ctx}.grade"),
    )


def _read_not_evaluable_result(data: dict[str, object], ctx: str) -> NotEvaluableGradeResult:
    keys = _COMMON_RESULT_KEYS | frozenset({"unavailable_required_inputs"})
    _reject_unknown(data, keys, ctx)
    common = _common_result_fields(data, ctx)
    return _build(
        NotEvaluableGradeResult,
        ctx,
        **common,
        unavailable_required_inputs=_tuple(
            _unavailable_required_input,
            _field(data, "unavailable_required_inputs", ctx),
            f"{ctx}.unavailable_required_inputs",
        ),
    )


def _read_grade_result(value: object, ctx: str) -> GradeResult:
    data = _mapping(value, ctx)
    if any(key in data for key in ("grade", "total_score")):
        return _read_evaluated_result(data, ctx)
    if "unavailable_required_inputs" in data:
        return _read_not_evaluable_result(data, ctx)
    raise EvaluationSerializationError(
        f"{ctx} is neither an evaluated nor a not-evaluable grade result "
        "(no discriminating fields present)"
    )


def _read_snapshot(data: dict[str, object], ctx: str) -> InputSnapshot:
    keys = frozenset(
        {
            "snapshot_id",
            "input_hash",
            "source_capture_id",
            "game_context",
            "batter",
            "expected_starting_pitcher",
            "pitcher_role",
            "as_of",
            "window_profile",
            "window_start",
            "window_end",
            "present_observations",
            "missing_observations",
            "validation_inputs",
            "weather_is_forecast",
        }
    )
    _reject_unknown(data, keys, ctx)
    return _build(
        InputSnapshot,
        ctx,
        snapshot_id=_snapshot_id(_field(data, "snapshot_id", ctx), f"{ctx}.snapshot_id"),
        input_hash=_sha256(_field(data, "input_hash", ctx), f"{ctx}.input_hash"),
        source_capture_id=_source_capture_id(
            _field(data, "source_capture_id", ctx), f"{ctx}.source_capture_id"
        ),
        game_context=_game_context(_field(data, "game_context", ctx), f"{ctx}.game_context"),
        batter=_batter(_field(data, "batter", ctx), f"{ctx}.batter"),
        expected_starting_pitcher=_pitcher(
            _field(data, "expected_starting_pitcher", ctx), f"{ctx}.expected_starting_pitcher"
        ),
        pitcher_role=_enum(PitcherRole, _field(data, "pitcher_role", ctx), f"{ctx}.pitcher_role"),
        as_of=_datetime(_field(data, "as_of", ctx), f"{ctx}.as_of"),
        window_profile=_enum(
            WindowProfile, _field(data, "window_profile", ctx), f"{ctx}.window_profile"
        ),
        window_start=_datetime(_field(data, "window_start", ctx), f"{ctx}.window_start"),
        window_end=_datetime(_field(data, "window_end", ctx), f"{ctx}.window_end"),
        present_observations=_tuple(
            _metric_observation,
            _field(data, "present_observations", ctx),
            f"{ctx}.present_observations",
        ),
        missing_observations=_tuple(
            _missing_observation,
            _field(data, "missing_observations", ctx),
            f"{ctx}.missing_observations",
        ),
        validation_inputs=_tuple(
            _validation_input_record,
            _field(data, "validation_inputs", ctx),
            f"{ctx}.validation_inputs",
        ),
        weather_is_forecast=_bool(
            _field(data, "weather_is_forecast", ctx), f"{ctx}.weather_is_forecast"
        ),
        # The internal rehydration path: identity is verified immediately after
        # this returns, before the snapshot reaches any caller.
        _authority=_SNAPSHOT_CONSTRUCTION_AUTHORITY,
    )


def _read_envelope(data: dict[str, object], ctx: str) -> EvaluationEnvelope:
    keys = frozenset(
        {
            "evaluation_id",
            "snapshot_id",
            "source_capture_id",
            "evaluated_at",
            "code_version",
            "model_configuration_version",
            "product_specification_version",
            "schema_version",
            "config_hash",
            "input_hash",
            "game_id",
            "slate_date",
            "batter_id",
            "expected_starting_pitcher_id",
            "window_profile",
            "pitcher_role",
            "provenance",
            "supersedes",
            "grade_result",
        }
    )
    _reject_unknown(data, keys, ctx)
    return _build(
        EvaluationEnvelope,
        ctx,
        evaluation_id=_evaluation_id(_field(data, "evaluation_id", ctx), f"{ctx}.evaluation_id"),
        snapshot_id=_snapshot_id(_field(data, "snapshot_id", ctx), f"{ctx}.snapshot_id"),
        source_capture_id=_source_capture_id(
            _field(data, "source_capture_id", ctx), f"{ctx}.source_capture_id"
        ),
        evaluated_at=_datetime(_field(data, "evaluated_at", ctx), f"{ctx}.evaluated_at"),
        code_version=_str(_field(data, "code_version", ctx), f"{ctx}.code_version"),
        model_configuration_version=_str(
            _field(data, "model_configuration_version", ctx), f"{ctx}.model_configuration_version"
        ),
        product_specification_version=_str(
            _field(data, "product_specification_version", ctx),
            f"{ctx}.product_specification_version",
        ),
        schema_version=_int(_field(data, "schema_version", ctx), f"{ctx}.schema_version"),
        config_hash=_sha256(_field(data, "config_hash", ctx), f"{ctx}.config_hash"),
        input_hash=_sha256(_field(data, "input_hash", ctx), f"{ctx}.input_hash"),
        game_id=_game_id(_field(data, "game_id", ctx), f"{ctx}.game_id"),
        slate_date=_date(_field(data, "slate_date", ctx), f"{ctx}.slate_date"),
        batter_id=_player_id(_field(data, "batter_id", ctx), f"{ctx}.batter_id"),
        expected_starting_pitcher_id=_player_id(
            _field(data, "expected_starting_pitcher_id", ctx),
            f"{ctx}.expected_starting_pitcher_id",
        ),
        window_profile=_enum(
            WindowProfile, _field(data, "window_profile", ctx), f"{ctx}.window_profile"
        ),
        pitcher_role=_enum(PitcherRole, _field(data, "pitcher_role", ctx), f"{ctx}.pitcher_role"),
        provenance=_tuple(_provenance_entry, _field(data, "provenance", ctx), f"{ctx}.provenance"),
        supersedes=_optional(_evaluation_id, _field(data, "supersedes", ctx), f"{ctx}.supersedes"),
        grade_result=_read_grade_result(_field(data, "grade_result", ctx), f"{ctx}.grade_result"),
    )


def _read_outcome(data: dict[str, object], ctx: str) -> OutcomeRecord:
    keys = frozenset({"game_id", "batter_id", "hit_at_least_one_home_run"})
    _reject_unknown(data, keys, ctx)
    return _build(
        OutcomeRecord,
        ctx,
        game_id=_game_id(_field(data, "game_id", ctx), f"{ctx}.game_id"),
        batter_id=_player_id(_field(data, "batter_id", ctx), f"{ctx}.batter_id"),
        hit_at_least_one_home_run=_bool(
            _field(data, "hit_at_least_one_home_run", ctx), f"{ctx}.hit_at_least_one_home_run"
        ),
    )


# --------------------------------------------------------------------------
# Deserialization (wrapper handling + dispatch)
# --------------------------------------------------------------------------


def _open_wrapper(data: bytes) -> tuple[str, int, object]:
    if not isinstance(data, bytes | bytearray):
        raise EvaluationSerializationError(
            f"a serialized record must be bytes, got {type(data).__name__}"
        )
    try:
        parsed = json.loads(bytes(data).decode("utf-8"), parse_float=_reject_float)
    except UnicodeDecodeError as exc:
        raise EvaluationSerializationError("a serialized record must be UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise EvaluationSerializationError(
            f"a serialized record must be valid JSON: {exc}"
        ) from exc

    wrapper = _object(
        parsed, frozenset({"record_type", "schema_version", "payload"}), "record wrapper"
    )
    record_type = _str(
        _field(wrapper, "record_type", "record wrapper"), "record wrapper.record_type"
    )
    schema_version = _int(
        _field(wrapper, "schema_version", "record wrapper"), "record wrapper.schema_version"
    )
    payload = _field(wrapper, "payload", "record wrapper")
    return record_type, schema_version, payload


def _require_supported(record_type: str, schema_version: int) -> None:
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise UnsupportedRecordSchemaVersionError(
            f"record type {record_type!r} declares schema version {schema_version}, but this "
            f"build supports {sorted(SUPPORTED_SCHEMA_VERSIONS)}"
        )


def deserialize_record(data: bytes) -> Record:
    """Decode canonical bytes into the exact GM-006 record they describe.

    Rejects an unknown record type, an unknown/newer schema version, unknown or
    missing fields, wrong types, and any floating-point number — always as a typed
    evaluation error. A decoded snapshot's identity is recomputed and a mismatch
    raises :class:`RecordIntegrityError`; an envelope's wrapper and embedded schema
    versions must agree.
    """
    record_type, schema_version, payload = _open_wrapper(data)

    if record_type == _SNAPSHOT:
        _require_supported(record_type, schema_version)
        snapshot = _read_snapshot(_mapping(payload, "input_snapshot payload"), "InputSnapshot")
        verify_snapshot_identity(snapshot)
        return snapshot
    if record_type == _EVALUATED:
        _require_supported(record_type, schema_version)
        return _read_evaluated_result(
            _mapping(payload, "evaluated_grade_result payload"), "EvaluatedGradeResult"
        )
    if record_type == _NOT_EVALUABLE:
        _require_supported(record_type, schema_version)
        return _read_not_evaluable_result(
            _mapping(payload, "not_evaluable_grade_result payload"), "NotEvaluableGradeResult"
        )
    if record_type == _ENVELOPE:
        _require_supported(record_type, schema_version)
        envelope = _read_envelope(
            _mapping(payload, "evaluation_envelope payload"), "EvaluationEnvelope"
        )
        if envelope.schema_version != schema_version:
            raise RecordIntegrityError(
                f"envelope wrapper schema_version {schema_version} does not match the embedded "
                f"schema_version {envelope.schema_version}"
            )
        return envelope
    if record_type == _OUTCOME:
        _require_supported(record_type, schema_version)
        return _read_outcome(_mapping(payload, "outcome_record payload"), "OutcomeRecord")

    raise EvaluationSerializationError(
        f"unknown record type {record_type!r}; supported: "
        f"{sorted((_SNAPSHOT, _EVALUATED, _NOT_EVALUABLE, _ENVELOPE, _OUTCOME))}"
    )


def _expect(record: Record, expected: type[T], record_type: str) -> T:
    if not isinstance(record, expected):
        raise EvaluationSerializationError(
            f"expected a {record_type}, got a {type(record).__name__}"
        )
    return record


def deserialize_snapshot(data: bytes) -> InputSnapshot:
    """Decode bytes into an :class:`InputSnapshot`, verifying its identity."""
    return _expect(deserialize_record(data), InputSnapshot, _SNAPSHOT)


def deserialize_evaluated_result(data: bytes) -> EvaluatedGradeResult:
    """Decode bytes into an :class:`EvaluatedGradeResult`."""
    return _expect(deserialize_record(data), EvaluatedGradeResult, _EVALUATED)


def deserialize_not_evaluable_result(data: bytes) -> NotEvaluableGradeResult:
    """Decode bytes into a :class:`NotEvaluableGradeResult`."""
    return _expect(deserialize_record(data), NotEvaluableGradeResult, _NOT_EVALUABLE)


def deserialize_envelope(data: bytes) -> EvaluationEnvelope:
    """Decode bytes into an :class:`EvaluationEnvelope`."""
    return _expect(deserialize_record(data), EvaluationEnvelope, _ENVELOPE)


def deserialize_outcome(data: bytes) -> OutcomeRecord:
    """Decode bytes into an :class:`OutcomeRecord`."""
    return _expect(deserialize_record(data), OutcomeRecord, _OUTCOME)
