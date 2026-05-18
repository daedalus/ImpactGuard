"""Semantic behavior analysis for Python functions.

Provides deeper analysis beyond signature-level compatibility by examining
function bodies to detect:

- **Async/generator changes** – sync↔async and regular↔generator shifts that
  break calling conventions without any signature change.
- **Exception contracts** – the set of exception types a function explicitly
  raises.  Adding a new exception type is a potential breaking change for
  callers that catch specific exceptions.
- **Side effects** – file I/O, stdout writes, OS/subprocess calls, network
  calls, global-state mutation, and ``self`` attribute mutation.  Gaining or
  losing a side effect often indicates a behavioral contract change.
- **Return-value semantics** – whether a function always implicitly returns
  ``None`` (no ``return value``).  Changing this is a structural semantic
  shift.
- **Docstring contracts** – changes to the docstring text are used as a
  lightweight proxy for documented contract changes (e.g. updated invariants,
  preconditions, or ``Raises`` sections).

Public API
----------
:func:`analyze_behavior`
    Extract behavioral traits for all functions in a list of Python files.

:func:`compare_behavior`
    Compare two behavioral snapshots and return semantic change lists.

:data:`SEMANTIC_SEVERITY`
    Severity scores for semantic change types (mirrors ``SEVERITY_SCORES``
    in :mod:`risk_model`).
"""

import ast
import hashlib
from pathlib import Path
from typing import Any

from ._logging import get_logger

_log = get_logger(__name__)

# ── Severity scores for semantic change types ─────────────────────────────────

#: Severity scores for semantic (behavioral) change types.
#:
#: These supplement the signature-level ``SEVERITY_SCORES`` in
#: :mod:`risk_model`.  Values follow the same 0.0–1.0 calibration:
#:
#: * **ASYNC_CHANGED** (0.8) – sync↔async shift breaks every caller; awaiting
#:   a non-coroutine or calling a coroutine without ``await`` both cause
#:   immediate ``TypeError``/``RuntimeWarning`` at runtime.
#: * **YIELD_REMOVED** (0.8) – generator→regular; ``for x in func()`` callers
#:   break because the return value is no longer iterable in the expected way.
#: * **YIELD_ADDED** (0.7) – regular→generator; callers that expected a plain
#:   return value now get a generator object.
#: * **SIDE_EFFECT_ADDED** (0.6) – the function now performs I/O, mutates
#:   global state, or calls external systems.  Callers relying on pure/
#:   idempotent behaviour may break.
#: * **EXCEPTION_ADDED** (0.5) – a new exception type may propagate to the
#:   caller.  Callers with fine-grained ``except`` clauses may miss it.
#: * **RETURNS_NONE_CHANGED** (0.5) – a function that previously returned
#:   a meaningful value now always returns ``None``, or vice versa.
#: * **SIDE_EFFECT_REMOVED** (0.3) – a side effect the caller may have relied
#:   upon (e.g. writing a cache file) has been removed.
#: * **CONTRACT_CHANGED** (0.3) – the documented contract (docstring) changed,
#:   suggesting a behavioural shift that may not be captured by other signals.
#: * **EXCEPTION_REMOVED** (0.2) – an exception is no longer raised; callers
#:   with a dead ``except`` clause are unaffected at runtime.
SEMANTIC_SEVERITY: dict[str, float] = {
    "ASYNC_CHANGED": 0.8,
    "YIELD_REMOVED": 0.8,
    "YIELD_ADDED": 0.7,
    "SIDE_EFFECT_ADDED": 0.6,
    "EXCEPTION_ADDED": 0.5,
    "RETURNS_NONE_CHANGED": 0.5,
    "SIDE_EFFECT_REMOVED": 0.3,
    "CONTRACT_CHANGED": 0.3,
    "CONTRACT_REMOVED": 0.2,
    "EXCEPTION_REMOVED": 0.2,
}

# ── Internal AST visitor ──────────────────────────────────────────────────────

#: Call prefixes/names that indicate file-I/O side effects.
_FILE_IO_NAMES = frozenset({"open", "io.open", "os.open", "builtins.open", "pathlib.Path.open"})

