"""Meta-tests for the suite-wide network block installed by ``tests/conftest.py``.

Each attempt below is a syntactically valid, would-be-real connection call.
None of them reaches the operating system: the autouse session guard raises
before any name resolution or system call, which is exactly what these tests
prove. No real external request is ever made.
"""

from __future__ import annotations

import os
import socket
import subprocess
from pathlib import Path

import pytest
from tests.network_guard.guarded_child import run_guarded_python

BLOCK_MESSAGE = "network access is prohibited in tests"

# 192.0.2.0/24 and 2001:db8::/32 are documentation-only address ranges; even if
# the guard failed, nothing routable is addressed. The guard raises first.
IPV4_TARGET = ("192.0.2.1", 80)
IPV6_TARGET = ("2001:db8::1", 80)
IPV4_UDP_TARGET = ("192.0.2.1", 9)
IPV6_UDP_TARGET = ("2001:db8::1", 9)


def test_direct_ipv4_connect_is_blocked_immediately() -> None:
    with (
        socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate,
        pytest.raises(RuntimeError, match=BLOCK_MESSAGE),
    ):
        candidate.connect(IPV4_TARGET)


def test_direct_ipv6_connect_is_blocked_immediately() -> None:
    with (
        socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as candidate,
        pytest.raises(RuntimeError, match=BLOCK_MESSAGE),
    ):
        candidate.connect(IPV6_TARGET)


def test_connect_ex_is_blocked_rather_than_returning_an_error_code() -> None:
    with (
        socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate,
        pytest.raises(RuntimeError, match=BLOCK_MESSAGE),
    ):
        candidate.connect_ex(IPV4_TARGET)


def test_helper_based_connection_is_blocked() -> None:
    with pytest.raises(RuntimeError, match=BLOCK_MESSAGE):
        socket.create_connection(IPV4_TARGET)


def test_blocking_happens_before_any_dns_resolution() -> None:
    """A hostname connect fails with the block message, not a DNS error.

    If any resolution were attempted first, this reserved ``.invalid`` name
    would raise ``socket.gaierror`` instead of the guard's message.
    """
    with pytest.raises(RuntimeError, match=BLOCK_MESSAGE):
        socket.create_connection(("greenmachine-test.invalid", 80))


def test_the_failure_message_states_the_policy() -> None:
    with (
        socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate,
        pytest.raises(RuntimeError, match="prohibited in tests") as failure,
    ):
        candidate.connect(IPV4_TARGET)
    assert "GM-008" in str(failure.value)


def test_socket_objects_can_still_be_created_and_closed() -> None:
    """Only network operations are blocked; local, connection-free use is fine."""
    candidate = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    candidate.close()


# --------------------------------------------------------------------------
# Datagram paths
# --------------------------------------------------------------------------


def test_ipv4_udp_sendto_is_blocked_before_any_packet() -> None:
    with (
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as candidate,
        pytest.raises(RuntimeError, match=BLOCK_MESSAGE),
    ):
        candidate.sendto(b"synthetic", IPV4_UDP_TARGET)


@pytest.mark.skipif(not socket.has_ipv6, reason="IPv6 is unavailable on this platform")
def test_ipv6_udp_sendto_is_blocked_before_any_packet() -> None:
    with (
        socket.socket(socket.AF_INET6, socket.SOCK_DGRAM) as candidate,
        pytest.raises(RuntimeError, match=BLOCK_MESSAGE),
    ):
        candidate.sendto(b"synthetic", IPV6_UDP_TARGET)


@pytest.mark.skipif(
    not hasattr(socket.socket, "sendmsg"), reason="sendmsg is unavailable on this platform"
)
def test_sendmsg_is_blocked_where_available() -> None:
    with (
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as candidate,
        pytest.raises(RuntimeError, match=BLOCK_MESSAGE),
    ):
        candidate.sendmsg([b"synthetic"], [], 0, IPV4_UDP_TARGET)


# --------------------------------------------------------------------------
# Resolver paths
# --------------------------------------------------------------------------


def test_getaddrinfo_is_blocked() -> None:
    with pytest.raises(RuntimeError, match=BLOCK_MESSAGE):
        socket.getaddrinfo("greenmachine-test.invalid", 80)


