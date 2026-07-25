"""Strict loading of the injected sample-minimum policy from exact bytes.

The policy is always supplied explicitly — there is no default anywhere in
``src/`` (Q14, the production minimums, remains an open Product Owner
decision). Loading is byte-oriented on purpose: the same exact bytes that a
capture validated are archived inside the published bundle, and replay reloads
and digest-verifies those archived bytes, so a run can never be replayed under
silently different minimums.

The document contract is exact and fails closed:

* the root is a JSON object with exactly the fields ``disclaimer`` and
  ``minimums`` — unknown fields are rejected;
* ``disclaimer`` is a non-blank string or a list of strings (joined with one
  space);
* ``minimums`` maps component values to objects mapping window-profile values
  to non-boolean integers.

Completeness (every policy component under both profiles), uniqueness, and
non-negativity are then enforced by :class:`SampleMinimumPolicy` itself.
"""

from __future__ import annotations

from greenmachine.domain import ComponentId, WindowProfile

from .errors import SamplePolicyError
from .models import SampleMinimumPolicy
from .strict_json import strict_json_loads

__all__ = ["load_sample_policy"]

_ROOT_FIELDS = frozenset({"disclaimer", "minimums"})


def _policy_error(detail: str) -> SamplePolicyError:
    return SamplePolicyError(detail)


def load_sample_policy(raw: bytes) -> SampleMinimumPolicy:
    """Parse exact policy bytes strictly into a complete ``SampleMinimumPolicy``.

    Duplicate JSON keys are rejected at every nesting level — a duplicated
    component or profile key could otherwise silently shadow a minimum.
    """
    document = strict_json_loads(raw, describe="the sample policy", on_error=_policy_error)
    if not isinstance(document, dict):
        raise SamplePolicyError("the sample policy root must be a JSON object")

    unknown = sorted(set(document) - _ROOT_FIELDS)
    if unknown:
        raise SamplePolicyError(f"the sample policy carries unknown field(s): {unknown}")
    missing = sorted(_ROOT_FIELDS - set(document))
    if missing:
        raise SamplePolicyError(f"the sample policy is missing required field(s): {missing}")

    raw_disclaimer = document["disclaimer"]
    if isinstance(raw_disclaimer, list):
        if not all(isinstance(line, str) for line in raw_disclaimer):
            raise SamplePolicyError("every sample policy disclaimer line must be a string")
        disclaimer = " ".join(raw_disclaimer)
    elif isinstance(raw_disclaimer, str):
        disclaimer = raw_disclaimer
    else:
        raise SamplePolicyError(
            "the sample policy 'disclaimer' must be a string or a list of strings"
        )
    if not disclaimer.strip():
        raise SamplePolicyError("the sample policy must carry a non-blank 'disclaimer'")

    minimums = document["minimums"]
    if not isinstance(minimums, dict):
        raise SamplePolicyError("the sample policy 'minimums' must be an object")
    entries: list[tuple[ComponentId, WindowProfile, int]] = []
    for component_value, per_profile in minimums.items():
        try:
            component = ComponentId(component_value)
        except ValueError as exc:
            raise SamplePolicyError(
                f"sample policy component '{component_value}' is not a known component"
            ) from exc
        if not isinstance(per_profile, dict):
            raise SamplePolicyError(
                f"sample policy minimums for '{component_value}' must be an object"
            )
        for profile_value, minimum in per_profile.items():
            try:
                profile = WindowProfile(profile_value)
            except ValueError as exc:
                raise SamplePolicyError(
                    f"sample policy profile '{profile_value}' is not a known window profile"
                ) from exc
            candidate: object = minimum
            if isinstance(candidate, bool) or not isinstance(candidate, int):
                raise SamplePolicyError(
                    f"sample policy minimum for ('{component_value}', '{profile_value}') "
                    f"must be an integer"
                )
            entries.append((component, profile, candidate))
    return SampleMinimumPolicy(disclaimer=disclaimer, entries=tuple(entries))
