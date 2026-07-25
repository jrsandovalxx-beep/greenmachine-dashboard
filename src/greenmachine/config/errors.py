"""Configuration failures, typed by the stage that rejected the file.

Three loading stages, three errors, all under
:class:`~greenmachine.common.errors.ConfigurationError` (ADR-0007):

* :class:`ConfigParseError` — the bytes are not one well-formed YAML mapping.
* :class:`ConfigSchemaError` — the shape is wrong: unknown key, missing key,
  wrong type, a YAML float where a quoted decimal string belongs.
* :class:`ConfigSemanticError` — the shape is right but the meaning is not:
  points that do not sum, buckets that overlap, a grade table with a gap.

The distinction matters during an incident. A parse error is a typo, a schema
error is a structural mistake, and a semantic error means somebody wrote a
configuration that would have produced a plausible wrong grade.

GM-004 adds a second family under the same root, for versioning and integrity:
resolving a version, registering one twice, offering a malformed hash, or
finding that a configuration already used to grade has since changed on disk.
:class:`ConfigVersionError` groups them so a caller can catch the whole family,
and each leaf is distinct so a caller can react to exactly one case.

Raw ``yaml`` and ``pydantic`` exceptions never escape this package, and neither
do the ``KeyError``/``OSError``/``ValueError`` the versioning layer meets: they
are translated here and preserved as ``__cause__`` so the original detail
survives without becoming the public contract.
"""

from __future__ import annotations

from greenmachine.common.errors import ConfigurationError, ErrorContext

__all__ = [
    "ConfigIntegrityError",
    "ConfigParseError",
    "ConfigSchemaError",
    "ConfigSemanticError",
    "ConfigVersionError",
    "ConflictingConfigVersionError",
    "DuplicateConfigVersionError",
    "MalformedConfigHashError",
    "ModifiedAfterUseError",
    "SourceModifiedError",
    "SourceUnavailableError",
    "UnknownConfigVersionError",
    "VersionLabelReplacedError",
    "context_for",
    "key_path_text",
]


class ConfigParseError(ConfigurationError):
    """The file is not a single well-formed YAML mapping.

    Covers malformed YAML, more than one document, a non-mapping root, a
    duplicate mapping key, and an alias or merge key.
    """


class ConfigSchemaError(ConfigurationError):
    """The configuration's shape is wrong.

    An unknown key, a missing required key, a wrong type, or a scoring numeric
    that was not supplied as a quoted string.
    """


class ConfigSemanticError(ConfigurationError):
    """The configuration parses and type-checks but means something invalid.

    Every rule in ``MODEL_SPEC.md`` §19 fails here rather than at load time in
    production: a violation is a load failure, never a warning.
    """


class MalformedConfigHashError(ConfigurationError):
    """A value offered as a ``config_hash`` is not one valid digest.

    A ``config_hash`` is exactly 64 lowercase hexadecimal characters (SHA-256).
    Uppercase, wrong length, whitespace, and non-hex all fail here rather than
    being stored — a broken identity is worse than none. Raised by the
    :class:`~greenmachine.config.hashing.ConfigHash` value object, never by
    computing a hash.
    """


class ConfigVersionError(ConfigurationError):
    """A configuration version could not be resolved, registered, or trusted.

    The shared root of the GM-004 family. Catch this to handle any versioning or
    integrity failure at once; catch a leaf to handle one case deliberately.
    """


class UnknownConfigVersionError(ConfigVersionError):
    """No configuration is registered under the requested version identifier.

    Carries the requested identifier and, in its message, the identifiers that
    *are* known — a raw ``KeyError`` would carry only the miss.
    """


class DuplicateConfigVersionError(ConfigVersionError):
    """Two configurations were offered under the same version identifier.

    A version identifier names exactly one set of rules; two records under one
    name cannot both be resolved, so the registry refuses to guess.
    """


class ConflictingConfigVersionError(DuplicateConfigVersionError):
    """A reused version identifier whose two configurations differ semantically.

    The stronger form of a duplicate: the same label would identify two
    *different* ``config_hash`` values. A subclass so that catching
    :class:`DuplicateConfigVersionError` still catches it, while a caller that
    cares can distinguish a genuine conflict from an identical re-registration.
    """


class ConfigIntegrityError(ConfigVersionError):
    """A configuration version failed a later modified-after-use check.

    The base of the four seal-verification outcomes below. A seal records what a
    version looked like when it was used; verification reloads the source and
    reports exactly how — if at all — it has since diverged.
    """


class ModifiedAfterUseError(ConfigIntegrityError):
    """The rules changed: same version identifier, different ``config_hash``.

    The most dangerous case — the label still claims to be the rules that
    produced an evaluation, but the meaning underneath it has moved.
    """


class VersionLabelReplacedError(ConfigIntegrityError):
    """The source now declares a different version identifier than was sealed."""


class SourceModifiedError(ConfigIntegrityError):
    """The source text changed although the configuration's meaning did not.

    Comments or formatting were edited: the ``config_hash`` still matches but the
    normalized source fingerprint does not, so the file is no longer byte-for-byte
    the one that was sealed.
    """


class SourceUnavailableError(ConfigIntegrityError):
    """The sealed source cannot be read back to verify it.

    The file is missing, unreadable, or the seal was taken over in-memory text
    with no source path at all, so on-disk verification is not possible.
    """


def key_path_text(key_path: tuple[str, ...]) -> str:
    """Render a key path for a message, e.g. ``allocations.categories[0].max_points``.

    The structured :class:`~greenmachine.common.errors.ErrorContext` remains the
    machine-readable form; this is only for the human sentence.
    """
    if not key_path:
        return "<root>"
    rendered = ""
    for part in key_path:
        if part.isdigit():
            rendered += f"[{part}]"
        elif rendered:
            rendered += f".{part}"
        else:
            rendered = part
    return rendered


def context_for(
    file_path: str | None,
    key_path: tuple[str, ...] = (),
    *,
    metric: str | None = None,
    window_profile: str | None = None,
    subject: str | None = None,
    expected: str | None = None,
    observed: str | None = None,
) -> ErrorContext:
    """Build the structured context every configuration error carries.

    ``expected``/``observed`` carry the two sides of a mismatch — the sealed
    hash versus the current one, the sealed source fingerprint versus the reloaded
    one — for the GM-004 integrity errors. They stay ``None`` everywhere else.
    """
    return ErrorContext(
        file_path=file_path,
        key_path=key_path,
        metric=metric,
        window_profile=window_profile,
        subject=subject,
        expected=expected,
        observed=observed,
    )
