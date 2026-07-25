"""GM-030-r2 deployment-readiness contract for Streamlit Community Cloud.

The hosted app installs the repository-root ``requirements.txt``
automatically, so that file must carry exactly the bounded runtime/UI
dependencies — the project runtime dependencies plus the UI extra — and
never a development tool. The release archive keeps the one outer
``greenmachine/`` directory whose contents become the GitHub repository
root.
"""

from __future__ import annotations

import importlib.util
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
REQUIREMENTS = REPO_ROOT / "requirements.txt"

# The one local editable project-install line (GM-040-HF1): Community Cloud
# installs requirements.txt only, and the app resolves its version from
# installed distribution metadata — so the host must install the project
# itself. This is not a dependency; it is the deployment's self-install.
EDITABLE_SELF_INSTALL = "-e ."

APPROVED_REQUIREMENTS = (
    EDITABLE_SELF_INSTALL,
    "streamlit>=1.32,<2",
    "PyYAML>=6,<7",
    "pydantic>=2,<3",
    "tzdata>=2024.1",
)

_DEV_ONLY_MARKERS = ("pytest", "hypothesis", "ruff", "mypy", "pre-commit", "types-")


def _requirement_lines() -> tuple[str, ...]:
    lines = REQUIREMENTS.read_text(encoding="utf-8").splitlines()
    return tuple(line.strip() for line in lines if line.strip() and not line.startswith("#"))


def test_requirements_txt_sits_beside_the_entrypoint() -> None:
    assert REQUIREMENTS.is_file()
    assert (REPO_ROOT / "streamlit_app.py").is_file()
    assert (REPO_ROOT / ".streamlit" / "config.toml").is_file()
    assert (REPO_ROOT / "evidence" / "gm020_vertical_slice" / "prospective_run").is_dir()


def test_requirements_carry_exactly_the_approved_specifications() -> None:
    """The editable self-install first, then the same four bounded runtime/UI
    dependencies — nothing else."""
    assert _requirement_lines() == APPROVED_REQUIREMENTS


def test_the_editable_self_install_is_present_for_community_cloud() -> None:
    """GM-040-HF1 regression: without `-e .`, the hosted app crashes at import
    with PackageNotFoundError because no greenmachine distribution exists."""
    assert EDITABLE_SELF_INSTALL in _requirement_lines()


def test_requirements_carry_no_dev_or_test_dependency() -> None:
    rendered = " ".join(_requirement_lines()).lower()
    for marker in _DEV_ONLY_MARKERS:
        assert marker not in rendered, marker


def test_requirements_track_the_project_runtime_dependencies_plus_ui() -> None:
    """Dependency drift fails here: beyond the self-install line,
    requirements.txt must equal pyproject's runtime dependencies plus the
    [ui] extra, exactly."""
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    runtime = list(pyproject["project"]["dependencies"])
    ui_extra = list(pyproject["project"]["optional-dependencies"]["ui"])
    dependency_lines = [line for line in _requirement_lines() if line != EDITABLE_SELF_INSTALL]
    assert sorted(dependency_lines) == sorted(runtime + ui_extra)


def test_no_secret_shaped_deployment_file_exists() -> None:
    for pattern in ("secrets.toml", "*.pem", "*.key", ".env"):
        found = [
            path
            for path in REPO_ROOT.rglob(pattern)
            if ".venv" not in path.parts and "cleanvenv" not in path.parts
        ]
        assert found == [], f"secret-shaped file(s) present: {found}"


def test_the_release_archive_ships_requirements_under_the_outer_directory() -> None:
    """The builder's real plan: requirements.txt is included, and every entry
    keeps the intended single greenmachine/ outer directory."""
    spec = importlib.util.spec_from_file_location(
        "build_release_archive", REPO_ROOT / "scripts" / "build_release_archive.py"
    )
    assert spec is not None and spec.loader is not None
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)

    arcnames = [arcname for arcname, _ in builder.release_file_plan()]
    assert "greenmachine/requirements.txt" in arcnames
    assert "greenmachine/streamlit_app.py" in arcnames
    assert "greenmachine/.streamlit/config.toml" in arcnames
    assert all(arcname.startswith("greenmachine/") for arcname in arcnames)


def test_deployment_documentation_names_the_entrypoint_and_requirements() -> None:
    documentation = (REPO_ROOT / "docs" / "STREAMLIT_PROTOTYPE.md").read_text(encoding="utf-8")
    assert "entrypoint | `streamlit_app.py`" in documentation
    assert "streamlit run streamlit_app.py" in documentation
    assert "requirements.txt" in documentation
    assert "automatically" in documentation
    # Community Cloud is never told to install the packaging extra.
    assert ".[ui]" not in documentation
    assert "install `.[ui]`" not in documentation