def test_gethostbyname_is_blocked() -> None:
    with pytest.raises(RuntimeError, match=BLOCK_MESSAGE):
        socket.gethostbyname("greenmachine-test.invalid")


def test_gethostbyname_ex_is_blocked() -> None:
    with pytest.raises(RuntimeError, match=BLOCK_MESSAGE):
        socket.gethostbyname_ex("greenmachine-test.invalid")


def test_gethostbyaddr_is_blocked() -> None:
    with pytest.raises(RuntimeError, match=BLOCK_MESSAGE):
        socket.gethostbyaddr("192.0.2.1")


# --------------------------------------------------------------------------
# Child Python processes inherit an equivalent guard
# --------------------------------------------------------------------------


def _run_child(program: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Run a guarded child interpreter (the suite's approved launch mechanism)."""
    return run_guarded_python("-c", program, env=env, timeout=120)


def test_the_secondary_sitecustomize_defense_is_arranged_on_pythonpath() -> None:
    """The session prepends tests/network_guard for the secondary sitecustomize shim.

    Secondary defense only: the primary mechanism is the explicit
    ``child_bootstrap.py`` every guarded child runs through, which does not
    depend on PYTHONPATH at all (proven below).
    """
    pythonpath = os.environ.get("PYTHONPATH")
    assert pythonpath is not None
    assert "network_guard" in pythonpath.split(os.pathsep)[0]


def test_child_python_create_connection_is_blocked() -> None:
    completed = _run_child(
        "import socket\nsocket.create_connection(('192.0.2.1', 80), timeout=5)\n"
    )
    assert completed.returncode != 0
    assert BLOCK_MESSAGE in completed.stderr
    assert "child-process guard" in completed.stderr


def test_child_python_udp_sendto_is_blocked() -> None:
    completed = _run_child(
        "import socket\n"
        "with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as candidate:\n"
        "    candidate.sendto(b'synthetic', ('192.0.2.1', 9))\n"
    )
    assert completed.returncode != 0
    assert BLOCK_MESSAGE in completed.stderr


def test_child_python_resolution_is_blocked() -> None:
    completed = _run_child("import socket\nsocket.gethostbyname('greenmachine-test.invalid')\n")
    assert completed.returncode != 0
    assert BLOCK_MESSAGE in completed.stderr


def test_ordinary_child_python_computation_still_succeeds() -> None:
    completed = _run_child("print(6 * 7)")
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "42"


def test_child_filesystem_access_remains_available(tmp_path: Path) -> None:
    completed = run_guarded_python(
        "-c",
        "from pathlib import Path\n"
        "Path('probe.txt').write_text('synthetic-ok', encoding='utf-8')\n"
        "print(Path('probe.txt').read_text(encoding='utf-8'))\n",
        cwd=tmp_path,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "synthetic-ok"
    assert (tmp_path / "probe.txt").read_text(encoding="utf-8") == "synthetic-ok"


# --------------------------------------------------------------------------
# Portability: the child guard survives hostile sitecustomize arrangements
# --------------------------------------------------------------------------


def _environment_without_pythonpath() -> dict[str, str]:
    """Environment A: no sitecustomize of ours is reachable at all."""
    return {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}


# The GreenMachine secondary shim, for origin comparison. The regression never
# requires a *specific* competitor to win the ``sitecustomize`` slot — some
# hosts load their own sitecustomize before every PYTHONPATH entry — it only
# requires that whichever module holds the slot is NOT this shim, and that the
# explicit bootstrap guards regardless.
_GREENMACHINE_SHIM = (
    Path(__file__).resolve().parents[3] / "tests" / "network_guard" / "sitecustomize.py"
)

_COMPETING_SITECUSTOMIZE = (
    '"""Temporary competing sitecustomize for the GreenMachine portability regression."""\n'
)

# Reports which module, if any, holds the ``sitecustomize`` slot in the child.
# Only stable information is printed: the module's __spec__.origin (falling
# back to __file__), or <none>. No custom attribute of any competitor is
# consulted — the temporary competitor defines none.
_SITECUSTOMIZE_ORIGIN_PROBE = (
    "import sys\n"
    "module = sys.modules.get('sitecustomize')\n"
    "if module is None:\n"
    "    print('sitecustomize-origin=<none>')\n"
    "else:\n"
    "    spec = getattr(module, '__spec__', None)\n"
    "    origin = getattr(spec, 'origin', None) or getattr(module, '__file__', None)\n"
    "    print('sitecustomize-origin=' + (origin or '<unknown>'))\n"
)


def _reported_sitecustomize_origin(stdout: str) -> str | None:
    """The origin the probe reported, or None when no sitecustomize loaded."""
    lines = [line for line in stdout.splitlines() if line.startswith("sitecustomize-origin=")]
    assert lines, f"the probe did not report a sitecustomize origin:\n{stdout}"
    value = lines[-1].split("=", 1)[1]
    return None if value == "<none>" else value


def _is_greenmachine_shim(origin: str) -> bool:
    return os.path.normcase(str(Path(origin).resolve())) == os.path.normcase(
        str(_GREENMACHINE_SHIM)
    )


def _assert_foreign_sitecustomize_is_active(stdout: str) -> str:
    """Some sitecustomize holds the slot, and it is not GreenMachine's shim.

    Portable across hosts: the active module may be the temporary supplied
    competitor or a host-provided one that loads even earlier — either
    satisfies the regression contract.
    """
    origin = _reported_sitecustomize_origin(stdout)
    assert origin is not None, "a competing sitecustomize must be active for this regression"
    assert not _is_greenmachine_shim(origin), (
        f"the active sitecustomize is GreenMachine's own shim ({origin}); the regression "
        f"requires a non-GreenMachine competitor to hold the slot"
    )
    return origin


def _environment_with_supplied_competitor(
    directory: Path, base_environment: dict[str, str] | None = None
) -> dict[str, str]:
    """Environment B: a competing sitecustomize ahead of the GreenMachine dir.

    Python imports at most one module named ``sitecustomize``; putting this
    directory before the GreenMachine guard directory on PYTHONPATH displaces
    the secondary shim. On hosts whose own startup hooks load before every
    PYTHONPATH entry, the host's module wins instead — the regression accepts
    either competitor, because the explicit bootstrap must guard regardless.
    """
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "sitecustomize.py").write_text(_COMPETING_SITECUSTOMIZE, encoding="utf-8")
    environment = dict(os.environ) if base_environment is None else dict(base_environment)
    current = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        str(directory) if current is None else str(directory) + os.pathsep + current
    )
    return environment


def _environment_without_greenmachine_guard_entry() -> dict[str, str]:
    """The session environment with the GreenMachine guard dir off PYTHONPATH.

    Used to detect whether the *host itself* provides a sitecustomize: with our
    directory removed, any module still holding the slot came from the host.
    """
    environment = dict(os.environ)
    current = environment.get("PYTHONPATH")
    if current is not None:
        guard_dir = os.path.normcase(str(_GREENMACHINE_SHIM.parent))
        entries = [
            entry
            for entry in current.split(os.pathsep)
            if entry and os.path.normcase(str(Path(entry).resolve())) != guard_dir
        ]
        if entries:
            environment["PYTHONPATH"] = os.pathsep.join(entries)
        else:
            environment.pop("PYTHONPATH")
    return environment


def test_child_guard_does_not_depend_on_pythonpath_or_sitecustomize() -> None:
    """Environment A: with PYTHONPATH stripped entirely, the bootstrap still guards."""
    completed = _run_child(
        "import socket\nsocket.create_connection(('192.0.2.1', 80), timeout=5)\n",
        env=_environment_without_pythonpath(),
    )
    assert completed.returncode != 0
    assert BLOCK_MESSAGE in completed.stderr


def test_a_foreign_sitecustomize_is_active_and_cannot_prevent_the_guard(
    tmp_path: Path,
) -> None:
    environment = _environment_with_supplied_competitor(tmp_path)

    loaded = _run_child(_SITECUSTOMIZE_ORIGIN_PROBE, env=environment)
    assert loaded.returncode == 0, loaded.stderr
    _assert_foreign_sitecustomize_is_active(loaded.stdout)

    tcp = _run_child(
        _SITECUSTOMIZE_ORIGIN_PROBE
        + "import socket\nsocket.create_connection(('192.0.2.1', 80), timeout=5)\n",
        env=environment,
    )
    assert tcp.returncode != 0
    _assert_foreign_sitecustomize_is_active(tcp.stdout)
    assert BLOCK_MESSAGE in tcp.stderr


def test_competing_sitecustomize_child_udp_sendto_is_blocked(tmp_path: Path) -> None:
    environment = _environment_with_supplied_competitor(tmp_path)
    completed = _run_child(
        "import socket\n"
        "with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as candidate:\n"
        "    candidate.sendto(b'synthetic', ('192.0.2.1', 9))\n",
        env=environment,
    )
    assert completed.returncode != 0
    assert BLOCK_MESSAGE in completed.stderr


def test_competing_sitecustomize_child_resolution_is_blocked(tmp_path: Path) -> None:
    environment = _environment_with_supplied_competitor(tmp_path)
    completed = _run_child(
        "import socket\nsocket.gethostbyname('greenmachine-test.invalid')\n",
        env=environment,
    )
    assert completed.returncode != 0
    assert BLOCK_MESSAGE in completed.stderr


def test_computation_and_filesystem_succeed_under_a_competing_sitecustomize(
    tmp_path: Path,
) -> None:
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    environment = _environment_with_supplied_competitor(tmp_path / "competitor-dir")

    completed = run_guarded_python(
        "-c",
        _SITECUSTOMIZE_ORIGIN_PROBE + "print(6 * 7)\n"
        "from pathlib import Path\n"
        "Path('probe.txt').write_text('synthetic-ok', encoding='utf-8')\n"
        "print(Path('probe.txt').read_text(encoding='utf-8'))\n",
        env=environment,
        cwd=workdir,
        timeout=120,
    )

    assert completed.returncode == 0, completed.stderr
    _assert_foreign_sitecustomize_is_active(completed.stdout)
    assert "42" in completed.stdout
    assert "synthetic-ok" in completed.stdout
    assert (workdir / "probe.txt").read_text(encoding="utf-8") == "synthetic-ok"


def test_host_provided_or_supplied_competitor_cannot_prevent_the_guard(
    tmp_path: Path,
) -> None:
    """The independently observed environment: the competitor may be the host's.

    With the GreenMachine guard directory removed from PYTHONPATH, any module
    still holding the ``sitecustomize`` slot is host-provided and its identity
    is not controlled by GreenMachine — exercise it directly. Where the host
    provides none, the supplied temporary competitor satisfies the same
    contract. Either way the explicit bootstrap must guard, and no assertion
    depends on which competitor won or on any absolute host path.
    """
    environment = _environment_without_greenmachine_guard_entry()
    probe = _run_child(_SITECUSTOMIZE_ORIGIN_PROBE, env=environment)
    assert probe.returncode == 0, probe.stderr

    if _reported_sitecustomize_origin(probe.stdout) is None:
        # No host-provided sitecustomize on this machine: supply the temporary
        # competitor, still without the GreenMachine guard directory reachable.
        environment = _environment_with_supplied_competitor(tmp_path, base_environment=environment)
        probe = _run_child(_SITECUSTOMIZE_ORIGIN_PROBE, env=environment)
        assert probe.returncode == 0, probe.stderr
    _assert_foreign_sitecustomize_is_active(probe.stdout)

    tcp = _run_child(
        "import socket\nsocket.create_connection(('192.0.2.1', 80), timeout=5)\n",
        env=environment,
    )
    assert tcp.returncode != 0
    assert BLOCK_MESSAGE in tcp.stderr

    udp = _run_child(
        "import socket\n"
        "with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as candidate:\n"
        "    candidate.sendto(b'synthetic', ('192.0.2.1', 9))\n",
        env=environment,
    )
    assert udp.returncode != 0
    assert BLOCK_MESSAGE in udp.stderr

    resolution = _run_child(
        "import socket\nsocket.gethostbyname('greenmachine-test.invalid')\n",
        env=environment,
    )
    assert resolution.returncode != 0
    assert BLOCK_MESSAGE in resolution.stderr

    computation = _run_child("print(6 * 7)", env=environment)
    assert computation.returncode == 0, computation.stderr
    assert computation.stdout.strip() == "42"
