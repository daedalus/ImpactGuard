"""TypeScript language extractor for ImpactGuard.

Provides signature and call-site extraction for TypeScript (``.ts``) and
TSX (``.tsx``) source files.

Two extraction backends are supported:

* **tree-sitter** (preferred) — accurate AST-based extraction.  Requires the
  optional ``tree-sitter`` and ``tree-sitter-typescript`` packages::

      pip install "impactguard[languages]"

* **Regex fallback** — lightweight extraction that covers the most common
  patterns without any extra dependencies.  Emits a ``UserWarning`` on first
  use so callers know they are getting best-effort results.

The tree-sitter backend is used automatically whenever the packages are
available at import time.
"""

from __future__ import annotations

import re
import warnings
from pathlib import Path
from typing import Any

# ── Optional tree-sitter dependency ──────────────────────────────────────────

try:
    import tree_sitter_typescript as _ts_lang  # type: ignore[import-untyped]
    from tree_sitter import Language as _TsLanguage
    from tree_sitter import Node as _TsNode
    from tree_sitter import Parser as _TsParser

    _TS_LANGUAGE = _TsLanguage(_ts_lang.language_typescript())
    _TREE_SITTER_AVAILABLE = True
except ImportError:  # pragma: no cover
    _TREE_SITTER_AVAILABLE = False


# ── Tree-sitter helpers ───────────────────────────────────────────────────────


def _make_parser() -> Any:
    """Create a fresh tree-sitter TypeScript parser."""
    parser = _TsParser(_TS_LANGUAGE)
    return parser


def _node_text(node: Any, source: bytes) -> str:
    """Return the UTF-8 text of a tree-sitter node."""
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _child_of_type(node: Any, *types: str) -> Any | None:
    """Return the first direct child whose type is in *types*, or *None*."""
    for child in node.children:
        if child.type in types:
            return child
    return None


def _children_of_type(node: Any, *types: str) -> list[Any]:
    """Return all direct children whose type is in *types*."""
    return [c for c in node.children if c.type in types]


def _decorator_text(decorator_node: Any, source: bytes) -> str:
    """Return the decorator name/call without the leading ``@``."""
    parts = [
        _node_text(child, source)
        for child in decorator_node.children
        if child.type != "@"
    ]
    return "".join(parts)


def _extract_type_annotation(type_annotation_node: Any, source: bytes) -> str | None:
    """Return the text of a ``type_annotation`` node (skipping the ``:`` token)."""
    for child in type_annotation_node.children:
        if child.type != ":":
            return _node_text(child, source).strip()
    return None


def _has_ignore_comment_ts(source_bytes: bytes, lineno_0based: int) -> bool:
    """Return *True* if a ``// impactguard: ignore`` comment appears on or before the node."""
    tag = b"impactguard: ignore"
    lines = source_bytes.split(b"\n")
    for idx in (lineno_0based - 1, lineno_0based):
        if 0 <= idx < len(lines) and tag in lines[idx]:
            return True
    return False


def _parse_formal_params_ts(
    params_node: Any | None,
    source: bytes,
) -> tuple[list[dict[str, Any]], bool]:
    """Parse a ``formal_parameters`` node into positional args and vararg flag.

    Args:
        params_node: Tree-sitter ``formal_parameters`` node, or *None*.
        source: Raw source bytes of the file.

    Returns:
        ``(positional, has_vararg)`` where each positional arg is a dict with
        ``name``, ``has_default``, and ``type`` keys.
    """
    positional: list[dict[str, Any]] = []
    has_vararg = False

    if params_node is None:
        return positional, has_vararg

    for child in params_node.children:
        if child.type == "required_parameter":
            # Check for rest pattern (...name)
            if _child_of_type(child, "rest_pattern") is not None:
                has_vararg = True
                continue
            # Check for default value (= token present)
            has_default = any(c.type == "=" for c in child.children)
            name, type_ = _extract_param_info_ts(child, source)
            positional.append({"name": name, "has_default": has_default, "type": type_})

        elif child.type == "optional_parameter":
            name, type_ = _extract_param_info_ts(child, source)
            positional.append({"name": name, "has_default": True, "type": type_})

    return positional, has_vararg


