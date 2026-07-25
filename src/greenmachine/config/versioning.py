"""Versioned configurations: identity, a read-only registry, and a use seal.

GM-003 turns YAML into a validated :class:`GreenMachineConfig`. This module gives
each one a durable identity and the machinery to trust it later:

* :class:`VersionedConfiguration` — an immutable record pairing a configuration
  with its human label, its semantic :class:`~greenmachine.config.hashing.ConfigHash`,
  and (when file-backed) where it came from and a source fingerprint.
* :func:`load_versioned_config` / :func:`load_versioned_config_text` — load
  through the approved GM-003 loader, then compute the identity. No YAML parsing
  or semantic validation is duplicated here.
* :class:`ConfigurationVersionRegistry` — an explicit, read-only collection that
  resolves versions by identifier, keeps many at once independently, and refuses
  a duplicate or conflicting identifier rather than silently choosing one.
* :class:`ConfigurationUseSeal` — a small immutable token a caller keeps when a
  version is used, so :meth:`ConfigurationUseSeal.verify_unchanged` can later
  reload the source and report exactly how it has diverged, if at all.

Nothing here reads a clock, consults the environment, generates randomness, holds
a global "active" version, or writes anything. The only side effect is reading
the files it is explicitly told to read.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from .errors import (
    ConfigParseError,
    ConfigVersionError,
    ConflictingConfigVersionError,
    DuplicateConfigVersionError,
    ModifiedAfterUseError,
    SourceModifiedError,
    SourceUnavailableError,
    UnknownConfigVersionError,
    VersionLabelReplacedError,
    context_for,
)
from .hashing import ConfigHash, is_sha256_hex
from .hashing import config_hash as compute_config_hash
from .hashing import source_digest as compute_source_digest
from .loader import load_config_text
from .schema import GreenMachineConfig

__all__ = [
    "ConfigurationUseSeal",
    "ConfigurationVersionRegistry",
    "VersionedConfiguration",
    "load_versioned_config",
    "load_versioned_config_text",
]


# --------------------------------------------------------------------------
# The versioned record
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class VersionedConfiguration:
    """One validated configuration together with its identity.

    Frozen, and hashable to the extent its fields are (the configuration is a
    frozen model, the hash and the strings are immutable). Carries no timestamp,
    no randomness, and reads no environment: two loads of the same bytes produce
    equal records.

    ``source_path`` and ``source_digest`` describe where the configuration came
    from. A file-backed load sets both; a text load sets only the digest (of the
    text it was handed), because there is no path to reload later.
    """

    version_identifier: str
    config_hash: ConfigHash
    configuration: GreenMachineConfig
    source_path: str | None = None
    source_digest: str | None = None

    def __post_init__(self) -> None:
        # Field types first. A widened alias keeps each guard live at runtime for
        # an untyped caller, the way the loader's own boundary checks do.
        identifier: object = self.version_identifier
        _require_version_identifier(identifier)
        if not isinstance(self.config_hash, ConfigHash):
            raise ConfigVersionError(
                f"config_hash must be a ConfigHash value object, got "
                f"{type(self.config_hash).__name__}",
                context_for(None, subject=self.version_identifier),
            )
        configuration: object = self.configuration
        if not isinstance(configuration, GreenMachineConfig):
            raise ConfigVersionError(
                f"configuration must be a GreenMachineConfig, got {type(configuration).__name__}",
                context_for(None, subject=self.version_identifier),
            )
        _validate_source_fields(
            self.source_path, self.source_digest, subject=self.version_identifier
        )

        # Identity coherence: the record must not be able to claim a label or a
        # semantic hash that does not describe the configuration it carries.
        actual_label = configuration.model_configuration_version
        if self.version_identifier != actual_label:
            raise ConfigVersionError(
                f"version identifier {self.version_identifier!r} does not match the "
                f"configuration's model_configuration_version {actual_label!r}",
                context_for(
                    self.source_path if isinstance(self.source_path, str) else None,
                    subject=self.version_identifier,
                    expected=actual_label,
                    observed=self.version_identifier,
                ),
            )
        actual_hash = compute_config_hash(configuration)
        if self.config_hash != actual_hash:
            raise ConfigVersionError(
                f"config_hash does not describe the supplied configuration for version "
                f"{self.version_identifier!r}",
                context_for(
                    self.source_path if isinstance(self.source_path, str) else None,
                    subject=self.version_identifier,
                    expected=actual_hash.value,
                    observed=self.config_hash.value,
                ),
            )


def _require_version_identifier(identifier: object) -> None:
    """Reject anything that is not a usable version identifier."""
    if not isinstance(identifier, str) or not identifier.strip():
        raise ConfigVersionError(
            f"a version identifier must be a non-blank string, got {identifier!r}",
            context_for(None),
        )


def _validate_source_fields(source_path: object, source_digest: object, *, subject: str) -> None:
    """Enforce the source-field rules shared by records and seals.

    ``source_digest``, when present, must be one valid lowercase SHA-256 hex value
    — the same well-formedness :class:`ConfigHash` demands, but a *different* fact,
    so it is not a ``ConfigHash`` and a malformed one is a version error, not a
    ``MalformedConfigHashError``. A ``source_path`` must be a non-blank absolute
    path (so later verification is independent of any working directory) and,
    being file-backed, requires a ``source_digest`` to check against. The path is
    never required to exist at construction time.
    """
    if source_digest is not None and not is_sha256_hex(source_digest):
        raise ConfigVersionError(
            f"source_digest must be one lowercase 64-character SHA-256 hex value, got "
            f"{source_digest!r}",
            context_for(source_path if isinstance(source_path, str) else None, subject=subject),
        )
    if source_path is None:
        return
    if not isinstance(source_path, str) or not source_path.strip():
        raise ConfigVersionError(
            f"source_path must be a non-blank string or None, got {source_path!r}",
            context_for(None, subject=subject),
        )
    if not Path(source_path).is_absolute():
        raise ConfigVersionError(
            f"source_path must be an absolute path so verification is independent of the "
            f"working directory, got {source_path!r}",
            context_for(source_path, subject=subject),
        )
    if source_digest is None:
        raise ConfigVersionError(
            f"a file-backed record (source_path {source_path!r}) requires a source_digest",
            context_for(source_path, subject=subject),
        )


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------


def load_versioned_config_text(
    text: str, *, file_path: str | None = None
) -> VersionedConfiguration:
    """Load a versioned configuration from YAML text. Performs no file I/O.

    Uses the GM-003 text loader, so its typed
    :class:`~greenmachine.config.errors.ConfigParseError`,
    :class:`~greenmachine.config.errors.ConfigSchemaError`, and
    :class:`~greenmachine.config.errors.ConfigSemanticError` propagate unchanged.
    ``file_path`` is a label for those errors only; the resulting record is
    text-backed and has no ``source_path``, so filesystem verification of its
    seal is unavailable by design.
    """
    config = load_config_text(text, file_path=file_path)
    return _versioned(config, source_path=None, source_text=text)


def load_versioned_config(path: str | Path) -> VersionedConfiguration:
    """Read a UTF-8 YAML file and load it as a versioned configuration.

    Reads the file exactly once — the same bytes feed both the source fingerprint
    and the GM-003 loader — and never writes. A bad path type or an unreadable
    file becomes a typed :class:`~greenmachine.config.errors.ConfigParseError`
    (matching :func:`greenmachine.config.load_config`), never a raw ``OSError``.

    The stored ``source_path`` is made **absolute** (resolving the working
    directory in force at load time), so a file loaded through a relative name can
    still be verified after the caller has changed directories. No filesystem
    metadata enters either digest.
    """
    location = _as_path(path)
    text = _read_config_source(location)
    absolute = str(location.resolve())
    config = load_config_text(text, file_path=absolute)
    return _versioned(config, source_path=absolute, source_text=text)


def _versioned(
    config: GreenMachineConfig, *, source_path: str | None, source_text: str
) -> VersionedConfiguration:
    """Assemble a record from a validated configuration and its source text."""
    return VersionedConfiguration(
        version_identifier=config.model_configuration_version,
        config_hash=compute_config_hash(config),
        configuration=config,
        source_path=source_path,
        source_digest=compute_source_digest(source_text),
    )


def _as_path(path: str | Path) -> Path:
    try:
        return Path(path)
    except TypeError as exc:
        raise ConfigParseError(
            f"configuration path must be a str or path-like, got {type(path).__name__}",
            context_for(None),
        ) from exc


def _read_config_source(location: Path) -> str:
    """Read a configuration file as UTF-8, translating read failures.

    Mirrors GM-003's ``load_config`` so a missing file, a permission error, or a
    non-UTF-8 file surfaces as a typed configuration error rather than a raw
    ``OSError`` — reading is the only filesystem access this package performs.
    """
    try:
        return location.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ConfigParseError(
            f"configuration must be UTF-8 encoded: {exc}", context_for(str(location))
        ) from exc
    except OSError as exc:
        raise ConfigParseError(
            f"could not read configuration file: {exc}", context_for(str(location))
        ) from exc


# --------------------------------------------------------------------------
# The read-only registry
# --------------------------------------------------------------------------


class ConfigurationVersionRegistry:
    """An explicit, immutable set of configuration versions keyed by identifier.

    Built from a caller-supplied collection — either ready
    :class:`VersionedConfiguration` records or paths loaded immediately. It never
    scans a directory, reads an environment variable, or elects an "active"
    version, and it cannot be mutated after construction: the backing mapping is
    a read-only view, and attribute assignment is refused.

    A version identifier names exactly one set of rules, so registering the same
    identifier twice is an error — :class:`~greenmachine.config.errors.DuplicateConfigVersionError`
    for an identical re-registration, and the more specific
    :class:`~greenmachine.config.errors.ConflictingConfigVersionError` when the
    two share a label but differ semantically.
    """

    __slots__ = ("_by_identifier",)

    _by_identifier: Mapping[str, VersionedConfiguration]

    def __init__(self, versions: Iterable[VersionedConfiguration]) -> None:
        built: dict[str, VersionedConfiguration] = {}
        for version in versions:
            if not isinstance(version, VersionedConfiguration):
                raise ConfigVersionError(
                    f"a registry entry must be a VersionedConfiguration, got "
                    f"{type(version).__name__}",
                    context_for(None),
                )
            existing = built.get(version.version_identifier)
            if existing is not None:
                self._reject_reuse(existing, version)
            built[version.version_identifier] = version
        object.__setattr__(self, "_by_identifier", MappingProxyType(dict(built)))

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("ConfigurationVersionRegistry is immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("ConfigurationVersionRegistry is immutable")

    @staticmethod
    def _reject_reuse(existing: VersionedConfiguration, incoming: VersionedConfiguration) -> None:
        identifier = existing.version_identifier
        if existing.config_hash != incoming.config_hash:
            raise ConflictingConfigVersionError(
                f"version {identifier!r} was offered twice with different rules "
                f"({existing.config_hash} then {incoming.config_hash})",
                context_for(
                    incoming.source_path,
                    subject=identifier,
                    expected=existing.config_hash.value,
                    observed=incoming.config_hash.value,
                ),
            )
        raise DuplicateConfigVersionError(
            f"version {identifier!r} was offered more than once",
            context_for(incoming.source_path, subject=identifier),
        )

    @classmethod
    def from_versioned(
        cls, versions: Iterable[VersionedConfiguration]
    ) -> ConfigurationVersionRegistry:
        """Build a registry from already-loaded versioned configurations."""
        return cls(versions)

    @classmethod
    def from_paths(cls, paths: Iterable[str | Path]) -> ConfigurationVersionRegistry:
        """Build a registry by loading each path immediately, once, in order."""
        return cls([load_versioned_config(path) for path in paths])

    def identifiers(self) -> tuple[str, ...]:
        """Every known version identifier, in a deterministic sorted order."""
        return tuple(sorted(self._by_identifier))

    def __contains__(self, identifier: object) -> bool:
        # Never raises on a non-string or unhashable candidate — those simply are
        # not registered identifiers, so membership is False.
        return (
            isinstance(identifier, str)
            and bool(identifier.strip())
            and (identifier in self._by_identifier)
        )

    def __len__(self) -> int:
        return len(self._by_identifier)

    def resolve(self, identifier: str) -> VersionedConfiguration:
        """Return the version registered under ``identifier``.

        A non-string or blank identifier is a caller mistake and raises
        :class:`~greenmachine.config.errors.ConfigVersionError`; a well-formed but
        unregistered identifier raises
        :class:`~greenmachine.config.errors.UnknownConfigVersionError`. Neither a
        raw ``KeyError`` (from the lookup) nor a raw ``TypeError`` (from an
        unhashable candidate) is ever exposed.
        """
        candidate: object = identifier
        if not isinstance(candidate, str) or not candidate.strip():
            raise ConfigVersionError(
                f"a version identifier must be a non-blank string, got {candidate!r}",
                context_for(None),
            )
        if candidate in self._by_identifier:
            return self._by_identifier[candidate]
        known = ", ".join(self.identifiers()) or "(none registered)"
        raise UnknownConfigVersionError(
            f"no configuration registered under version {candidate!r}; known: {known}",
            context_for(None, subject=candidate),
        )


# --------------------------------------------------------------------------
# The modified-after-use seal
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ConfigurationUseSeal:
    """An immutable record of what a configuration version looked like when used.

    A caller takes a seal the moment a version is put to work. It stores only
    what is needed to check the version later — the identifier, the semantic
    hash, the source fingerprint, and the source path — and nothing that varies,
    so the seal itself is a stable, comparable value.

    :meth:`verify_unchanged` reloads the source and reports the outcome; it never
    rewrites the seal or the source. GM-006 decides when a seal is recorded and
    when it is checked — this module only provides the mechanism.
    """

    version_identifier: str
    config_hash: ConfigHash
    source_digest: str | None = None
    source_path: str | None = None

    def __post_init__(self) -> None:
        _require_version_identifier(self.version_identifier)
        if not isinstance(self.config_hash, ConfigHash):
            raise ConfigVersionError(
                f"a use seal's config_hash must be a ConfigHash value object, got "
                f"{type(self.config_hash).__name__}",
                context_for(None, subject=self.version_identifier),
            )
        # A seal has no configuration to re-derive the hash from, so it validates
        # only the fields it does hold. The same source-field rules apply.
        _validate_source_fields(
            self.source_path, self.source_digest, subject=self.version_identifier
        )

    @classmethod
    def over(cls, versioned: VersionedConfiguration) -> ConfigurationUseSeal:
        """Seal the identity of a versioned configuration at the point of use.

        Requires a :class:`VersionedConfiguration`; anything else raises a typed
        :class:`~greenmachine.config.errors.ConfigVersionError` rather than
        leaking an ``AttributeError`` from a missing field.
        """
        if not isinstance(versioned, VersionedConfiguration):
            raise ConfigVersionError(
                f"a use seal must be taken over a VersionedConfiguration, got "
                f"{type(versioned).__name__}",
                context_for(None),
            )
        return cls(
            version_identifier=versioned.version_identifier,
            config_hash=versioned.config_hash,
            source_digest=versioned.source_digest,
            source_path=versioned.source_path,
        )

    def verify_unchanged(self) -> VersionedConfiguration:
        """Reload the sealed source and confirm it still matches, or raise.

        Returns the freshly reloaded :class:`VersionedConfiguration` when
        everything matches. Otherwise raises the one integrity error that fits:

        * :class:`~greenmachine.config.errors.SourceUnavailableError` — the seal
          has no source path (it was taken over text), or the file is missing or
          unreadable;
        * :class:`~greenmachine.config.errors.VersionLabelReplacedError` — the
          source now declares a different version identifier;
        * :class:`~greenmachine.config.errors.ModifiedAfterUseError` — the rules
          changed under an unchanged identifier;
        * :class:`~greenmachine.config.errors.SourceModifiedError` — the meaning
          is unchanged but the source text (a comment, some formatting) was edited.

        A reloaded file that no longer parses or validates raises its GM-003 typed
        error unchanged. This method never mutates the seal.
        """
        if self.source_path is None:
            raise SourceUnavailableError(
                f"version {self.version_identifier!r} was sealed from in-memory text with no "
                "source path, so on-disk verification is not possible",
                context_for(None, subject=self.version_identifier),
            )

        text = _reload_source(Path(self.source_path), self.source_path)
        current = _versioned(
            load_config_text(text, file_path=self.source_path),
            source_path=self.source_path,
            source_text=text,
        )

        if current.version_identifier != self.version_identifier:
            raise VersionLabelReplacedError(
                f"version {self.version_identifier!r} was sealed, but the source now declares "
                f"{current.version_identifier!r}",
                context_for(
                    self.source_path,
                    subject=self.version_identifier,
                    observed=current.version_identifier,
                ),
            )
        if current.config_hash != self.config_hash:
            raise ModifiedAfterUseError(
                f"version {self.version_identifier!r} was modified after use: its rules "
                "changed while its identifier stayed the same",
                context_for(
                    self.source_path,
                    subject=self.version_identifier,
                    expected=self.config_hash.value,
                    observed=current.config_hash.value,
                ),
            )
        if self.source_digest is not None and current.source_digest != self.source_digest:
            raise SourceModifiedError(
                f"version {self.version_identifier!r} is semantically unchanged, but its "
                "source text was edited (a comment or formatting)",
                context_for(
                    self.source_path,
                    subject=self.version_identifier,
                    expected=self.source_digest,
                    observed=current.source_digest,
                ),
            )
        return current


def _reload_source(location: Path, source_path: str) -> str:
    """Read a sealed source back for verification, translating read failures.

    A missing file, a directory, or a permission error becomes a typed
    :class:`~greenmachine.config.errors.SourceUnavailableError` — distinct from
    the load-time ``ConfigParseError`` so a caller can tell "could not read for
    verification" from "could not load in the first place".
    """
    try:
        return location.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise SourceUnavailableError(
            f"sealed source {source_path!r} is not valid UTF-8: {exc}",
            context_for(source_path),
        ) from exc
    except OSError as exc:
        raise SourceUnavailableError(
            f"sealed source {source_path!r} could not be read for verification: {exc}",
            context_for(source_path),
        ) from exc