#: Call names that write to stdout/stderr.
_PRINT_NAMES = frozenset({"print", "sys.stdout.write", "sys.stderr.write"})

#: Call prefixes that indicate OS / subprocess interaction.
_OS_PREFIXES = ("os.", "subprocess.", "shutil.", "tempfile.")

#: Call prefixes that indicate network interaction.
_NET_PREFIXES = ("socket.", "urllib.", "requests.", "http.", "httpx.", "aiohttp.", "grpc.")

#: Call prefixes/names that indicate logging side effects.
_LOG_PREFIXES = ("logging.", "_log.", "log.", "logger.")


class _BehaviorVisitor(ast.NodeVisitor):
    """AST visitor that collects behavioral traits from a single function body.

    The visitor is intentionally **shallow**: it does not recurse into nested
    function definitions (``def``/``async def``) or class definitions, so each
    function is analysed in isolation.
    """

    def __init__(self) -> None:
        self.raises: set[str] = set()
        self.side_effects: set[str] = set()
        self.has_yield: bool = False
        self._return_has_value: list[bool] = []

    # ── Recursion guards ──────────────────────────────────────────────────────

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Do not recurse into nested function definitions."""

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Do not recurse into nested async function definitions."""

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Do not recurse into nested class definitions."""

    # ── Exception detection ───────────────────────────────────────────────────

    def visit_Raise(self, node: ast.Raise) -> None:
        if node.exc is not None:
            try:
                exc_str = ast.unparse(node.exc).strip()
                # Normalise: "ValueError('msg')" → "ValueError"
                if "(" in exc_str:
                    exc_type = exc_str[: exc_str.index("(")].strip()
                else:
                    exc_type = exc_str
                if exc_type:
                    self.raises.add(exc_type)
            except Exception:
                pass
        self.generic_visit(node)

    # ── Side-effect detection ─────────────────────────────────────────────────

    def visit_Call(self, node: ast.Call) -> None:
        try:
            call_str = ast.unparse(node.func).strip()
            if call_str in _FILE_IO_NAMES:
                self.side_effects.add("file_io")
            elif call_str in _PRINT_NAMES:
                self.side_effects.add("stdout_write")
            elif any(call_str.startswith(p) for p in _OS_PREFIXES):
                self.side_effects.add("os_call")
            elif any(call_str.startswith(p) for p in _NET_PREFIXES):
                self.side_effects.add("network_call")
            elif any(call_str.startswith(p) for p in _LOG_PREFIXES):
                self.side_effects.add("logging")
        except Exception:
            pass
        self.generic_visit(node)

    # ── Generator detection ───────────────────────────────────────────────────

    def visit_Yield(self, node: ast.Yield) -> None:
        self.has_yield = True
        self.generic_visit(node)

    def visit_YieldFrom(self, node: ast.YieldFrom) -> None:
        self.has_yield = True
        self.generic_visit(node)

    # ── Return-value semantics ────────────────────────────────────────────────

    def visit_Return(self, node: ast.Return) -> None:
        has_value = node.value is not None and not (
            isinstance(node.value, ast.Constant) and node.value.value is None
        )
        self._return_has_value.append(has_value)
        self.generic_visit(node)

    # ── Global / self mutation ────────────────────────────────────────────────

    def visit_Global(self, node: ast.Global) -> None:
        self.side_effects.add("global_mutation")
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            if isinstance(target, ast.Attribute) and isinstance(
                target.value, ast.Name
            ) and target.value.id == "self":
                self.side_effects.add("self_mutation")
                break
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        if (
            isinstance(node.target, ast.Attribute)
            and isinstance(node.target.value, ast.Name)
            and node.target.value.id == "self"
        ):
            self.side_effects.add("self_mutation")
        self.generic_visit(node)

    # ── Derived property ──────────────────────────────────────────────────────

    @property
    def always_returns_none(self) -> bool:
        """True when the function has no ``return <value>`` statements."""
        return not any(self._return_has_value)


# ── Helper utilities ──────────────────────────────────────────────────────────


def _extract_docstring(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """Return the function's docstring, or *None* when absent."""
    if (
        node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    ):
        return node.body[0].value.value
    return None