def _extract_param_info_ts(
    param_node: Any,
    source: bytes,
) -> tuple[str, str | None]:
    """Extract name and type from a parameter node.

    Handles both ``required_parameter`` and ``optional_parameter`` nodes.
    """
    name: str | None = None
    type_: str | None = None

    for child in param_node.children:
        if child.type == "identifier" and name is None:
            name = _node_text(child, source)
        elif child.type == "type_annotation":
            type_ = _extract_type_annotation(child, source)

    return name or "unknown", type_


def _build_sig(
    name: str,
    node: Any,
    source: bytes,
    fq_file: str,
    class_name: str | None,
    exported: bool,
    decorators: list[str],
    is_async: bool,
    params_node: Any | None,
    return_type_node: Any | None,
) -> dict[str, Any]:
    """Build a signature dict from parsed components."""
    positional, has_vararg = _parse_formal_params_ts(params_node, source)

    return_type: str | None = None
    if return_type_node is not None:
        return_type = _extract_type_annotation(return_type_node, source)

    if class_name:
        fqname = f"{fq_file}:{class_name}.{name}"
        display_name = f"{class_name}.{name}"
    else:
        fqname = f"{fq_file}:{name}"
        display_name = name

    return {
        "fqname": fqname,
        "name": display_name,
        "file": fq_file,
        "lineno": node.start_point[0] + 1,
        "end_lineno": node.end_point[0] + 1,
        "positional": positional,
        "kwonly": [],
        "vararg": has_vararg,
        "kwarg": False,
        "class_name": class_name,
        "return_type": return_type,
        "decorators": decorators,
        "is_async": is_async,
        "ignored": _has_ignore_comment_ts(source, node.start_point[0]),
        "exported": exported,
    }


def _process_function_declaration(
    node: Any,
    source: bytes,
    fq_file: str,
    class_name: str | None,
    exported: bool,
    decorators: list[str],
    funcs: list[dict[str, Any]],
) -> None:
    """Extract signature from a ``function_declaration`` node."""
    name: str | None = None
    is_async = False
    params_node = None
    return_type_node = None

    for child in node.children:
        if child.type == "identifier" and name is None:
            name = _node_text(child, source)
        elif child.type == "async":
            is_async = True
        elif child.type == "formal_parameters":
            params_node = child
        elif child.type == "type_annotation":
            return_type_node = child

    if name is None:
        return

    funcs.append(
        _build_sig(
            name,
            node,
            source,
            fq_file,
            class_name,
            exported,
            decorators,
            is_async,
            params_node,
            return_type_node,
        )
    )


def _process_method_definition(
    node: Any,
    source: bytes,
    fq_file: str,
    class_name: str | None,
    exported: bool,
    decorators: list[str],
    funcs: list[dict[str, Any]],
) -> None:
    """Extract signature from a ``method_definition`` node."""
    name: str | None = None
    is_async = False
    params_node = None
    return_type_node = None

    for child in node.children:
        if child.type == "property_identifier" and name is None:
            name = _node_text(child, source)
        elif child.type == "async":
            is_async = True
        elif child.type == "formal_parameters":
            params_node = child
        elif child.type == "type_annotation":
            return_type_node = child

    if name is None:
        return

    funcs.append(
        _build_sig(
            name,
            node,
            source,
            fq_file,
            class_name,
            exported,
            decorators,
            is_async,
            params_node,
            return_type_node,
        )
    )


