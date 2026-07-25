"""Deterministic Hypothesis configuration for the property suite (GM-008).

**Fixed seed: 20260724.** The property suite runs under Hypothesis's supported
pytest seed mechanism — ``--hypothesis-seed=20260724`` is configured explicitly
in ``pyproject.toml`` ``addopts`` — so example generation is driven by
``Random(20260724)``. The value is a stable constant chosen once; it is never
derived from a date, a clock, or an environment variable at runtime.

**Profile: ``greenmachine-ci``** — registered in the root ``tests/conftest.py``
(registration must precede the Hypothesis pytest plugin's option handling;
only the root conftest is imported that early) and loaded here whenever the
property suite runs without an explicit profile selection. Its settings,
asserted by ``tests/property/test_golden_properties.py``:

- ``derandomize=False`` — deliberately, so the explicit fixed seed 20260724 is
  what genuinely drives generation (Hypothesis prefers derandomization over a
  forced seed when both are set).
- ``database=None`` — examples are generated in memory only; no persistent
  example database is written or read.
- ``deadline=None`` — no wall-clock dependence in pass/fail decisions.
- ``max_examples=50`` — an explicit, deliberate example budget.
- No health check is suppressed.

**Deliberate local overrides** (portable, from the repository root):

- another explicit seed::

      pytest tests/property --hypothesis-seed=12345

- the exploratory profile without the CI seed::

      pytest tests/property --hypothesis-profile=greenmachine-exploratory --hypothesis-seed=random

A later ``--hypothesis-seed`` on the command line wins over the ``addopts``
default. The CLI options are the only override paths — this conftest touches
nothing when a profile was explicitly selected, and no environment variable is
consulted.
"""

from __future__ import annotations

import pytest
from hypothesis import settings

CI_PROFILE = "greenmachine-ci"

# The GM-008 fixed property-test seed, mirrored from pyproject addopts.
FIXED_SEED = 20260724

_PROFILE_OPTION = "--hypothesis-profile"
_SEED_OPTION = "--hypothesis-seed"


def pytest_configure(config: pytest.Config) -> None:
    requested = config.getoption(_PROFILE_OPTION)
    if not requested:
        settings.load_profile(CI_PROFILE)


@pytest.fixture(scope="session")
def loaded_hypothesis_profile(pytestconfig: pytest.Config) -> str:
    """The name of the profile this session runs the property suite under."""
    requested = pytestconfig.getoption(_PROFILE_OPTION)
    return str(requested) if requested else CI_PROFILE


@pytest.fixture(scope="session")
def configured_hypothesis_seed(pytestconfig: pytest.Config) -> str | None:
    """The raw ``--hypothesis-seed`` value this session runs under."""
    raw = pytestconfig.getoption(_SEED_OPTION)
    return None if raw is None else str(raw)
