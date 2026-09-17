"""Structural decay measure: a complexity-accretion signal, complementary to
the S x E x C x lambda breaking-change risk model in ``risk_model.py``.

Ported concept (independent implementation) from officefloor/ImpactGate's
change-impact formula: https://github.com/officefloor/ImpactGate — the idea
that a non-breaking change can still make a codebase *worse* by piling
complexity onto an already-heavy container (a "god class" gaining another
method, a "god function" gaining another branch), and that this is cheap to
detect with:

    cost(unit)  = max(WMC_other, 1) * CC(unit) * max(1, changed_lines(unit))

``WMC_other`` is the complexity already sitting in the unit's container
(class, or module for free functions), measured on the PRE-change tree, so:

  - a unit dropped into a brand-new container costs ~CC*dlines (importing a
    file is cheap; nothing was there before)
  - a method accreted onto an existing heavy class is charged for the
    siblings that were already there (piling onto a god-class is expensive)

This module only measures decay; it does not judge whether a change is a
*breaking* API change (see ``risk_model.py`` / ``impact_analysis.py`` for
that). The two signals are meant to be reported side by side.

Scope: Python only for now (uses ``ast`` for both unit extraction and
cyclomatic complexity, consistent with the rest of ImpactGuard's Python-first
extraction). Other languages fall back to whole-file line-count deltas with
CC=1, which still gates pathological file growth but carries no per-unit
signal; see ``_generic_units``.
"""

from __future__ import annotations

import ast
import re
import subprocess
from dataclasses import dataclass, field

from ._logging import get_logger

_log = get_logger(__name__)

_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# Diffs bigger than this are almost always a generated dump or a vendored
# blob dragged into the repo. Scoring them would either drown every other
# signal in noise or make the gate effectively unusable, so they are
# reported under "skipped" instead of folded into the score.
DEFAULT_MAX_DIFF_LINES = 200_000
DEFAULT_RENAME_JACCARD = 0.6


# ── Data model ────────────────────────────────────────────────────────────


@dataclass
class Unit:
    """A scored region of code: a function, method, or (as a fallback) a
    whole file."""

    name: str
    container: str  # class fqname, or "<module>" for free functions/files
    cc: int
    start_line: int
    end_line: int


@dataclass
class UnitImpact:
    name: str
    container: str
    cc: int
    dlines: int
    wmc_other: int
    cost: int
    kind: str  # "mutation" | "godclass" (new) | "rename"


@dataclass
class FileImpact:
    path: str
    mutation_cost: int = 0
    godclass_cost: int = 0
    mut_units: int = 0
    new_units: int = 0
    renames: int = 0
    units: list = field(default_factory=list)  # list[UnitImpact]

    @property
    def total_cost(self) -> int:
        return self.mutation_cost + self.godclass_cost


@dataclass
class SkippedFile:
    path: str
    diff_lines: int


@dataclass
class DecayScore:
    files_changed: int = 0
    impact: int = 0  # files_changed * sum(mutation_cost + godclass_cost)
    file_impacts: list = field(default_factory=list)  # list[FileImpact]
    skipped: list = field(default_factory=list)  # list[SkippedFile]

    def ranked_files(self) -> list:
        """Files sorted by their share of the total cost, highest first."""
        return sorted(
            (fi for fi in self.file_impacts if fi.total_cost > 0),
            key=lambda fi: fi.total_cost,
            reverse=True,
        )


# ── Cyclomatic complexity (Python, ast-based) ──────────────────────────────

_DECISION_NODES = (
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.Try,
    ast.ExceptHandler,
    ast.With,
    ast.AsyncWith,
    ast.Assert,
    ast.BoolOp,
    ast.IfExp,
    ast.comprehension,
)


def _cyclomatic_complexity(node: ast.AST) -> int:
    """McCabe-style cyclomatic complexity: 1 + number of decision points
    strictly inside *node*'s own body (nested defs are walked separately so
    their complexity isn't double-counted into the parent)."""
    cc = 1
    for child in ast.walk(node):
        if child is node:
            continue
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue  # counted on its own when we visit it directly
        if isinstance(child, _DECISION_NODES):
            cc += 1
        elif isinstance(child, ast.BoolOp):
            cc += len(child.values) - 1
    return cc