def _process_arrow_function(
    arrow_node: Any,
    var_name: str,
    source: bytes,
    fq_file: str,
    class_name: str | None,
    exported: bool,
    decorators: list[str],
    funcs: list[dict[str, Any]],
) -> None:
    """Extract signature from an ``arrow_function`` node assigned to a variable."""
    is_async = False
    params_node: Any = None
    return_type_node: Any = None
    single_param_name: str | None = None  # set for single-identifier arrow: x => expr

    for child in arrow_node.children:
        if child.type == "async":
            is_async = True
        elif child.type == "formal_parameters":
            params_node = child
        elif child.type == "type_annotation":
            return_type_node = child
        elif (
            child.type == "identifier"
            and params_node is None
            and return_type_node is None
        ):
            # Single-param arrow without parens: x => expr
            single_param_name = _node_text(child, source)

    if single_param_name is not None:
        # Single identifier param path: build the signature directly
        return_type: str | None = None
        if return_type_node is not None:
            return_type = _extract_type_annotation(return_type_node, source)

        if class_name:
            fqname = f"{fq_file}:{class_name}.{var_name}"
            display_name = f"{class_name}.{var_name}"
        else:
            fqname = f"{fq_file}:{var_name}"
            display_name = var_name

        funcs.append(
            {
                "fqname": fqname,
                "name": display_name,
                "file": fq_file,
                "lineno": arrow_node.start_point[0] + 1,
                "end_lineno": arrow_node.end_point[0] + 1,
                "positional": [
                    {"name": single_param_name, "has_default": False, "type": None}
                ],
                "kwonly": [],
                "vararg": False,
                "kwarg": False,
                "class_name": class_name,
                "return_type": return_type,
                "decorators": decorators,
                "is_async": is_async,
                "ignored": _has_ignore_comment_ts(source, arrow_node.start_point[0]),
                "exported": exported,
            }
        )
    else:
        # Normal path: formal_parameters or no params at all
        funcs.append(
            _build_sig(
                var_name,
                arrow_node,
                source,
                fq_file,
                class_name,
                exported,
                decorators,
                is_async,
                params_node,
                return_type_node,
            )
        )


def _process_class_declaration(
    node: Any,
    source: bytes,
    fq_file: str,
    exported: bool,
    funcs: list[dict[str, Any]],
) -> None:
    """Extract signatures from all methods inside a ``class_declaration`` node."""
    class_name: str | None = None
    for child in node.children:
        if child.type == "type_identifier":
            class_name = _node_text(child, source)
            break

    class_body = _child_of_type(node, "class_body")
    if class_body is None:
        return

    pending_decorators: list[str] = []
    for child in class_body.children:
        if child.type == "decorator":
            pending_decorators.append(_decorator_text(child, source))
        elif child.type == "method_definition":
            _process_method_definition(
                child,
                source,
                fq_file,
                class_name,
                exported,
                pending_decorators,
                funcs,
            )
            pending_decorators = []
        else:
            pending_decorators = []


def _process_variable_declarator(
    node: Any,
    source: bytes,
    fq_file: str,
    class_name: str | None,
    exported: bool,
    decorators: list[str],
    funcs: list[dict[str, Any]],
) -> None:
    """Extract an arrow-function or function expression from a ``variable_declarator``."""
    var_name: str | None = None
    for child in node.children:
        if child.type == "identifier" and var_name is None:
            var_name = _node_text(child, source)
        elif child.type in ("arrow_function", "function"):
            if var_name is not None:
                _process_arrow_function(
                    child,
                    var_name,
                    source,
                    fq_file,
                    class_name,
                    exported,
                    decorators,
                    funcs,
                )


