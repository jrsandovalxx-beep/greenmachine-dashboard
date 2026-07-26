"""GM-041.5-HF2: the Hypothesis profile is the same in every environment.

Hypothesis fills any setting a profile leaves unspecified from the active
built-in profile, and on a hosted runner it detects CI and suppresses
``HealthCheck.too_slow``. An unspecified field therefore resolved differently on
a developer machine than in GitHub Actions — which is how a *determinism*
profile came to have environment-dependent settings, green locally and red in
CI for five consecutive deliveries.

Detection happens while Hypothesis is imported, so a test that merely sets
``os.environ`` in-process proves nothing: the decision was already made. Every
case here therefore runs a **subprocess** with a fabricated environment and
reads the profile back out of it.

GM-041.5-HF1 removed the environment dependence but pinned the wrong value,
``(HealthCheck.too_slow,)``, contradicting the policy recorded in
``tests/property/conftest.py``, ``tests/README.md``, and ADR-0008. HF2 keeps the
explicit pin and empties it, which is both environment-independent and the
accepted policy.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from tests.network_guard.guarded_child import run_guarded_python

REPO_ROOT = Path(__file__).resolve().parents[2]

# Environments the profile must be identical across. The two CI variables are
# the ones Hypothesis inspects; a hosted GitHub Actions runner sets both.
ENVIRONMENTS: tuple[tuple[str, dict[str, str]], ...] = (
    ("CI unset", {}),
    ("CI=true", {"CI": "true"}),
    ("GITHUB_ACTIONS=true", {"GITHUB_ACTIONS": "true"}),
)

# The settings the project pins deliberately. Every one is asserted, not just
# the health-check field, so a future edit cannot quietly move another of them.
EXPECTED: dict[str, object] = {
    "derandomize": False,
    "database": None,
    "deadline": None,
    "max_examples": 50,
    "print_blob": False,
    "suppress_health_check": [],
}

_PROBE = """
import json, sys
sys.path.insert(0, {tests!r})
sys.path.insert(0, {root!r})
import conftest  # registers the profile exactly as pytest does
from hypothesis import settings

profile = settings.get_profile("greenmachine-ci")
print(json.dumps({{
    "derandomize": profile.derandomize,
    "database": None if profile.database is None else repr(profile.database),
    "deadline": None if profile.deadline is None else repr(profile.deadline),
    "max_examples": profile.max_examples,
    "print_blob": profile.print_blob,
    "suppress_health_check": sorted(str(h) for h in profile.suppress_health_check),
}}))
"""


def _profile_under(environment: dict[str, str]) -> dict[str, object]:
    """Register the profile in a fresh interpreter and read it back."""
    child = dict(os.environ)
    # Clear both signals first so the parent's own environment cannot leak in
    # and make a case pass for the wrong reason.
    child.pop("CI", None)
    child.pop("GITHUB_ACTIONS", None)
    child.update(environment)

    source = _PROBE.format(tests=str(REPO_ROOT / "tests"), root=str(REPO_ROOT))
    # Through the centralized guarded launcher, so the network guard is
    # installed in the child like every other Python subprocess this suite
    # spawns (GM-008; an architecture test enforces that `sys.executable`
    # appears in no test file but that launcher).
    completed = run_guarded_python("-c", source, cwd=REPO_ROOT, env=child, check=True)
    parsed: dict[str, object] = json.loads(completed.stdout)
    return parsed


@pytest.mark.parametrize(("label", "environment"), ENVIRONMENTS, ids=[e[0] for e in ENVIRONMENTS])
def test_no_health_check_is_suppressed_in_any_environment(
    label: str, environment: dict[str, str]
) -> None:
    """The accepted ADR-0008 policy, enforced where it can actually be broken."""
    profile = _profile_under(environment)

    assert profile["suppress_health_check"] == [], (
        f"under {label} the profile suppresses {profile['suppress_health_check']}; "
        f"GreenMachine keeps every health check active in every environment"
    )


@pytest.mark.parametrize(("label", "environment"), ENVIRONMENTS, ids=[e[0] for e in ENVIRONMENTS])
def test_every_pinned_setting_survives_each_environment(
    label: str, environment: dict[str, str]
) -> None:
    """Not only the health-check field: the whole deliberate configuration."""
    profile = _profile_under(environment)

    assert profile == EXPECTED, f"the profile differs from its declared settings under {label}"


def test_the_profile_is_byte_identical_across_all_three_environments() -> None:
    """The property that matters, stated directly rather than case by case.

    Three separate equalities against a constant could all hold while the
    environments still differed from one another if the constant were wrong.
    Comparing them to each other closes that gap.
    """
    dumps = {label: _profile_under(environment) for label, environment in ENVIRONMENTS}
    reference_label, reference = next(iter(dumps.items()))

    for label, profile in dumps.items():
        assert profile == reference, (
            f"the profile under {label} differs from the profile under {reference_label}: "
            f"{profile} vs {reference}"
        )


def test_meta_the_probe_would_notice_an_environment_dependent_profile() -> None:
    """Anti-vacuity: prove the subprocess seam can see the defect it guards.

    An UNSPECIFIED ``suppress_health_check`` is exactly the pre-HF1 shape. It
    must resolve differently between a bare environment and a CI one -- if this
    ever stops being true the guards above are measuring nothing, and the day
    Hypothesis changes that behaviour this test is the one that says so.
    """
    source = (
        "import json, os\n"
        "from hypothesis import settings\n"
        "settings.register_profile('probe_unspecified', max_examples=50)\n"
        "print(json.dumps(sorted(str(h) for h in "
        "settings.get_profile('probe_unspecified').suppress_health_check)))\n"
    )

    def run(environment: dict[str, str]) -> list[str]:
        child = dict(os.environ)
        child.pop("CI", None)
        child.pop("GITHUB_ACTIONS", None)
        child.update(environment)
        completed = run_guarded_python("-c", source, env=child, check=True)
        result: list[str] = json.loads(completed.stdout)
        return result

    bare = run({})
    hosted = run({"CI": "true"})

    assert bare == [], "an unspecified profile should suppress nothing off-CI"
    assert hosted != bare, (
        "an unspecified profile no longer varies with CI; the inheritance this "
        "suite guards against may have changed in Hypothesis, and the guards "
        "above should be re-examined rather than trusted"
    )
