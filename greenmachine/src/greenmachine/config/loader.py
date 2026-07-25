"""Strict YAML loading: text in, frozen typed configuration out.

"No dictionaries escape this package" (ARCHITECTURE.md §4.2). The loader reads
UTF-8, parses exactly one YAML mapping under a hardened loader, validates the
shape with the schema models, runs every semantic invariant, and returns a
frozen :class:`~greenmachine.config.schema.GreenMachineConfig`. The parsed
mapping itself is never stored or returned.

The YAML dialect is deliberately narrow:

* **Duplicate keys are an error.** PyYAML's default is last-one-wins, which
  silently discards a threshold somebody meant to set.
* **Aliases and merge keys are rejected.** They are the only way a YAML document
  can make two parts of the tree share one object, and a shared mutable default
  is exactly what a frozen configuration must not contain. Rejecting them proves
  independence rather than relying on the models to copy correctly.
* **No environment interpolation, no includes, no network.** A configuration
  means the same thing on every machine or it means nothing.

File I/O is confined to :func:`load_config`; :func:`load_config_text` does the
whole job from a string and touches no filesystem.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from .errors import ConfigParseError, ConfigSchemaError, context_for, key_path_text
from .schema import GreenMachineConfig
from .validation_rules import validate_semantics

__all__ = ["StrictConfigLoader", "load_config", "load_config_text"]


class _DuplicateKey(yaml.MarkedYAMLError):
    """A mapping declared the same key twice."""


class _AliasNotAllowed(yaml.MarkedYAMLError):
    """The document used a YAML alias or merge key."""


class _UnhashableKey(yaml.MarkedYAMLError):
    """A mapping key was itself a list or mapping (``? [a, b]``)."""


# Pydantic reports a discriminated-union error with the matched branch's
# discriminator value inserted as a path segment (``...scoring[0].bucketed.key``).
# That value is not a key in the YAML document, so it is removed before an
# ErrorContext is built. It is removed only when it sits immediately after the
# index into a genuine discriminated-union position *and* the document object
# there carries the matching discriminator value.
#
# A union is identified by its full schema **position**, not by a field name.
# The schema has exactly two discriminated unions, keyed here by the sequence of
# field names (indices dropped) that leads to the union list:
#
# * ``ComponentProfileConfig.scoring`` — the ``AnyScoring`` union.
# * ``SignalClause.all_of`` — the ``AnySignalCondition`` union.
#
# ``QualificationPredicate.all_of`` and ``.any_of`` are lists of plain
# ``PredicateComparison`` objects, *not* unions. Their field names collide with
# the signal union's, which is exactly why matching on position rather than name
# is required: a real ``grade_in`` key inside a binary predicate's ``all_of``
# must survive.
_SIGNAL_CONDITION_TAGS = frozenset(
    {"grade_in", "total_score", "category_score", "strong_category_count", "always"}
)
_UNION_POSITIONS: dict[tuple[str, ...], tuple[str, frozenset[str]]] = {
    # field-name spine (no indices) -> (discriminator key, permitted tag values)
    ("components", "profiles", "scoring"): ("method", frozenset({"bucketed", "binary"})),
    ("allocations", "signal_rules", "any_of", "all_of"): ("type", _SIGNAL_CONDITION_TAGS),
}


class StrictConfigLoader(yaml.SafeLoader):
    """A ``SafeLoader`` that refuses duplicate keys, aliases, and merge keys.

    ``SafeLoader`` already refuses arbitrary Python object construction. This
    narrows the dialect further to the subset a configuration file needs.
    """

    def compose_node(self, parent: yaml.Node | None, index: int) -> yaml.Node | None:
        # `check_event`/`peek_event` are untyped in types-PyYAML; the ignores are
        # narrow and cover a stub gap, not a weakness in this code.
        if self.check_event(yaml.events.AliasEvent):  # type: ignore[no-untyped-call]
            event = self.peek_event()  # type: ignore[no-untyped-call]
            raise _AliasNotAllowed(
                context="while composing configuration",
                context_mark=None,
                problem=(
                    "YAML aliases are not allowed in configuration; they let two parts of the "
                    "document share one object. Write the value out in full."
                ),
                problem_mark=event.start_mark,
            )
        return super().compose_node(parent, index)

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        seen: set[Any] = set()
        for key_node, _ in node.value:
            if key_node.tag == "tag:yaml.org,2002:merge":
                raise _AliasNotAllowed(
                    context="while constructing a configuration mapping",
                    context_mark=node.start_mark,
                    problem=(
                        "YAML merge keys ('<<') are not allowed in configuration; they share "
                        "structure between mappings. Write each mapping out in full."
                    ),
                    problem_mark=key_node.start_mark,
                )
            key = self.construct_object(key_node, deep=True)
            # A complex key (``? [a, b]``) constructs to a list or dict, which is
            # unhashable. Detect it here so ``key in seen`` cannot raise a raw
            # TypeError past the loader's own error contract.
            try:
                hash(key)
            except TypeError as exc:
                raise _UnhashableKey(
                    context="while constructing a configuration mapping",
                    context_mark=node.start_mark,
                    problem=(
                        f"a mapping key must be a scalar, got a {type(key).__name__}; complex "
                        "keys ('? [a, b]') are not allowed in configuration"
                    ),
                    problem_mark=key_node.start_mark,
                ) from exc
            if key in seen:
                raise _DuplicateKey(
                    context="while constructing a configuration mapping",
                    context_mark=node.start_mark,
                    problem=(
                        f"duplicate key {key!r}; the later value would silently replace the "
                        "earlier one"
                    ),
                    problem_mark=key_node.start_mark,
                )
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


def _parse_yaml(text: str, file_path: str | None) -> dict[str, Any]:
    """Parse exactly one YAML mapping, or raise :class:`ConfigParseError`."""
    try:
        documents = list(yaml.load_all(text, Loader=StrictConfigLoader))
    except yaml.YAMLError as exc:
        raise ConfigParseError(f"could not parse YAML: {exc}", context_for(file_path)) from exc

    if not documents:
        raise ConfigParseError(
            "the configuration is empty; expected one YAML mapping", context_for(file_path)
        )
    if len(documents) > 1:
        raise ConfigParseError(
            f"expected exactly one YAML document, found {len(documents)}",
            context_for(file_path),
        )

    document = documents[0]
    if not isinstance(document, dict):
        raise ConfigParseError(
            f"the configuration root must be a mapping, got {type(document).__name__}",
            context_for(file_path),
        )
    return document


def _normalize_key_path(location: tuple[object, ...], document: dict[str, Any]) -> tuple[str, ...]:
    """Render a Pydantic error location as a real YAML key path.

    Walks the location alongside the parsed document. A synthetic
    discriminated-union branch segment — the discriminator value Pydantic inserts
    right after the index into a union field — is dropped, but only when the
    document object at that position actually carries the matching discriminator.
    Everything else, including a genuine YAML key whose name happens to equal a
    discriminator value, is kept verbatim.

    A union is recognised by the full sequence of field names leading to it (its
    ``field_spine`` — the key segments with the list indices dropped), never by
    the immediate field name alone. ``all_of`` names a discriminated union under
    a signal rule but a plain list under a qualification predicate, so a real
    ``grade_in`` key inside a binary predicate's ``all_of`` is preserved.

    When the document cannot be navigated (because it is itself invalid), a
    candidate segment is *kept* rather than guessed at, so an accurate-but-noisier
    path is preferred over a wrong one.
    """
    path: list[str] = []
    # Only the key (non-index) segments, used to identify a union by position.
    field_spine: list[str] = []
    pointer: object = document
    # Set to the union's (discriminator key, tags) immediately after we index
    # into a genuine union position; the next string segment may then be synthetic.
    pending_union: tuple[str, frozenset[str]] | None = None

    for segment in location:
        if isinstance(segment, int):
            if isinstance(pointer, list) and 0 <= segment < len(pointer):
                pointer = pointer[segment]
            else:
                pointer = None
            path.append(str(segment))
            # The list we just indexed is a union only when the whole field-name
            # spine that reaches it is one the schema declares as a union.
            pending_union = _UNION_POSITIONS.get(tuple(field_spine))
            continue

        text = str(segment)
        if pending_union is not None:
            discriminator, tags = pending_union
            if text in tags and isinstance(pointer, dict) and pointer.get(discriminator) == text:
                # A synthetic branch segment: skip it, keep the pointer where it
                # is (the union element), and continue with the element's keys.
                pending_union = None
                continue

        pointer = pointer[text] if isinstance(pointer, dict) and text in pointer else None
        path.append(text)
        field_spine.append(text)
        pending_union = None

    return tuple(path)


def _subject_from_document(
    document: dict[str, Any], key_path: tuple[str, ...]
) -> tuple[str | None, str | None]:
    """Best-effort component/profile identity for a key path into ``document``.

    Reads the ``component_id`` and ``window_profile`` the path points at, but only
    when they are actually present as strings. Where the surrounding data is
    itself invalid there is nothing to read, so nothing is guessed.
    """
    metric: str | None = None
    window_profile: str | None = None

    if len(key_path) >= 2 and key_path[0] == "components" and key_path[1].isdigit():
        components = document.get("components")
        component = _at(components, int(key_path[1]))
        if isinstance(component, dict):
            component_id = component.get("component_id")
            if isinstance(component_id, str):
                metric = component_id
            if len(key_path) >= 4 and key_path[2] == "profiles" and key_path[3].isdigit():
                profile = _at(component.get("profiles"), int(key_path[3]))
                if isinstance(profile, dict):
                    window = profile.get("window_profile")
                    if isinstance(window, str):
                        window_profile = window

    return metric, window_profile


def _at(sequence: object, index: int) -> object:
    """Return ``sequence[index]`` when that is safe, else ``None``."""
    if isinstance(sequence, list) and 0 <= index < len(sequence):
        return sequence[index]
    return None


def _raise_schema_error(
    exc: ValidationError, document: dict[str, Any], file_path: str | None
) -> None:
    """Translate Pydantic's report into one typed, located failure."""
    first = exc.errors()[0]
    location = first.get("loc", ())
    key_path = _normalize_key_path(location, document)
    message = first.get("msg", "invalid value")
    detail = f"{key_path_text(key_path)}: {message}"
    if len(exc.errors()) > 1:
        detail += f" (and {len(exc.errors()) - 1} further schema problem(s))"

    metric, window_profile = _subject_from_document(document, key_path)
    raise ConfigSchemaError(
        detail,
        context_for(file_path, key_path, metric=metric, window_profile=window_profile),
    ) from exc