def _visit_node(
    node: Any,
    source: bytes,
    fq_file: str,
    class_name: str | None,
    exported: bool,
    pending_decorators: list[str],
    funcs: list[dict[str, Any]],
) -> None:
    """Recursively visit a tree-sitter node and collect function signatures."""
    t = node.type

    if t == "export_statement":
        # Everything inside an export_statement is exported
        for child in node.children:
            if child.type in (
                "function_declaration",
                "class_declaration",
                "lexical_declaration",
            ):
                _visit_node(
                    child,
                    source,
                    fq_file,
                    class_name,
                    True,
                    pending_decorators,
                    funcs,
                )
        return

    if t == "class_declaration":
        _process_class_declaration(node, source, fq_file, exported, funcs)
        return

    if t == "function_declaration":
        _process_function_declaration(
            node,
            source,
            fq_file,
            class_name,
            exported,
            pending_decorators,
            funcs,
        )
        return

    if t == "lexical_declaration":
        for child in node.children:
            if child.type == "variable_declarator":
                _process_variable_declarator(
                    child,
                    source,
                    fq_file,
                    class_name,
                    exported,
                    pending_decorators,
                    funcs,
                )
        return

    # Top-level program — gather pending decorators before declarations
    if t == "program":
        top_decs: list[str] = []
        for child in node.children:
            if child.type == "decorator":
                top_decs.append(_decorator_text(child, source))
            elif child.type in (
                "export_statement",
                "function_declaration",
                "class_declaration",
                "lexical_declaration",
            ):
                _visit_node(child, source, fq_file, None, False, top_decs, funcs)
                top_decs = []
            else:
                # Other nodes don't consume pending decorators, but we
                # recurse to catch nested definitions
                _visit_node(child, source, fq_file, class_name, exported, [], funcs)
                top_decs = []
        return

    # Default: recurse
    for child in node.children:
        _visit_node(child, source, fq_file, class_name, exported, [], funcs)


def _extract_with_tree_sitter(
    files: list[str],
    _base_path: str | None = None,
) -> list[dict[str, Any]]:
    """Extract TypeScript signatures using tree-sitter."""
    parser = _make_parser()
    all_funcs: list[dict[str, Any]] = []

    for f in files:
        path = Path(f)
        try:
            source = path.read_bytes()
        except OSError:
            continue

        tree = parser.parse(source)
        fq_file = path.name
        funcs: list[dict[str, Any]] = []
        _visit_node(tree.root_node, source, fq_file, None, False, [], funcs)
        all_funcs.extend(funcs)

    all_funcs.sort(key=lambda x: x["fqname"])
    return all_funcs


def _extract_calls_with_tree_sitter(path: Path) -> list[dict[str, Any]]:
    """Extract TypeScript call sites using tree-sitter."""
    parser = _make_parser()
    try:
        source = path.read_bytes()
    except OSError:
        return []

    tree = parser.parse(source)
    calls: list[dict[str, Any]] = []

    def visit(node: Any) -> None:
        if node.type == "call_expression":
            func_node = node.children[0] if node.children else None
            name: str | None = None
            if func_node is not None:
                if func_node.type == "identifier":
                    name = _node_text(func_node, source)
                elif func_node.type == "member_expression":
                    prop = _child_of_type(func_node, "property_identifier")
                    if prop is not None:
                        name = _node_text(prop, source)

            if name is not None:
                args_node = _child_of_type(node, "arguments")
                arg_count = 0
                if args_node is not None:
                    arg_count = sum(
                        1 for c in args_node.children if c.type not in ("(", ")", ",")
                    )
                calls.append(
                    {
                        "name": name,
                        "lineno": node.start_point[0] + 1,
                        "args": arg_count,
                        "kwargs": [],
                        "has_starargs": False,
                        "has_kwargs": False,
                        "file": str(path),
                    }
                )

        for child in node.children:
            visit(child)

    visit(tree.root_node)
    return calls


# ── Regex fallback ────────────────────────────────────────────────────────────

# Matches: (export )? (async )? function name<...>?(params): returntype
_FUNC_RE = re.compile(
    r"^(?:export\s+(?:default\s+)?)?(?P<async>async\s+)?"
    r"function\s+(?P<name>\w+)\s*(?:<[^>]*>)?\s*"
    r"\((?P<params>[^)]*)\)"
    r"(?:\s*:\s*(?P<return>[^{;]+))?",
    re.MULTILINE,
)

# Matches exported arrow/function expressions:
# (export )? (const|let|var) name = (async )? (params) =>
_ARROW_RE = re.compile(
    r"^(?:export\s+)?(?:const|let|var)\s+(?P<name>\w+)\s*"
    r"(?::[^=]+)?\s*=\s*(?P<async>async\s+)?"
    r"\((?P<params>[^)]*)\)\s*(?::\s*(?P<return>[^=>{]+))?\s*=>",
    re.MULTILINE,
)

