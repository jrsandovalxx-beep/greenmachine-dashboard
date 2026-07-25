"""The project error taxonomy: typed, specific, and carrying structured context.

ADR-0007. GreenMachine's value proposition is trustworthy explanation, so a
failure has to be diagnosable from the record alone. That needs three things a
message string cannot give:

* a **stable error code** derived from the class, not from prose that someone
  will reword;
* **structured context** — which file, which key path, which metric, which
  profile, which subject — held as fields rather than formatted into a sentence;
* a **root type** every caller can catch deliberately, so nothing has to reach
  for ``except Exception``.

The hierarchy is deliberately shallow: five branches matching the layers that can
fail, plus the one ingestion subtype ADR-0007 names. New leaves are added when a
real raise site needs one, not in anticipation.

Nothing here reads a clock, an environment variable, or the filesystem, and
nothing imports another GreenMachine package: every layer raises these, so
anything they depended on would become a dependency of the whole system.
"""

from __future__ import annotations

from dataclasses import dataclass, fields

__all__ = [
    "ConfigurationError",
    "DataInputError",
    "DomainInvariantError",
    "ErrorContext",
    "GreenMachineError",
    "IngestionError",
    "PersistenceError",
    "ProviderSchemaChangeError",
]


@dataclass(frozen=True, slots=True)
class ErrorContext:
    """Immutable structured context attached to every project error.

    Every field is optional: a low layer supplies only what it knows, and an
    outer layer is free to raise with more. Values are plain strings rather than
    domain enums — ``common`` sits underneath ``domain`` and must not import it,
    so a caller passes ``window_profile.value``.

    ``key_path`` is a tuple rather than a list so the whole context stays frozen
    and hashable; no mutable container is stored anywhere.

    ``provider``, ``expected``, and ``observed`` exist for source-schema
    mismatches (see :class:`ProviderSchemaChangeError`) and are ignored by
    everything else.
    """

    file_path: str | None = None
    key_path: tuple[str, ...] = ()
    metric: str | None = None
    window_profile: str | None = None
    subject: str | None = None
    provider: str | None = None
    expected: str | None = None
    observed: str | None = None

    def __post_init__(self) -> None:
        for spec in fields(self):
            value = getattr(self, spec.name)
            if spec.name == "key_path":
                self._check_key_path(value)
            elif value is not None and not isinstance(value, str):
                raise TypeError(
                    f"ErrorContext.{spec.name} must be a string or None, got {type(value).__name__}"
                )

    @staticmethod
    def _check_key_path(value: object) -> None:
        if not isinstance(value, tuple):
            raise TypeError(
                f"ErrorContext.key_path must be a tuple (an immutable sequence), "
                f"got {type(value).__name__}"
            )
        for index, part in enumerate(value):
            if not isinstance(part, str):
                raise TypeError(
                    f"ErrorContext.key_path[{index}] must be a string, got {type(part).__name__}"
                )

    @property
    def is_empty(self) -> bool:
        """True when nothing at all was supplied."""
        return self == _EMPTY_CONTEXT

    def as_dict(self) -> dict[str, str | list[str]]:
        """A **newly allocated** plain dictionary of the fields that were set.

        Safe to hand to a log formatter and safe for the caller to mutate: the
        dictionary, and the list it holds for ``key_path``, are built fresh on
        every call, so nothing a consumer does can reach back into the error.
        Unset fields are omitted rather than emitted as nulls.
        """
        payload: dict[str, str | list[str]] = {}
        for spec in fields(self):
            value = getattr(self, spec.name)
            if spec.name == "key_path":
                if value:
                    payload["key_path"] = list(value)
            elif value is not None:
                payload[spec.name] = value
        return payload


_EMPTY_CONTEXT = ErrorContext()


class GreenMachineError(Exception):
    """Root of every error GreenMachine raises deliberately.

    Catching this catches everything the project itself signals, and nothing
    else — which is what makes ``except Exception`` unnecessary and therefore
    prohibited (ADR-0007, enforced by an architecture test).

    A context always exists; it may be empty. Construction refuses a wrong-typed
    message or context rather than storing malformed state, because an error
    object that is itself broken is the worst thing to meet during an incident.
    """

    def __init__(self, message: str, context: ErrorContext | None = None) -> None:
        if not isinstance(message, str):
            raise TypeError(
                f"{type(self).__name__} message must be a string, got {type(message).__name__}"
            )
        if not message.strip():
            raise ValueError(f"{type(self).__name__} message must not be blank")
        if context is not None and not isinstance(context, ErrorContext):
            raise TypeError(
                f"{type(self).__name__} context must be an ErrorContext or None, "
                f"got {type(context).__name__}"
            )

        # A frozen module-level singleton, never a mutable default argument.
        resolved = _EMPTY_CONTEXT if context is None else context
        self._message = message
        self._context = resolved
        super().__init__(message)

    @property
    def message(self) -> str:
        """The human-readable description."""
        return self._message

    @property
    def context(self) -> ErrorContext:
        """The structured context. Always present, possibly empty."""
        return self._context

    @property
    def error_type(self) -> str:
        """Stable machine-readable code, derived from the class name.

        Derived from the type rather than written by hand at each raise site, so
        it cannot drift from the class it describes or vary in wording.
        """
        return type(self).__name__

    def as_log_record(self) -> dict[str, str | dict[str, str | list[str]]]:
        """Structured form for logging: fields, never a parsed exception string.

        The dictionary is freshly built, so a formatter may mutate it freely.
        """
        return {
            "error_type": self.error_type,
            "message": self._message,
            "context": self._context.as_dict(),
        }

    def __str__(self) -> str:
        return self._message

    def __repr__(self) -> str:
        return f"{type(self).__name__}(message={self._message!r}, context={self._context!r})"


class ConfigurationError(GreenMachineError):
    """A model configuration could not be loaded, parsed, or validated."""


class DataInputError(GreenMachineError):
    """A value supplied to the system was malformed, missing, or out of policy.

    Covers the numeric policy, canonical serialization, identifier derivation,
    and clock inputs — anything where the *data handed in* is the problem.
    """


class DomainInvariantError(GreenMachineError):
    """A domain object was asked to exist in a state the model forbids."""


class IngestionError(GreenMachineError):
    """A provider could not be read, or returned something unusable."""


class PersistenceError(GreenMachineError):
    """Stored history could not be read, or was asked to be mutated."""


class ProviderSchemaChangeError(IngestionError):
    """A source's shape no longer matches what the adapter was written against.

    ADR-0007 singles this out because it is the failure most likely to corrupt a
    slate quietly: a renamed leaderboard column that yields zeros looks like a
    cold streak. Adapters raise this loudly instead, recording ``provider``,
    ``expected``, and ``observed`` on the context so the diff is in the record.

    This is the error contract only. No adapter or parser is implemented here.
    """