def load_config_text(text: str, *, file_path: str | None = None) -> GreenMachineConfig:
    """Load a configuration from YAML text. Performs no file I/O.

    Args:
        text: The YAML document.
        file_path: Where the text came from, recorded on any error's context so
            the failure names a file even though nothing was read here.

    Raises:
        ConfigParseError: ``file_path`` is not str/None, ``text`` is not a
            string, or the text is not one well-formed YAML mapping.
        ConfigSchemaError: unknown key, missing key, or wrong type.
        ConfigSemanticError: a MODEL_SPEC §19 invariant was violated.
    """
    # Validated at the boundary, before anything is parsed, and never silently
    # stringified: a bad ``file_path`` would otherwise become a nonsense label on
    # every error this call raised. Its own context carries no ``file_path``,
    # because the supplied value is the thing that is wrong.
    if file_path is not None and not isinstance(file_path, str):
        raise ConfigParseError(
            f"file_path must be a str or None, got {type(file_path).__name__}",
            context_for(None),
        )
    if not isinstance(text, str):
        raise ConfigParseError(
            f"configuration text must be a string, got {type(text).__name__}",
            context_for(file_path),
        )

    document = _parse_yaml(text, file_path)

    try:
        config = GreenMachineConfig.model_validate(document)
    except ValidationError as exc:
        _raise_schema_error(exc, document, file_path)
        raise  # pragma: no cover - _raise_schema_error always raises

    validate_semantics(config, file_path)
    return config