_IGNORE_TAG = "impactguard: ignore"


def _has_ignore_comment_fallback(lines: list[str], lineno: int) -> bool:
    """Check for ``// impactguard: ignore`` on or before *lineno* (1-based)."""
    for idx in (lineno - 2, lineno - 1):
        if 0 <= idx < len(lines) and _IGNORE_TAG in lines[idx]:
            return True
    return False


def _parse_ts_params_regex(params_str: str) -> tuple[list[dict[str, Any]], bool]:
    """Parse a flat TypeScript parameter string into positional args.

    Handles the common cases:

    * ``name: type``
    * ``name?: type`` (optional)
    * ``name: type = default`` (defaulted)
    * ``...rest: type[]`` (rest / vararg)

    Nested generics (e.g. ``cb: (x: string) => void``) are approximated.
    """
    positional: list[dict[str, Any]] = []
    has_vararg = False

    params_str = params_str.strip()
    if not params_str:
        return positional, has_vararg

    # Split on top-level commas only (avoids splitting inside generics)
    parts = _top_level_split(params_str)

    for part in parts:
        part = part.strip()
        if not part:
            continue

        if part.startswith("..."):
            has_vararg = True
            continue

        is_optional = "?:" in part
        has_default = is_optional or re.search(r"=\s*\S", part) is not None

        # Extract name (before ?: or : or =)
        m = re.match(r"^(\w+)", part)
        name = m.group(1) if m else "unknown"

        # Extract type annotation (after first : or ?:, before =)
        type_: str | None = None
        type_m = re.search(r"\??\s*:\s*([^=]+)", part)
        if type_m:
            type_ = type_m.group(1).strip() or None

        positional.append({"name": name, "has_default": has_default, "type": type_})

    return positional, has_vararg


def _top_level_split(s: str) -> list[str]:
    """Split *s* on commas that are not inside ``<>``, ``()``, or ``[]``.

    Tracks each bracket type independently so that ``>`` in ``=>`` is never
    mistaken for a closing angle-bracket when no ``<`` is open.
    """
    parts: list[str] = []
    angle = paren = square = 0
    current: list[str] = []
    for ch in s:
        if ch == "<":
            angle += 1
            current.append(ch)
        elif ch == ">" and angle > 0:
            angle -= 1
            current.append(ch)
        elif ch == "(":
            paren += 1
            current.append(ch)
        elif ch == ")" and paren > 0:
            paren -= 1
            current.append(ch)
        elif ch == "[":
            square += 1
            current.append(ch)
        elif ch == "]" and square > 0:
            square -= 1
            current.append(ch)
        elif ch == "," and angle == 0 and paren == 0 and square == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    if current:
        parts.append("".join(current))
    return parts


def _extract_with_regex(
    files: list[str],
    _base_path: str | None = None,
) -> list[dict[str, Any]]:
    """Best-effort TypeScript signature extraction using regular expressions.

    Falls back to this implementation when tree-sitter is not available.
    Class methods and complex nested functions may not be captured.
    """
    all_funcs: list[dict[str, Any]] = []

    for f in files:
        path = Path(f)
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        fq_file = path.name
        lines = source.splitlines()

        for pattern, is_async_group in ((_FUNC_RE, "async"), (_ARROW_RE, "async")):
            for m in pattern.finditer(source):
                name = m.group("name")
                is_async = bool(m.group(is_async_group))
                params_str = m.group("params") or ""
                return_type: str | None = (m.group("return") or "").strip() or None
                lineno = source[: m.start()].count("\n") + 1

                # exported detection via simple string check on the line
                line_text = lines[lineno - 1] if lineno <= len(lines) else ""
                exported = line_text.lstrip().startswith("export")

                positional, has_vararg = _parse_ts_params_regex(params_str)
                fqname = f"{fq_file}:{name}"

                all_funcs.append(
                    {
                        "fqname": fqname,
                        "name": name,
                        "file": fq_file,
                        "lineno": lineno,
                        "end_lineno": lineno,
                        "positional": positional,
                        "kwonly": [],
                        "vararg": has_vararg,
                        "kwarg": False,
                        "class_name": None,
                        "return_type": return_type,
                        "decorators": [],
                        "is_async": is_async,
                        "ignored": _has_ignore_comment_fallback(lines, lineno),
                        "exported": exported,
                    }
                )

    # De-duplicate by fqname (regex patterns may overlap for some forms)
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for sig in all_funcs:
        if sig["fqname"] not in seen:
            seen.add(sig["fqname"])
            unique.append(sig)

    unique.sort(key=lambda x: x["fqname"])
    return unique


