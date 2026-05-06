"""Adversarial synthetic generator for ImpactGuard reliability testing.

Produces (old_signatures, new_signatures) pairs where the *new* snapshot
contains a BREAKING change that has been deliberately disguised to look like a
non-breaking (safe) or even beneficial change.

Each :class:`AdversarialPair` carries:

* ``strategy_name`` – unique identifier for the deception tactic.
* ``description`` – one-sentence summary of what change was made.
* ``camouflage_notes`` – explanation of *why* the change appears benign.
* ``old_signatures`` / ``new_signatures`` – raw signature lists suitable for
  serialisation to JSON and passing to :func:`impactguard.compare`.
* ``expected_breaking_patterns`` – substrings that **must** appear in the
  ``"breaking"`` list returned by :func:`impactguard.compare`.
* ``expected_nonbreaking_patterns`` – substrings expected in
  ``"nonbreaking"``; these are the camouflage noise added to distract the
  analyser (and reviewers).

Strategies
----------
1.  ``required_param_hidden_by_type_annotation``
2.  ``positional_reorder_hidden_by_optional_add``
3.  ``type_narrowing_disguised_as_cleanup``
4.  ``kwonly_removal_with_optional_addition``
5.  ``vararg_removal_with_kwarg_addition``
6.  ``return_type_narrowing_disguised_as_guarantee``
7.  ``decorator_removal_hidden_by_optional_kwarg``
8.  ``required_kwonly_added_with_misleading_name``
9.  ``function_removal_hidden_by_rename_addition``
10. ``kwargs_removal_hidden_by_explicit_params``
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Name pools used by randomized strategy factories
# ---------------------------------------------------------------------------

_MODULES: list[str] = [
    "myapp", "core", "utils", "service", "api",
    "backend", "client", "handlers", "models", "auth",
]

_FUNC_NAMES: list[str] = [
    "process", "transfer", "render", "connect", "log_event",
    "fetch_name", "get_config", "create_session", "parse_config",
    "send_request", "handle", "execute", "validate", "transform",
    "dispatch", "publish", "query", "update", "delete",
]

_PARAM_NAMES: list[str] = [
    "source", "destination", "user_id", "name", "value",
    "data", "config", "context", "path", "key", "token",
    "url", "host", "port", "limit", "mode", "version",
    "payload", "request", "template", "event", "label",
    "target", "origin", "tag", "scope", "region", "bucket",
    "index", "cursor",
]

_SCALAR_TYPES: list[str] = ["str", "int", "float", "bool", "bytes"]

#: Parameter names that *sound* optional but can carry no default in ``required_kwonly_added_with_misleading_name``.
_MISLEADING_KWONLY_NAMES: list[str] = [
    "optional_context", "extra_info", "maybe_config",
    "optional_hints", "supplemental_data", "optional_meta",
]

_DECORATOR_NAMES: list[str] = ["cache", "lru_cache", "cached_property"]

_VERSION_SUFFIXES: list[str] = ["_v2", "_v3", "_new", "_updated", "_next"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rand_fqname(rng: random.Random) -> str:
    """Return a random ``module:function`` qualified name."""
    return f"{rng.choice(_MODULES)}:{rng.choice(_FUNC_NAMES)}"


def _rand_params(rng: random.Random, n: int,
                 exclude: list[str] | None = None) -> list[str]:
    """Return *n* distinct parameter names chosen without replacement."""
    pool = [p for p in _PARAM_NAMES if p not in (exclude or [])]
    return rng.sample(pool, min(n, len(pool)))


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


def _param(
    name: str,
    has_default: bool = False,
    type_: str | None = None,
) -> dict[str, Any]:
    """Build a parameter descriptor matching the ImpactGuard signature schema."""
    p: dict[str, Any] = {"name": name, "has_default": has_default}
    if type_ is not None:
        p["type"] = type_
    return p


def _sig(
    fqname: str,
    positional: list[dict] | None = None,
    kwonly: list[dict] | None = None,
    vararg: bool = False,
    kwarg: bool = False,
    return_type: str | None = None,
    decorators: list[str] | None = None,
    exported: bool = True,
) -> dict[str, Any]:
    """Build a function-signature descriptor matching the ImpactGuard schema."""
    return {
        "fqname": fqname,
        "name": fqname.split(".")[-1].split(":")[-1],
        "positional": positional or [],
        "kwonly": kwonly or [],
        "vararg": vararg,
        "kwarg": kwarg,
        "return_type": return_type,
        "decorators": decorators or [],
        "exported": exported,
    }


@dataclass
class AdversarialPair:
    """A synthetic (old, new) signature pair that hides a breaking change."""

    strategy_name: str
    description: str
    camouflage_notes: str
    old_signatures: list[dict[str, Any]]
    new_signatures: list[dict[str, Any]]
    expected_breaking_patterns: list[str] = field(default_factory=list)
    expected_nonbreaking_patterns: list[str] = field(default_factory=list)

    def verify(self, result: dict[str, list[str]]) -> tuple[bool, list[str]]:
        """Check whether *result* from ``compare()`` contains all expected patterns.

        Returns
        -------
        (ok, failures)
            *ok* is ``True`` when every expected breaking pattern is found.
            *failures* lists the patterns that were NOT found.
        """
        failures: list[str] = []
        for pattern in self.expected_breaking_patterns:
            if not any(pattern in item for item in result.get("breaking", [])):
                failures.append(f"MISSING breaking pattern: {pattern!r}")
        return (len(failures) == 0), failures


# ---------------------------------------------------------------------------
# Strategy implementations
# ---------------------------------------------------------------------------


def _strategy_required_param_hidden_by_type_annotation(
    rng: random.Random,
) -> AdversarialPair:
    """Add a required positional parameter while also widening a type annotation.

    Widening the first parameter's type from ``T`` to ``T | None`` is a genuine
    non-breaking improvement.  A reviewer (or a naive tool) might focus on the
    TYPE WIDENED entry and miss that a new required parameter has no default.
    """
    fqname = _rand_fqname(rng)
    p_a, p_b, p_c = _rand_params(rng, 3)
    base_type = rng.choice(_SCALAR_TYPES)
    wide_type = f"{base_type} | None"
    old = [
        _sig(
            fqname,
            positional=[_param(p_a, type_=base_type), _param(p_b)],
        )
    ]
    new = [
        _sig(
            fqname,
            positional=[
                _param(p_a, type_=wide_type),  # widening — non-breaking noise
                _param(p_b),
                _param(p_c),                    # ← BREAKING: required, no default
            ],
        )
    ]
    return AdversarialPair(
        strategy_name="required_param_hidden_by_type_annotation",
        description=(
            "A new required positional parameter is added alongside a non-breaking "
            "type widening on an existing parameter."
        ),
        camouflage_notes=(
            f"Widening '{p_a}' from '{base_type}' to '{wide_type}' produces a TYPE WIDENED "
            "non-breaking entry that draws attention away from the silent "
            f"introduction of the required '{p_c}'."
        ),
        old_signatures=old,
        new_signatures=new,
        expected_breaking_patterns=["REQUIRED POSITIONAL ADDED", fqname],
        expected_nonbreaking_patterns=["TYPE WIDENED"],
    )


def _strategy_positional_reorder_hidden_by_optional_add(
    rng: random.Random,
) -> AdversarialPair:
    """Swap two positional parameters while also adding an optional one.

    The optional addition is non-breaking noise that can make the diff look
    like a pure expansion of the API.
    """
    fqname = _rand_fqname(rng)
    p_src, p_dst, p_opt = _rand_params(rng, 3)
    old = [
        _sig(
            fqname,
            positional=[_param(p_src), _param(p_dst)],
        )
    ]
    new = [
        _sig(
            fqname,
            positional=[
                _param(p_dst),                         # ← BREAKING: reorder
                _param(p_src),
                _param(p_opt, has_default=True),       # non-breaking noise
            ],
        )
    ]
    return AdversarialPair(
        strategy_name="positional_reorder_hidden_by_optional_add",
        description=(
            "The first two positional parameters are swapped; an optional "
            "third parameter is added simultaneously."
        ),
        camouflage_notes=(
            f"The optional '{p_opt}' addition produces a NONBREAKING entry, "
            "making the diff look like a pure feature addition."
        ),
        old_signatures=old,
        new_signatures=new,
        expected_breaking_patterns=["POSITIONAL REORDER", fqname],
        expected_nonbreaking_patterns=["OPTIONAL POSITIONAL ADDED", fqname],
    )


def _strategy_type_narrowing_disguised_as_cleanup(
    rng: random.Random,
) -> AdversarialPair:
    """Narrow a parameter type from ``T | None`` to ``T``.

    This looks like a cleanup or a "we no longer accept None" guarantee, but
    callers that previously passed ``None`` will break at runtime.
    """
    fqname = _rand_fqname(rng)
    p_name = rng.choice(_PARAM_NAMES)
    base_type = rng.choice(_SCALAR_TYPES)
    wide_type = f"{base_type} | None"
    old = [
        _sig(
            fqname,
            positional=[_param(p_name, type_=wide_type)],
        )
    ]
    new = [
        _sig(
            fqname,
            positional=[_param(p_name, type_=base_type)],  # ← BREAKING: narrowing
        )
    ]
    return AdversarialPair(
        strategy_name="type_narrowing_disguised_as_cleanup",
        description=(
            f"A parameter's type is narrowed from '{wide_type}' to '{base_type}', "
            "breaking callers that pass None."
        ),
        camouflage_notes=(
            f"Removing 'None' from the '{p_name}' type union reads as a type-safety "
            "improvement or stricter validation, not as a breaking contract change."
        ),
        old_signatures=old,
        new_signatures=new,
        expected_breaking_patterns=["TYPE CHANGED", fqname, p_name],
        expected_nonbreaking_patterns=[],
    )


def _strategy_kwonly_removal_with_optional_addition(
    rng: random.Random,
) -> AdversarialPair:
    """Remove a required keyword-only argument while adding an optional one.

    The optional addition emits a NONBREAKING entry, masking the BREAKING
    removal.
    """
    fqname = _rand_fqname(rng)
    p_pos, p_req_kw, p_opt_kw = _rand_params(rng, 3)
    old = [
        _sig(
            fqname,
            positional=[_param(p_pos)],
            kwonly=[_param(p_req_kw)],              # required kwonly
        )
    ]
    new = [
        _sig(
            fqname,
            positional=[_param(p_pos)],
            kwonly=[_param(p_opt_kw, has_default=True)],  # optional — noise
            # p_req_kw silently removed ← BREAKING
        )
    ]
    return AdversarialPair(
        strategy_name="kwonly_removal_with_optional_addition",
        description=(
            "A required keyword-only argument is removed while an optional "
            "keyword argument is added."
        ),
        camouflage_notes=(
            f"The addition of '{p_opt_kw}' generates a NONBREAKING signal and looks "
            f"like a feature enhancement, hiding the removal of '{p_req_kw}'."
        ),
        old_signatures=old,
        new_signatures=new,
        expected_breaking_patterns=["KWONLY REMOVED", fqname],
        expected_nonbreaking_patterns=["OPTIONAL KWONLY ADDED", fqname],
    )


def _strategy_vararg_removal_with_kwarg_addition(
    rng: random.Random,
) -> AdversarialPair:
    """Remove ``*args`` while simultaneously adding ``**kwargs``.

    ``**kwargs`` makes the signature look more flexible, but callers relying
    on positional variadic arguments will break.
    """
    fqname = _rand_fqname(rng)
    (p_first,) = _rand_params(rng, 1)
    old = [
        _sig(fqname, positional=[_param(p_first)], vararg=True)
    ]
    new = [
        _sig(fqname, positional=[_param(p_first)], vararg=False, kwarg=True)
        # *args REMOVED ← BREAKING; **kwargs ADDED ← looks like expansion
    ]
    return AdversarialPair(
        strategy_name="vararg_removal_with_kwarg_addition",
        description=(
            "``*args`` is removed while ``**kwargs`` is added, breaking callers "
            "that passed extra positional arguments."
        ),
        camouflage_notes=(
            "``**kwargs`` signals interface flexibility; a reviewer might see the "
            "change as an upgrade from positional variadic to keyword variadic."
        ),
        old_signatures=old,
        new_signatures=new,
        expected_breaking_patterns=["*args REMOVED", fqname],
        expected_nonbreaking_patterns=[],
    )


def _strategy_return_type_narrowing_disguised_as_guarantee(
    rng: random.Random,
) -> AdversarialPair:
    """Narrow the return type from ``T | None`` to ``T``.

    Callers that branch on ``None`` will now have dead-code paths or runtime
    errors if the implementation ever still returns ``None`` in practice.
    """
    fqname = _rand_fqname(rng)
    (p_first,) = _rand_params(rng, 1)
    base_type = rng.choice(_SCALAR_TYPES)
    wide_type = f"{base_type} | None"
    old = [
        _sig(fqname, positional=[_param(p_first)], return_type=wide_type)
    ]
    new = [
        _sig(fqname, positional=[_param(p_first)], return_type=base_type)
        # BREAKING: return type narrowed
    ]
    return AdversarialPair(
        strategy_name="return_type_narrowing_disguised_as_guarantee",
        description=(
            f"The return type is narrowed from '{wide_type}' to '{base_type}', "
            "appearing as a stronger guarantee while breaking downstream None-checks."
        ),
        camouflage_notes=(
            "Removing 'None' from the return type looks like the function now "
            "always succeeds—a positive improvement—masking downstream breakage."
        ),
        old_signatures=old,
        new_signatures=new,
        expected_breaking_patterns=["RETURN TYPE CHANGED", fqname],
        expected_nonbreaking_patterns=[],
    )


def _strategy_decorator_removal_hidden_by_optional_kwarg(
    rng: random.Random,
) -> AdversarialPair:
    """Remove a caching decorator while adding an optional ``force`` kwarg.

    The optional kwarg is non-breaking; the decorator removal changes the
    function's caching semantics and calling convention for callers that
    depend on them.
    """
    fqname = _rand_fqname(rng)
    p_key, p_force = _rand_params(rng, 2)
    decorator = rng.choice(_DECORATOR_NAMES)
    old = [
        _sig(fqname, positional=[_param(p_key)], decorators=[decorator])
    ]
    new = [
        _sig(
            fqname,
            positional=[_param(p_key)],
            kwonly=[_param(p_force, has_default=True)],  # noise
            decorators=[],  # ← BREAKING: decorator removed
        )
    ]
    return AdversarialPair(
        strategy_name="decorator_removal_hidden_by_optional_kwarg",
        description=(
            f"A ``@{decorator}`` decorator is removed while an optional keyword-only "
            "argument is added."
        ),
        camouflage_notes=(
            f"The '{p_force}' kwarg looks like a cache-invalidation option being added, "
            f"which could be mistaken for a caching improvement rather than removal of @{decorator}."
        ),
        old_signatures=old,
        new_signatures=new,
        expected_breaking_patterns=["DECORATOR REMOVED", fqname],
        expected_nonbreaking_patterns=["OPTIONAL KWONLY ADDED", fqname],
    )


def _strategy_required_kwonly_added_with_misleading_name(
    rng: random.Random,
) -> AdversarialPair:
    """Add a required keyword-only parameter whose name implies optionality.

    Naming a required parameter ``optional_context`` or ``extra_info``
    suggests it is supplementary, but the absence of a default makes it
    mandatory.
    """
    fqname = _rand_fqname(rng)
    (p_pos,) = _rand_params(rng, 1)
    misleading_name = rng.choice(_MISLEADING_KWONLY_NAMES)
    old = [
        _sig(fqname, positional=[_param(p_pos)])
    ]
    new = [
        _sig(
            fqname,
            positional=[_param(p_pos)],
            kwonly=[_param(misleading_name)],  # ← BREAKING: no default!
        )
    ]
    return AdversarialPair(
        strategy_name="required_kwonly_added_with_misleading_name",
        description=(
            f"A required keyword-only parameter named '{misleading_name}' is added, "
            "breaking callers that do not supply it."
        ),
        camouflage_notes=(
            f"The word suggesting optionality in '{misleading_name}' implies it has a default, "
            "leading reviewers to classify it as a safe addition."
        ),
        old_signatures=old,
        new_signatures=new,
        expected_breaking_patterns=["REQUIRED KWONLY ADDED", fqname],
        expected_nonbreaking_patterns=[],
    )


def _strategy_function_removal_hidden_by_rename_addition(
    rng: random.Random,
) -> AdversarialPair:
    """Remove a public function while adding a similarly-named replacement.

    From a diff perspective the change looks like a rename / upgrade, but any
    caller importing the old name will get an ``AttributeError``.
    """
    old_fqname = _rand_fqname(rng)
    suffix = rng.choice(_VERSION_SUFFIXES)
    module, func = old_fqname.split(":")
    new_fqname = f"{module}:{func}{suffix}"
    (p_path,) = _rand_params(rng, 1)
    (p_strict,) = _rand_params(rng, 1, exclude=[p_path])
    old = [
        _sig(old_fqname, positional=[_param(p_path)])
    ]
    new = [
        _sig(new_fqname, positional=[_param(p_path), _param(p_strict, has_default=True)])
        # old function REMOVED ← BREAKING; new function ADDED ← noise
    ]
    return AdversarialPair(
        strategy_name="function_removal_hidden_by_rename_addition",
        description=(
            f"The original function is removed and a new '{suffix.lstrip('_')}' variant is added, "
            "appearing as a non-destructive upgrade."
        ),
        camouflage_notes=(
            "The ADDED entry for the new variant is non-breaking and dominates "
            "visual attention in a diff, hiding the REMOVED entry for the old name."
        ),
        old_signatures=old,
        new_signatures=new,
        expected_breaking_patterns=["REMOVED", old_fqname],
        expected_nonbreaking_patterns=["ADDED", new_fqname],
    )


def _strategy_kwargs_removal_hidden_by_explicit_params(
    rng: random.Random,
) -> AdversarialPair:
    """Replace ``**kwargs`` with explicit optional parameters.

    The change looks like an API clarity improvement, but callers that pass
    arbitrary keyword arguments (not in the explicit list) will get a
    ``TypeError``.
    """
    fqname = _rand_fqname(rng)
    p_url, p1, p2, p3 = _rand_params(rng, 4)
    old = [
        _sig(fqname, positional=[_param(p_url)], kwarg=True)
    ]
    new = [
        _sig(
            fqname,
            positional=[_param(p_url)],
            kwonly=[
                _param(p1, has_default=True),
                _param(p2, has_default=True),
                _param(p3, has_default=True),
            ],
            kwarg=False,  # ← BREAKING: **kwargs removed
        )
    ]
    return AdversarialPair(
        strategy_name="kwargs_removal_hidden_by_explicit_params",
        description=(
            "``**kwargs`` is removed and replaced with explicit optional parameters, "
            "breaking callers that pass unlisted keyword arguments."
        ),
        camouflage_notes=(
            f"Adding named parameters like '{p1}', '{p2}', '{p3}' looks like better "
            "documentation and IDE support. The loss of forward-compatibility for "
            "unknown kwargs is easy to miss."
        ),
        old_signatures=old,
        new_signatures=new,
        expected_breaking_patterns=["**kwargs REMOVED", fqname],
        expected_nonbreaking_patterns=["OPTIONAL KWONLY ADDED", fqname],
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

from collections.abc import Callable

_STRATEGY_REGISTRY: dict[str, Callable[["random.Random"], "AdversarialPair"]] = {
    "required_param_hidden_by_type_annotation": _strategy_required_param_hidden_by_type_annotation,
    "positional_reorder_hidden_by_optional_add": _strategy_positional_reorder_hidden_by_optional_add,
    "type_narrowing_disguised_as_cleanup": _strategy_type_narrowing_disguised_as_cleanup,
    "kwonly_removal_with_optional_addition": _strategy_kwonly_removal_with_optional_addition,
    "vararg_removal_with_kwarg_addition": _strategy_vararg_removal_with_kwarg_addition,
    "return_type_narrowing_disguised_as_guarantee": _strategy_return_type_narrowing_disguised_as_guarantee,
    "decorator_removal_hidden_by_optional_kwarg": _strategy_decorator_removal_hidden_by_optional_kwarg,
    "required_kwonly_added_with_misleading_name": _strategy_required_kwonly_added_with_misleading_name,
    "function_removal_hidden_by_rename_addition": _strategy_function_removal_hidden_by_rename_addition,
    "kwargs_removal_hidden_by_explicit_params": _strategy_kwargs_removal_hidden_by_explicit_params,
}


def list_strategies() -> list[str]:
    """Return the names of all available camouflage strategies."""
    return list(_STRATEGY_REGISTRY)


def generate(strategy_name: str, *, seed: int | str | None = None) -> AdversarialPair:
    """Generate an :class:`AdversarialPair` for the named strategy.

    Parameters
    ----------
    strategy_name:
        One of the names returned by :func:`list_strategies`.
    seed:
        Optional seed for the internal :class:`random.Random` instance.
        Passing the same *seed* value guarantees identical output
        (deterministic / reproducible).  Omitting *seed* (or passing
        ``None``) draws entropy from the OS, producing a unique result
        each time.

    Returns
    -------
    AdversarialPair

    Raises
    ------
    KeyError
        If *strategy_name* is not registered.
    """
    if strategy_name not in _STRATEGY_REGISTRY:
        raise KeyError(
            f"Unknown strategy {strategy_name!r}. "
            f"Available: {list(_STRATEGY_REGISTRY)}"
        )
    rng = random.Random(seed)
    return _STRATEGY_REGISTRY[strategy_name](rng)


def generate_all(*, seed: int | str | None = None) -> list[AdversarialPair]:
    """Generate one :class:`AdversarialPair` for every registered strategy.

    Parameters
    ----------
    seed:
        Optional seed for the internal :class:`random.Random` instance
        shared across all strategy calls.  Passing the same *seed* always
        produces the same list (deterministic / reproducible).  Omitting
        *seed* (or passing ``None``) draws OS entropy, yielding a unique
        result each time.

    Returns
    -------
    list[AdversarialPair]
        One entry per strategy, in registration order.
    """
    rng = random.Random(seed)
    return [factory(rng) for factory in _STRATEGY_REGISTRY.values()]