def load_config(path: str | Path) -> GreenMachineConfig:
    """Read a UTF-8 YAML file and load it.

    The only function in this package that touches the filesystem, and it only
    ever reads: configuration is version-controlled and never written by the
    application (ENGINEERING_GUIDELINES §8).

    Raises:
        ConfigParseError: the file cannot be read or is not one YAML mapping.
        ConfigSchemaError: unknown key, missing key, or wrong type.
        ConfigSemanticError: a MODEL_SPEC §19 invariant was violated.
    """
    # A wrong path type (``123``, ``None``) makes ``Path()`` raise a raw
    # TypeError; translate it so the public API only ever raises a configuration
    # error. ``file_path`` is unknown here, so it is left absent rather than
    # fabricated.
    try:
        location = Path(path)
    except TypeError as exc:
        raise ConfigParseError(
            f"configuration path must be a str or path-like, got {type(path).__name__}",
            context_for(None),
        ) from exc

    file_path = str(location)

    try:
        text = location.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ConfigParseError(
            f"configuration must be UTF-8 encoded: {exc}", context_for(file_path)
        ) from exc
    except OSError as exc:
        raise ConfigParseError(
            f"could not read configuration file: {exc}", context_for(file_path)
        ) from exc

    return load_config_text(text, file_path=file_path)