def _extract_calls_with_regex(path: Path) -> list[dict[str, Any]]:
    """Best-effort TypeScript call-site extraction using regular expressions."""
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    calls: list[dict[str, Any]] = []
    # Match simple call expressions: identifier(args) or obj.method(args)
    call_re = re.compile(r"\b(?:\w+\.)*(?P<name>\w+)\s*\((?P<args>[^)]*)\)")
    for m in call_re.finditer(source):
        name = m.group("name")
        args_str = m.group("args").strip()
        arg_count = (
            len([a for a in _top_level_split(args_str) if a.strip()]) if args_str else 0
        )
        lineno = source[: m.start()].count("\n") + 1
        calls.append(
            {
                "name": name,
                "lineno": lineno,
                "args": arg_count,
                "kwargs": [],
                "has_starargs": False,
                "has_kwargs": False,
                "file": str(path),
            }
        )
    return calls


# ── Public extractor class ────────────────────────────────────────────────────


class TypeScriptExtractor:
    """Language extractor for TypeScript (``.ts``) and TSX (``.tsx``) files.

    Uses tree-sitter for accurate AST-based extraction when available,
    otherwise falls back to regex-based extraction with a ``UserWarning``.
    """

    language: str = "typescript"
    extensions: list[str] = [".ts", ".tsx"]

    def __init__(self) -> None:
        self._warned: bool = False

    def _warn_if_no_tree_sitter(self) -> None:
        if not _TREE_SITTER_AVAILABLE and not self._warned:
            warnings.warn(
                "tree-sitter and tree-sitter-typescript are not installed; "
                "TypeScript extraction will use a regex-based fallback which "
                "may miss some function signatures.  Install the 'languages' "
                "extra for full support:  pip install 'impactguard[languages]'",
                UserWarning,
                stacklevel=3,
            )
            self._warned = True

    # ── LanguageExtractor protocol ────────────────────────────────────────────

    def extract_signatures(
        self,
        files: list[str],
        _base_path: str | None = None,
    ) -> list[dict[str, Any]]:
        """Extract signatures from TypeScript/TSX files."""
        if _TREE_SITTER_AVAILABLE:
            return _extract_with_tree_sitter(files, _base_path)
        self._warn_if_no_tree_sitter()
        return _extract_with_regex(files, _base_path)

    def extract_calls(self, path: Path) -> list[dict[str, Any]]:
        """Extract call sites from a TypeScript/TSX file."""
        if _TREE_SITTER_AVAILABLE:
            return _extract_calls_with_tree_sitter(path)
        self._warn_if_no_tree_sitter()
        return _extract_calls_with_regex(path)

    def parse_union_members(self, type_str: str) -> frozenset[str]:
        """Parse TypeScript union type syntax into member types.

        Handles ``X | Y | null | undefined`` syntax.  Each member is
        returned as-is (whitespace-stripped).
        """
        s = type_str.strip()
        if "|" in s:
            return frozenset(p.strip() for p in s.split("|"))
        return frozenset({s})


# ── Self-registration ─────────────────────────────────────────────────────────


def _register() -> None:
    from .registry import register

    register(TypeScriptExtractor())


_register()
