"""Shared static-analysis helpers for the architecture tests.

The first version of these guards matched on bare syntax — the literal name
``Decimal``, the literal attribute ``now``, a relative import flattened to an
empty string. All of that is bypassable with ordinary, valid Python: an import
alias, a unary minus, a ``..`` level. The helpers here resolve imports first and
then ask about *canonical* targets, so ``D(0.1)`` and ``Decimal(0.1)`` are the
same finding and ``from ..domain import X`` is visibly an escape.

Every rule is a plain function over an AST plus the module's identity, so the
same code that scans the real tree can be pointed at a seeded snippet with a
synthetic path. That is what makes the meta-tests meaningful.

This is deliberately *not* a general-purpose analyzer. It resolves the direct
syntactic forms a reviewer would actually write and does not attempt type
inference, which would trade these guards' precision for false positives.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Modules whose members we track well enough to resolve aliases.
TRACKED_MODULES = frozenset(
    {"datetime", "decimal", "uuid", "time", "random", "secrets", "builtins", "contextlib"}
)

# (module, member) pairs worth resolving to a canonical dotted name.
TRACKED_MEMBERS = frozenset(
    {
        ("datetime", "datetime"),
        ("datetime", "date"),
        ("decimal", "Decimal"),
        ("decimal", "Context"),
        ("uuid", "uuid1"),
        ("uuid", "uuid3"),
        ("uuid", "uuid4"),
        ("uuid", "uuid5"),
        ("time", "time"),
        ("builtins", "Exception"),
        ("builtins", "BaseException"),
        ("contextlib", "suppress"),
    }
)

# Exception types too broad to catch: they swallow bugs along with the failure
# the handler meant to address (ADR-0007).
BROAD_EXCEPTIONS = frozenset(
    {"Exception", "BaseException", "builtins.Exception", "builtins.BaseException"}
)

# Canonical calls that read wall-clock time. ``datetime.today()`` is a real-time
# read exactly like ``now()`` — it just spells it differently.
CLOCK_READS = frozenset(
    {
        "datetime.datetime.now",
        "datetime.datetime.utcnow",
        "datetime.datetime.today",
        "datetime.date.today",
        "time.time",
    }
)

# Calls that turn a float into a Decimal. Each maps to the keyword names that
# carry the value, so a keyword-only call is inspected too. Positional argument
# zero is always checked.
FLOAT_SINKS: dict[str, tuple[str, ...]] = {
    "decimal.Decimal": ("value",),
    "decimal.Decimal.from_float": ("f",),
    "decimal.Context.create_decimal_from_float": ("f",),
}

# Canonical non-deterministic UUID factories. uuid3/uuid5 are content-derived and
# therefore permitted.
RANDOM_UUIDS = frozenset({"uuid.uuid1", "uuid.uuid4"})

RANDOM_MODULES = frozenset({"random", "secrets"})

# The single approved real-time read in the whole source tree.
APPROVED_CLOCK_MODULE = "greenmachine.common.clock"
APPROVED_CLOCK_SCOPE = "SystemClock.now"

MODULE_SCOPE = "<module>"


# --------------------------------------------------------------------------
# Module identity
# --------------------------------------------------------------------------


def module_qualname(path: Path, src_root: Path) -> str:
    """Dotted module name for a file, e.g. ``greenmachine.common.clock``."""
    relative = path.relative_to(src_root).with_suffix("")
    parts = list(relative.parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def package_of(path: Path, src_root: Path) -> str:
    """Dotted package containing a file.

    For both ``common/numeric.py`` and ``common/__init__.py`` this is
    ``greenmachine.common``: a package's ``__init__`` lives *in* that package, so
    a level-1 relative import resolves against it either way.
    """
    return ".".join(path.relative_to(src_root).parent.parts)


# --------------------------------------------------------------------------
# Imports
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ImportRecord:
    """One import, keeping the relative level rather than discarding it."""

    module: str
    level: int
    names: tuple[str, ...]
    lineno: int

    @property
    def is_relative(self) -> bool:
        return self.level > 0

    @property
    def top_level(self) -> str:
        """Top-level absolute module name, or '' for a relative import."""
        return "" if self.is_relative else self.module.split(".")[0]

    def resolved(self, package: str) -> str:
        """Absolute module this import refers to, given the importing package.

        Mirrors importlib: level 1 resolves against the current package, level 2
        against its parent, and so on. A level that climbs past the root resolves
        to ``''``, which no allowed root ever contains.
        """
        if not self.is_relative:
            return self.module
        parts = package.split(".") if package else []
        keep = len(parts) - (self.level - 1)
        if keep < 0:
            return ""
        base = ".".join(parts[:keep])
        if not self.module:
            return base
        return f"{base}.{self.module}" if base else self.module

    def describe(self, package: str) -> str:
        dots = "." * self.level
        target = f"{dots}{self.module}" if self.is_relative else self.module
        return f"line {self.lineno}: from {target} -> {self.resolved(package) or '<above root>'}"


def collect_imports(tree: ast.AST) -> list[ImportRecord]:
    """Every import in the tree, with module, level, names, and line number."""
    records: list[ImportRecord] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            records.extend(
                ImportRecord(alias.name, 0, (alias.asname or alias.name,), node.lineno)
                for alias in node.names
            )
        elif isinstance(node, ast.ImportFrom):
            records.append(
                ImportRecord(
                    node.module or "",
                    node.level,
                    tuple(alias.asname or alias.name for alias in node.names),
                    node.lineno,
                )
            )
    return records


def within(module: str, root: str) -> bool:
    """True when ``module`` is ``root`` itself or a submodule of it."""
    return module == root or module.startswith(f"{root}.")


def cross_package_offenders(
    tree: ast.AST,
    package: str,
    allowed_root: str,
    *,
    also_allowed: frozenset[str] = frozenset(),
) -> list[ImportRecord]:
    """Imports that leave ``allowed_root``, relative or absolute.

    A relative import is resolved to its absolute target first, so
    ``from ..domain import ComponentId`` inside ``greenmachine.common`` is caught
    even though it never names ``greenmachine`` in the source text.

    ``also_allowed`` names exact modules a specific file is permitted to reach
    outside its root. GM-009 grants exactly one such exception —
    ``greenmachine.domain.errors`` may import ``greenmachine.common.errors`` — and
    it is matched exactly, so ``greenmachine.common`` or
    ``greenmachine.common.logging`` remain forbidden.
    """
    offenders: list[ImportRecord] = []
    for record in collect_imports(tree):
        resolved = record.resolved(package)
        if resolved in also_allowed:
            continue
        if record.is_relative:
            if not within(resolved, allowed_root):
                offenders.append(record)
        elif record.top_level == "greenmachine" and not within(resolved, allowed_root):
            offenders.append(record)
    return offenders


def _resolve_exception_name(node: ast.expr, aliases: Aliases) -> str | None:
    """Canonical name of an exception type named in an ``except`` clause."""
    if isinstance(node, ast.Name):
        return aliases.members.get(node.id, node.id)
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        base = node.value.id
        resolved_base = aliases.modules.get(base, base)
        return f"{resolved_base}.{node.attr}"
    return None


def _breadth_reasons(caught: ast.expr | None, aliases: Aliases) -> list[str]:
    """Why this ``except`` clause is too broad, if it is."""
    if caught is None:
        return ["bare `except:` catches everything, including KeyboardInterrupt"]

    candidates = caught.elts if isinstance(caught, ast.Tuple) else [caught]
    reasons: list[str] = []
    for element in candidates:
        name = _resolve_exception_name(element, aliases)
        if name in BROAD_EXCEPTIONS:
            reasons.append(f"catches {name}")
    return reasons


def _is_literal_expression(node: ast.expr) -> bool:
    """True for an expression that is a literal and cannot have a side effect.

    Recursive and deliberately conservative: a container counts only when every
    element, key, and value is itself literal. So ``()``, ``[]``, ``{}``,
    ``-1``, and ``[1, ("a", 2)]`` all qualify, while ``[recover()]``,
    ``{"result": recover()}``, ``{**other}``, and ``(value := recover())`` do
    not — each of those executes something.

    A bare name is *not* treated as a literal. Evaluating one is side-effect
    free in practice, but leaving it out keeps the rule conservative and avoids
    guessing at code that may be a deliberate reference.
    """
    if isinstance(node, ast.Constant):
        return True

    # Signed numeric literals: -1, +2. `not x` and `~x` are excluded, since the
    # operand there is far more likely to be an executable expression.
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub | ast.UAdd):
        return _is_literal_expression(node.operand)

    if isinstance(node, ast.Tuple | ast.List | ast.Set):
        return all(_is_literal_expression(element) for element in node.elts)

    if isinstance(node, ast.Dict):
        # A ``None`` key marks ``**unpacking``, which evaluates its operand.
        if any(key is None for key in node.keys):
            return False
        return all(
            _is_literal_expression(key) and _is_literal_expression(value)
            for key, value in zip(node.keys, node.values, strict=True)
            if key is not None
        )

    return False


def _is_noop_statement(statement: ast.stmt) -> bool:
    """True for a statement that does nothing at runtime.

    ``pass`` and any literal-only expression — ``...``, a docstring-style
    explanation, ``()``, ``[]``, ``{}``, ``-1`` — evaluate to nothing
    observable. A call, ``raise``, ``return``, or an assignment is not a no-op.
    """
    if isinstance(statement, ast.Pass):
        return True
    return isinstance(statement, ast.Expr) and _is_literal_expression(statement.value)


def _is_effectively_empty(body: list[ast.stmt]) -> bool:
    """True when every statement in the body is a no-op.

    Catches the whole family at once — ``pass``, ``...``, a comment-as-string
    followed by either — instead of only the single-``pass`` spelling.
    """
    return bool(body) and all(_is_noop_statement(statement) for statement in body)


def _exception_arguments(call: ast.Call) -> list[ast.expr]:
    """Exception types named in a call, seeing through literal containers.

    ``suppress(*(ValueError, Exception))`` is the valid API spelling of a
    multi-argument suppression, so a ``Starred`` whose value is a literal tuple
    or list is unpacked and its members inspected individually.

    A starred *variable* — ``suppress(*chosen)`` — is left alone: resolving it
    would need type inference, and guessing is worse than reporting the limit.
    """
    arguments: list[ast.expr] = []
    for argument in call.args:
        inner = argument.value if isinstance(argument, ast.Starred) else argument
        if isinstance(inner, ast.Tuple | ast.List):
            arguments.extend(inner.elts)
        elif not isinstance(argument, ast.Starred):
            arguments.append(inner)
    return arguments


def handler_offenders(tree: ast.AST) -> list[tuple[int, str]]:
    """``except`` clauses that catch too much, or that swallow what they catch.

    ADR-0007 prohibits bare ``except:`` and ``except Exception:`` because they
    turn a bug into a silent wrong answer. Aliased and module-qualified
    spellings resolve to the same canonical names, so renaming the import does
    not evade the rule.

    A handler whose body does nothing is rejected regardless of what it catches:
    catching a failure and discarding it is the swallow the ADR is written
    against, and a string explaining why does not make it observable.

    Specific handlers that actually do something — re-raise, recover, log,
    return a fallback — are permitted.
    """
    aliases = collect_aliases(tree)
    offenders: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        reasons = _breadth_reasons(node.type, aliases)
        if _is_effectively_empty(node.body):
            reasons.append("handler body does nothing, so the failure is swallowed")
        if reasons:
            offenders.append((node.lineno, "; ".join(reasons)))

    return offenders


def broad_suppress_offenders(tree: ast.AST) -> list[tuple[int, str]]:
    """``contextlib.suppress`` calls that discard a broad exception.

    ``with suppress(Exception):`` is ``except Exception: pass`` wearing a nicer
    hat, so the same prohibition applies. Suppressing a *specific* exception is
    permitted — it is a deliberate, narrow decision.

    Only calls that resolve to ``contextlib.suppress`` are considered, so an
    unrelated helper of the same name is never flagged.
    """
    aliases = collect_aliases(tree)
    offenders: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if resolve_call_target(node.func, aliases) != "contextlib.suppress":
            continue
        broad = [
            name
            for argument in _exception_arguments(node)
            if (name := _resolve_exception_name(argument, aliases)) in BROAD_EXCEPTIONS
        ]
        if broad:
            offenders.append(
                (node.lineno, f"contextlib.suppress discards {', '.join(sorted(set(broad)))}")
            )

    return offenders


def broad_exception_offenders(tree: ast.AST) -> list[tuple[int, str]]:
    """Every way a failure can be caught too broadly or silently discarded.

    The union of :func:`handler_offenders` and
    :func:`broad_suppress_offenders`, sorted by line, so one call covers
    ADR-0007's no-swallowed-exception policy for a whole file.
    """
    return sorted(handler_offenders(tree) + broad_suppress_offenders(tree))


def third_party_offenders(tree: ast.AST) -> list[ImportRecord]:
    """Absolute imports that are neither standard library nor GreenMachine.

    Uses ``sys.stdlib_module_names`` rather than a hand-maintained deny list, so
    an unlisted package such as ``scipy`` is caught by default instead of only
    the handful somebody remembered to enumerate. It is a static name set, so the
    result does not depend on what happens to be installed.
    """
    offenders: list[ImportRecord] = []
    for record in collect_imports(tree):
        if record.is_relative:
            continue  # relative imports are the cross-package rule's business
        top = record.top_level
        if not top or top == "__future__" or top == "greenmachine":
            continue
        if top in sys.stdlib_module_names:
            continue
        offenders.append(record)
    return offenders


def io_module_offenders(tree: ast.AST, forbidden: frozenset[str]) -> list[ImportRecord]:
    """Standard-library modules a package is separately forbidden to touch.

    Distinct from the third-party rule: ``pathlib`` *is* standard library, and is
    still not allowed in ``common``.
    """
    return [
        record
        for record in collect_imports(tree)
        if not record.is_relative and record.top_level in forbidden
    ]


# --------------------------------------------------------------------------
# Alias resolution
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Aliases:
    """Local names bound to tracked modules and members."""

    modules: dict[str, str] = field(default_factory=dict)
    members: dict[str, str] = field(default_factory=dict)


def collect_aliases(tree: ast.AST) -> Aliases:
    """Map local names to canonical modules/members, honouring ``as`` clauses."""
    modules: dict[str, str] = {}
    members: dict[str, str] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in TRACKED_MODULES:
                    modules[alias.asname or alias.name] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            for alias in node.names:
                if (node.module, alias.name) in TRACKED_MEMBERS:
                    members[alias.asname or alias.name] = f"{node.module}.{alias.name}"
                elif alias.name in TRACKED_MODULES and node.module == "":
                    modules[alias.asname or alias.name] = alias.name

    return Aliases(modules, members)


def resolve_call_target(func: ast.expr, aliases: Aliases) -> str | None:
    """Canonical dotted name a call's callee refers to, if it is tracked.

    Handles ``Decimal(...)``, ``D(...)``, ``dec.Decimal(...)``,
    ``Decimal.from_float(...)``, ``datetime.now()``, ``dt.today()``,
    ``datetime_module.datetime.now()``, and — by resolving through an
    instantiation — ``Context().create_decimal_from_float(...)``.

    Returns ``None`` for anything not reachable from a tracked import, which is
    what keeps an unrelated ``obj.from_float(0.1)`` from being flagged.
    """
    if isinstance(func, ast.Name):
        return aliases.members.get(func.id)

    if isinstance(func, ast.Attribute):
        base = func.value

        if isinstance(base, ast.Name):
            if base.id in aliases.modules:
                return f"{aliases.modules[base.id]}.{func.attr}"
            if base.id in aliases.members:
                return f"{aliases.members[base.id]}.{func.attr}"

        elif isinstance(base, ast.Attribute) and isinstance(base.value, ast.Name):
            if base.value.id in aliases.modules:
                return f"{aliases.modules[base.value.id]}.{base.attr}.{func.attr}"

        elif isinstance(base, ast.Call):
            # A method on a freshly constructed object: resolve the constructor,
            # then hang the method name off it. Covers Context().create_...().
            constructed = resolve_call_target(base.func, aliases)
            if constructed is not None:
                return f"{constructed}.{func.attr}"

    return None


# --------------------------------------------------------------------------
# Scopes
# --------------------------------------------------------------------------


def scoped_calls(tree: ast.AST) -> list[tuple[ast.Call, str]]:
    """Every call paired with its enclosing ``Class.method`` scope."""
    found: list[tuple[ast.Call, str]] = []

    def walk(node: ast.AST, scope: tuple[str, ...]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
                nested = (*scope, child.name)
            else:
                nested = scope
            if isinstance(child, ast.Call):
                found.append((child, ".".join(scope) if scope else MODULE_SCOPE))
            walk(child, nested)

    walk(tree, ())
    return found


# --------------------------------------------------------------------------
# Rules
# --------------------------------------------------------------------------


def clock_reads(tree: ast.AST) -> list[tuple[str, int]]:
    """Every wall-clock read, as ``(scope, lineno)``, alias-aware."""
    aliases = collect_aliases(tree)
    return [
        (scope, call.lineno)
        for call, scope in scoped_calls(tree)
        if resolve_call_target(call.func, aliases) in CLOCK_READS
    ]


def clock_policy_violations(tree: ast.AST, module: str) -> list[str]:
    """Enforce that the only real-time read is SystemClock.now in the approved file.

    The exemption is bound to the module *and* the scope, so a class called
    ``SystemClock`` in ``scoring/fake.py`` gets no exemption, and a second read
    inside the approved file — even in the approved method — is a violation.
    """
    reads = clock_reads(tree)

    if module != APPROVED_CLOCK_MODULE:
        return [f"{scope} (line {line})" for scope, line in reads]

    violations = [
        f"{scope} (line {line})" for scope, line in reads if scope != APPROVED_CLOCK_SCOPE
    ]
    if len(reads) != 1:
        violations.append(f"expected exactly one real-time read in {module}, found {len(reads)}")
    return violations


def _is_definite_float(node: ast.expr) -> bool:
    """True for a float literal, a signed float literal, or ``float(...)``."""
    if isinstance(node, ast.Constant) and isinstance(node.value, float):
        return True
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub | ast.UAdd):
        return _is_definite_float(node.operand)
    return bool(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "float"
    )


def decimal_from_float_offenders(tree: ast.AST) -> list[int]:
    """Lines building a Decimal from a definite float, through any tracked route.

    Covers every direct API that converts a float: the constructor (positional or
    ``value=``), ``Decimal.from_float``, and
    ``Context().create_decimal_from_float`` — each through plain, aliased, and
    module-qualified spellings.

    Only calls whose callee resolves to a tracked target are inspected, so an
    unrelated function taking a ``value=`` keyword, or an unknown object's own
    ``from_float`` method, is never flagged.
    """
    aliases = collect_aliases(tree)
    offenders: list[int] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = resolve_call_target(node.func, aliases)
        if target not in FLOAT_SINKS:
            continue

        value_keywords = FLOAT_SINKS[target]
        candidates: list[ast.expr] = list(node.args[:1])
        candidates.extend(
            keyword.value for keyword in node.keywords if keyword.arg in value_keywords
        )

        if any(_is_definite_float(candidate) for candidate in candidates):
            offenders.append(node.lineno)

    return offenders


def uuid_offenders(tree: ast.AST) -> list[int]:
    """Lines calling a non-deterministic UUID factory, through any alias."""
    aliases = collect_aliases(tree)
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and resolve_call_target(node.func, aliases) in RANDOM_UUIDS
    ]


def random_offenders(tree: ast.AST) -> list[str]:
    """Imports of randomness sources."""
    return [
        record.module
        for record in collect_imports(tree)
        if not record.is_relative and record.top_level in RANDOM_MODULES
    ]


def float_annotation_offenders(tree: ast.AST) -> list[int]:
    """Lines annotating anything as ``float``."""
    offenders: list[int] = []
    for node in ast.walk(tree):
        annotation = getattr(node, "annotation", None) or getattr(node, "returns", None)
        if annotation is None:
            continue
        offenders.extend(
            sub.lineno
            for sub in ast.walk(annotation)
            if isinstance(sub, ast.Name) and sub.id == "float"
        )
    return offenders