def _hash_docstring(docstring: str | None) -> str | None:
    """Return an 8-character MD5 hex digest of *docstring*, or *None*."""
    if docstring is None:
        return None
    return hashlib.md5(docstring.strip().encode()).hexdigest()[:8]  # noqa: S324


def _analyze_function_body(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> dict[str, Any]:
    """Extract behavioral traits from a single function AST node.

    Args:
        node: The function definition node to analyse.

    Returns:
        Dict with keys: ``raises``, ``side_effects``, ``has_yield``,
        ``is_async``, ``always_returns_none``, ``docstring_hash``.
    """
    visitor = _BehaviorVisitor()
    for child in node.body:
        visitor.visit(child)

    return {
        "raises": sorted(visitor.raises),
        "side_effects": sorted(visitor.side_effects),
        "has_yield": visitor.has_yield,
        "is_async": isinstance(node, ast.AsyncFunctionDef),
        "always_returns_none": visitor.always_returns_none,
        "docstring_hash": _hash_docstring(_extract_docstring(node)),
    }


# ── Public API ────────────────────────────────────────────────────────────────


def analyze_behavior(
    files: list[str],
    base_path: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Extract behavioral traits from Python source files.

    Analyses each function body in *files* using Python's ``ast`` module to
    detect exception contracts, side effects, generator/async nature, return
    semantics, and docstring contracts.

    Args:
        files: List of Python source file paths to analyse.
        base_path: Optional root directory used to make ``fqname`` keys
            relative (same semantics as
            :func:`~impactguard.extract_signatures.extract`).  When *None*
            the filename (without directory) is used, matching the default
            behaviour of the signature extractor.

    Returns:
        Dict mapping ``fqname`` (e.g. ``"module.py:ClassName.method"``) to a
        behavioral-traits dict containing:

        * ``raises``            – ``list[str]`` of exception type names
          explicitly raised in the function body.
        * ``side_effects``      – ``list[str]`` of detected side-effect
          categories: ``file_io``, ``stdout_write``, ``os_call``,
          ``network_call``, ``logging``, ``global_mutation``,
          ``self_mutation``.
        * ``has_yield``         – ``bool``: *True* when the function contains
          a ``yield`` or ``yield from`` statement.
        * ``is_async``          – ``bool``: *True* for ``async def``
          functions.
        * ``always_returns_none`` – ``bool``: *True* when the function has no
          ``return <non-None value>`` statement.
        * ``docstring_hash``    – ``str | None``: 8-char hex digest of the
          stripped docstring (change detection proxy).
    """
    result: dict[str, dict[str, Any]] = {}

    _log.debug("Analyzing behavior of %d file(s)", len(files))

    for f in files:
        path = Path(f)
        try:
            source_text = path.read_text()
            tree = ast.parse(source_text)
        except Exception as exc:
            _log.warning("Skipping '%s' in behavior analysis: %s", path, exc)
            continue

        # Build the fqname file prefix using the same logic as extract_signatures
        if base_path is not None:
            try:
                fq_file = str(path.relative_to(base_path))
            except ValueError:
                fq_file = path.name
        else:
            fq_file = path.name

        class _FileVisitor(ast.NodeVisitor):
            def __init__(self) -> None:
                self.current_class: str | None = None

            def visit_ClassDef(self, node: ast.ClassDef) -> None:
                old = self.current_class
                self.current_class = node.name
                self.generic_visit(node)
                self.current_class = old

            def _process(
                self, node: ast.FunctionDef | ast.AsyncFunctionDef
            ) -> None:
                if self.current_class:
                    fqname = f"{fq_file}:{self.current_class}.{node.name}"
                else:
                    fqname = f"{fq_file}:{node.name}"
                result[fqname] = _analyze_function_body(node)
                # Recurse so nested functions are captured under their own fqnames.
                # _BehaviorVisitor already stops at the function boundary, so
                # each nested function is analysed independently.
                self.generic_visit(node)

            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                self._process(node)

            def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
                self._process(node)

        file_visitor = _FileVisitor()
        file_visitor.visit(tree)
        _log.debug("Analyzed behavior of %d function(s) from '%s'", len(result), path)

    return result


def compare_behavior(
    old: dict[str, dict[str, Any]],
    new: dict[str, dict[str, Any]],
) -> dict[str, list[str]]:
    """Compare two behavioral snapshots and return semantic change lists.

    Only compares functions that exist in **both** snapshots.  Functions
    removed or added are handled by
    :func:`~impactguard.compare_signatures.compare` (``REMOVED`` /
    ``ADDED``).

    Args:
        old: Behavioral traits from the old version (``fqname`` → traits
            dict as returned by :func:`analyze_behavior`).
        new: Behavioral traits from the new version.

    Returns:
        Dict with two keys:

        * ``"semantic_breaking"``    – list of change strings for
          behavioral changes that are likely to break callers.
        * ``"semantic_nonbreaking"`` – list of change strings for behavioral
          shifts that are informational but unlikely to break callers.

        Each change string follows the ``TYPE: fqname [detail]`` pattern used
        throughout ImpactGuard so it can be passed directly to
        :func:`~impactguard.risk_model.get_severity`.
    """
    semantic_breaking: list[str] = []
    semantic_nonbreaking: list[str] = []

    for fqname, old_traits in old.items():
        if fqname not in new:
            continue  # removal handled by compare_signatures

        new_traits = new[fqname]

        # ── Async / sync shift ────────────────────────────────────────────
        if old_traits.get("is_async") != new_traits.get("is_async"):
            old_async = old_traits.get("is_async", False)
            direction = "sync→async" if not old_async else "async→sync"
            semantic_breaking.append(f"ASYNC_CHANGED: {fqname} ({direction})")

        # ── Generator / regular shift ─────────────────────────────────────
        old_yield = old_traits.get("has_yield", False)
        new_yield = new_traits.get("has_yield", False)
        if old_yield and not new_yield:
            semantic_breaking.append(f"YIELD_REMOVED: {fqname}")
        elif not old_yield and new_yield:
            semantic_breaking.append(f"YIELD_ADDED: {fqname}")

        # ── Exception contract changes ────────────────────────────────────
        old_raises = set(old_traits.get("raises", []))
        new_raises = set(new_traits.get("raises", []))

        for exc in sorted(new_raises - old_raises):
            semantic_breaking.append(f"EXCEPTION_ADDED: {fqname} raises {exc}")

        for exc in sorted(old_raises - new_raises):
            semantic_nonbreaking.append(
                f"EXCEPTION_REMOVED: {fqname} no longer raises {exc}"
            )

        # ── Side-effect changes ───────────────────────────────────────────
        old_se = set(old_traits.get("side_effects", []))
        new_se = set(new_traits.get("side_effects", []))

        for se in sorted(new_se - old_se):
            semantic_breaking.append(f"SIDE_EFFECT_ADDED: {fqname} ({se})")

        for se in sorted(old_se - new_se):
            semantic_nonbreaking.append(f"SIDE_EFFECT_REMOVED: {fqname} ({se})")

        # ── Return-value semantics ────────────────────────────────────────
        old_none = old_traits.get("always_returns_none")
        new_none = new_traits.get("always_returns_none")
        if (
            old_none is not None
            and new_none is not None
            and old_none != new_none
        ):
            semantic_breaking.append(f"RETURNS_NONE_CHANGED: {fqname}")

        # ── Docstring contract change ─────────────────────────────────────
        old_doc = old_traits.get("docstring_hash")
        new_doc = new_traits.get("docstring_hash")
        if old_doc is not None and new_doc is not None and old_doc != new_doc:
            semantic_nonbreaking.append(f"CONTRACT_CHANGED: {fqname}")
        elif old_doc is not None and new_doc is None:
            semantic_nonbreaking.append(f"CONTRACT_REMOVED: {fqname}")

    return {
        "semantic_breaking": sorted(set(semantic_breaking)),
        "semantic_nonbreaking": sorted(set(semantic_nonbreaking)),
    }