def _skip_nested(node: ast.AST, boundary_types) -> ast.iter_child_nodes:
    """Yield descendants of *node*, not descending into nested boundary_types
    (so a class's own CC doesn't swallow its methods' internals twice)."""
    stack = list(ast.iter_child_nodes(node))
    while stack:
        child = stack.pop()
        yield child
        if not isinstance(child, boundary_types):
            stack.extend(ast.iter_child_nodes(child))


def _python_units(source: str) -> list:
    """Extract function/method units from Python source. Free functions get
    container "<module>"; methods get their class's name."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        _log.debug("decay_model: failed to parse Python source: %s", exc)
        return []

    units: list[Unit] = []
    _FUNC = (ast.FunctionDef, ast.AsyncFunctionDef)

    def visit(node: ast.AST, container: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, _FUNC):
                end = getattr(child, "end_lineno", child.lineno)
                units.append(
                    Unit(
                        name=f"{container}.{child.name}" if container != "<module>" else child.name,
                        container=container,
                        cc=_cyclomatic_complexity(child),
                        start_line=child.lineno,
                        end_line=end,
                    )
                )
                # Nested defs (closures) are their own units too, container'd
                # under the enclosing function.
                visit(child, f"{container}.{child.name}" if container != "<module>" else child.name)
            elif isinstance(child, ast.ClassDef):
                visit(child, child.name)
            # Anything else at this level (module-level code, etc.) is not a
            # scored unit; it contributes to no container's WMC.

    visit(tree, "<module>")
    return units


def _generic_units(source: str, path: str) -> list:
    """Fallback for non-Python files: one whole-file unit, CC=1, container is
    the file itself. Still gates runaway file growth; carries no per-unit
    signal within the file."""
    lines = source.count("\n") + 1
    return [Unit(name=path, container="<file>", cc=1, start_line=1, end_line=lines)]


def extract_units(source: str, path: str) -> list:
    if path.endswith(".py"):
        return _python_units(source)
    return _generic_units(source, path)


# ── Diff parsing ────────────────────────────────────────────────────────────


def _line_set(ranges: list) -> set:
    out: set[int] = set()
    for start, count in ranges:
        out.update(range(start, start + count))
    return out


_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def parse_unified_diff(diff_text: str) -> dict:
    """Parse a unified diff (as produced by ``git diff -U0``) into
    ``{path: (added_ranges, removed_ranges)}`` where each range is
    ``(start_line, line_count)`` in the respective (before/after) file."""
    files: dict[str, tuple[list, list]] = {}
    path = None
    added: list = []
    removed: list = []

    def flush():
        if path is not None:
            files[path] = (added, removed)

    for line in diff_text.splitlines():
        if line.startswith("+++ "):
            p = line[4:].strip()
            if p.startswith("b/"):
                p = p[2:]
            if p != "/dev/null":
                flush()
                path = p
                added, removed = [], []
        elif line.startswith("--- "):
            continue
        elif line.startswith("@@"):
            m = _HUNK_RE.match(line)
            if not m:
                continue
            old_start, old_len, new_start, new_len = m.groups()
            old_len = int(old_len) if old_len is not None else 1
            new_len = int(new_len) if new_len is not None else 1
            if old_len:
                removed.append((int(old_start), old_len))
            if new_len:
                added.append((int(new_start), new_len))
    flush()
    return files


def diff_line_count(added: list, removed: list) -> int:
    return sum(c for _, c in added) + sum(c for _, c in removed)


# ── Rename matching (light, best-effort) ────────────────────────────────────


def _tokens(src_lines: list, u) -> set:
    body = "\n".join(src_lines[max(0, u.start_line - 1): u.end_line])
    return set(_TOKEN.findall(body))


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _best_rename(u, before: list, after_names: set, matched: set,
                  removed_lines: set, before_src: list, after_src: list,
                  threshold: float):
    u_tokens = _tokens(after_src, u)
    best, best_j = None, threshold
    for b in before:
        if b.name in matched or b.name in after_names:
            continue
        if not any(b.start_line <= ln <= b.end_line for ln in removed_lines):
            continue
        j = _jaccard(u_tokens, _tokens(before_src, b))
        if j >= best_j:
            best, best_j = b, j
    return best


# ── Core per-file scoring ────────────────────────────────────────────────────


def compute_file_impact(
    path: str,
    before_units: list,
    after_units: list,
    before_src: list,
    after_src: list,
    added: list,
    removed: list,
    rename_jaccard: float = DEFAULT_RENAME_JACCARD,
):
    """Score one file's change. ``before_units``/``after_units`` are the
    Units extracted from the pre- and post-change source; ``before_src``/
    ``after_src`` are the source split into lines (1-indexed access via
    line number - 1); ``added``/``removed`` are diff ranges from
    ``parse_unified_diff``."""
    added_lines = _line_set(added)
    removed_lines = _line_set(removed)

    before_by_container: dict[str, int] = {}
    for u in before_units:
        before_by_container[u.container] = before_by_container.get(u.container, 0) + u.cc

    def wmc_other(u, src) -> int:
        base = before_by_container.get(u.container, 0)
        return max(base - (src.cc if src is not None else 0), 0)

    before_by_name = {u.name: u for u in before_units}
    after_names = {u.name for u in after_units}

    def overlap(u, lines: set) -> int:
        if not lines:
            return 0
        return sum(1 for ln in range(u.start_line, u.end_line + 1) if ln in lines)

    touched = [(u, overlap(u, added_lines)) for u in after_units]
    touched = [(u, n) for u, n in touched if n > 0]

    matched_before: set = set()
    fi = FileImpact(path=path)

    for u, add_n in touched:
        prior = before_by_name.get(u.name)
        kind = "mutation"
        del_n = 0
        src = prior
        if prior is not None:
            matched_before.add(prior.name)
            del_n = overlap(prior, removed_lines)
        else:
            cand = _best_rename(u, before_units, after_names, matched_before,
                                 removed_lines, before_src, after_src, rename_jaccard)
            if cand is not None:
                matched_before.add(cand.name)
                del_n = overlap(cand, removed_lines)
                kind = "rename"
                src = cand
            else:
                kind = "godclass"

        dlines = max(1, add_n + del_n)
        wmc = wmc_other(u, src)
        cost = max(wmc, 1) * u.cc * dlines
        fi.units.append(UnitImpact(u.name, u.container, u.cc, dlines, wmc, cost, kind))
        if kind == "godclass":
            fi.godclass_cost += cost
            fi.new_units += 1
        else:
            fi.mutation_cost += cost
            fi.mut_units += 1
            if kind == "rename":
                fi.renames += 1

    return fi


# ── Git plumbing ─────────────────────────────────────────────────────────


def _run_git(args: list, cwd: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def _show(ref: str, path: str, cwd: str) -> str:
    try:
        return _run_git(["show", f"{ref}:{path}"], cwd=cwd)
    except RuntimeError:
        return ""  # file did not exist at ref (new or deleted file)


def _resolve_diff_args(mode: str, base: str) -> list:
    if mode == "staged":
        return ["diff", "-U0", "--staged"]
    if mode == "worktree":
        return ["diff", "-U0"]
    if mode == "range":
        return ["diff", "-U0", f"{base}...HEAD"]
    raise ValueError(f"unknown mode: {mode!r}")


def _side_refs(mode: str, base: str) -> tuple:
    """Return (before_ref, after_ref) usable with `git show ref:path`."""
    if mode == "staged":
        return "HEAD", ":0"  # ":0" -> git show ':0:path' reads the index
    if mode == "worktree":
        return "HEAD", None  # None -> read after-state straight off disk
    if mode == "range":
        return base, "HEAD"
    raise ValueError(f"unknown mode: {mode!r}")


def score_change(
    repo_path: str = ".",
    mode: str = "staged",
    base: str = "origin/main",
    max_diff_lines: int = DEFAULT_MAX_DIFF_LINES,
    rename_jaccard: float = DEFAULT_RENAME_JACCARD,
) -> DecayScore:
    """Score the structural decay of a change. ``mode`` is one of
    ``"staged"`` (default; staged vs HEAD, for a pre-commit hook),
    ``"worktree"`` (uncommitted edits vs HEAD), or ``"range"`` (merge-base of
    *base* vs HEAD, for CI/PR review)."""
    diff_text = _run_git(_resolve_diff_args(mode, base), cwd=repo_path)
    files = parse_unified_diff(diff_text)
    before_ref, after_ref = _side_refs(mode, base)

    score = DecayScore()
    for path, (added, removed) in files.items():
        n_lines = diff_line_count(added, removed)
        if n_lines > max_diff_lines:
            score.skipped.append(SkippedFile(path=path, diff_lines=n_lines))
            continue

        before_text = _show(before_ref, path, repo_path)
        if after_ref is None:
            try:
                with open(f"{repo_path}/{path}", encoding="utf-8", errors="replace") as fh:
                    after_text = fh.read()
            except OSError:
                after_text = ""
        else:
            after_text = _show(after_ref, path, repo_path)

        before_units = extract_units(before_text, path) if before_text else []
        after_units = extract_units(after_text, path) if after_text else []
        fi = compute_file_impact(
            path,
            before_units,
            after_units,
            before_text.splitlines(),
            after_text.splitlines(),
            added,
            removed,
            rename_jaccard,
        )
        score.file_impacts.append(fi)
        score.files_changed += 1

    total_unit_cost = sum(fi.total_cost for fi in score.file_impacts)
    score.impact = score.files_changed * total_unit_cost
    return score


# ── Enforcement (mirrors risk_gate.py / enforce_gate.py conventions) ────────


def enforce(score: DecayScore, warn_at: int, block_at: int, enforcement: str) -> tuple:
    """Return ``(blocked, exit_code)``. ``enforcement`` is ``"off"``,
    ``"warn"``, or ``"block"``, matching ``risk_gate.py``'s vocabulary.
    Exit codes follow the same convention used elsewhere in ImpactGuard:
    0 = ok/warn, 2 = blocked."""
    if enforcement == "off":
        return False, 0
    if score.impact >= block_at and enforcement == "block":
        return True, 2
    return False, 0


def is_warning(score: DecayScore, warn_at: int) -> bool:
    return score.impact >= warn_at


# ── Reporting ────────────────────────────────────────────────────────────


def render_text(score: DecayScore, top_n: int = 10) -> str:
    """Human-readable summary: the change-level impact number, files
    skipped as oversized, and a ranked list of files to consider for
    refactoring (highest share of the impact first)."""
    lines = [f"structural decay impact: {score.impact}",
             f"files changed (scored): {score.files_changed}"]

    if score.skipped:
        lines.append(
            f"skipped {len(score.skipped)} oversized file(s), not scored "
            "(diff over max_diff_lines; likely generated or vendored):"
        )
        for s in score.skipped:
            lines.append(f"  - {s.path} ({s.diff_lines} lines)")

    ranked = score.ranked_files()
    if ranked:
        lines.append("")
        lines.append("Files to consider for refactoring (by change-impact cost):")
        for fi in ranked[:top_n]:
            lines.append(
                f"  {fi.total_cost:>10}  {fi.path}"
                f"  (mutation={fi.mutation_cost}, new={fi.godclass_cost},"
                f" units_touched={fi.mut_units + fi.new_units})"
            )
    return "\n".join(lines)


def render_json(score: DecayScore) -> dict:
    return {
        "impact": score.impact,
        "files_changed": score.files_changed,
        "skipped": [{"path": s.path, "diff_lines": s.diff_lines} for s in score.skipped],
        "files": [
            {
                "path": fi.path,
                "total_cost": fi.total_cost,
                "mutation_cost": fi.mutation_cost,
                "godclass_cost": fi.godclass_cost,
                "mutated_units": fi.mut_units,
                "new_units": fi.new_units,
                "renames": fi.renames,
            }
            for fi in score.ranked_files()
        ],
    }
