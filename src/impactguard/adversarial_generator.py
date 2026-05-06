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

from dataclasses import dataclass, field
from typing import Any


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


def _strategy_required_param_hidden_by_type_annotation() -> AdversarialPair:
    """Add a required positional parameter while also annotating an existing one.

    The type annotation on the first parameter is a genuine non-breaking
    improvement.  A reviewer (or a naive tool) might focus on that and miss
    that ``c`` is required and has no default.
    """
    fqname = "mymodule:process"
    old = [
        _sig(
            fqname,
            positional=[_param("a"), _param("b")],
        )
    ]
    new = [
        _sig(
            fqname,
            positional=[
                _param("a", type_="str"),      # annotation added — looks like improvement
                _param("b"),
                _param("c"),                    # ← BREAKING: required, no default
            ],
        )
    ]
    return AdversarialPair(
        strategy_name="required_param_hidden_by_type_annotation",
        description=(
            "A new required positional parameter is added alongside a harmless "
            "type annotation on an existing parameter."
        ),
        camouflage_notes=(
            "The type annotation on 'a' is genuinely non-breaking and draws "
            "attention away from the silent introduction of the required 'c'."
        ),
        old_signatures=old,
        new_signatures=new,
        expected_breaking_patterns=["REQUIRED POSITIONAL ADDED", fqname],
        expected_nonbreaking_patterns=["TYPE WIDENED"],
    )


def _strategy_positional_reorder_hidden_by_optional_add() -> AdversarialPair:
    """Swap two positional parameters while also adding an optional one.

    The optional addition is non-breaking noise that can make the diff look
    like a pure expansion of the API.
    """
    fqname = "mymodule:transfer"
    old = [
        _sig(
            fqname,
            positional=[_param("source"), _param("destination")],
        )
    ]
    new = [
        _sig(
            fqname,
            positional=[
                _param("destination"),          # ← BREAKING: reorder
                _param("source"),
                _param("timeout", has_default=True),  # non-breaking noise
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
            "The optional 'timeout' addition produces a NONBREAKING entry, "
            "making the diff look like a pure feature addition."
        ),
        old_signatures=old,
        new_signatures=new,
        expected_breaking_patterns=["POSITIONAL REORDER", fqname],
        expected_nonbreaking_patterns=["OPTIONAL POSITIONAL ADDED", fqname],
    )


def _strategy_type_narrowing_disguised_as_cleanup() -> AdversarialPair:
    """Narrow a parameter type from ``str | None`` to ``str``.

    This looks like a cleanup or a "we no longer accept None" guarantee, but
    callers that previously passed ``None`` will break at runtime.
    """
    fqname = "mymodule:render"
    old = [
        _sig(
            fqname,
            positional=[_param("template", type_="str | None")],
        )
    ]
    new = [
        _sig(
            fqname,
            positional=[_param("template", type_="str")],  # ← BREAKING: narrowing
        )
    ]
    return AdversarialPair(
        strategy_name="type_narrowing_disguised_as_cleanup",
        description=(
            "A parameter's type is narrowed from 'str | None' to 'str', "
            "breaking callers that pass None."
        ),
        camouflage_notes=(
            "Removing 'None' from a type union reads as a type-safety improvement "
            "or stricter validation, not as a breaking contract change."
        ),
        old_signatures=old,
        new_signatures=new,
        expected_breaking_patterns=["TYPE CHANGED", fqname, "template"],
        expected_nonbreaking_patterns=[],
    )


def _strategy_kwonly_removal_with_optional_addition() -> AdversarialPair:
    """Remove a required keyword-only argument while adding an optional one.

    The optional addition emits a NONBREAKING entry, masking the BREAKING
    removal.
    """
    fqname = "mymodule:connect"
    old = [
        _sig(
            fqname,
            positional=[_param("host")],
            kwonly=[_param("auth_token")],          # required kwonly
        )
    ]
    new = [
        _sig(
            fqname,
            positional=[_param("host")],
            kwonly=[_param("timeout", has_default=True)],  # optional — noise
            # auth_token silently removed ← BREAKING
        )
    ]
    return AdversarialPair(
        strategy_name="kwonly_removal_with_optional_addition",
        description=(
            "A required keyword-only argument is removed while an optional "
            "keyword argument is added."
        ),
        camouflage_notes=(
            "The addition of 'timeout' generates a NONBREAKING signal and looks "
            "like a feature enhancement, hiding the removal of 'auth_token'."
        ),
        old_signatures=old,
        new_signatures=new,
        expected_breaking_patterns=["KWONLY REMOVED", fqname],
        expected_nonbreaking_patterns=["OPTIONAL KWONLY ADDED", fqname],
    )


def _strategy_vararg_removal_with_kwarg_addition() -> AdversarialPair:
    """Remove ``*args`` while simultaneously adding ``**kwargs``.

    ``**kwargs`` makes the signature look more flexible, but callers relying
    on positional variadic arguments will break.
    """
    fqname = "mymodule:log_event"
    old = [
        _sig(fqname, positional=[_param("event")], vararg=True)
    ]
    new = [
        _sig(fqname, positional=[_param("event")], vararg=False, kwarg=True)
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


def _strategy_return_type_narrowing_disguised_as_guarantee() -> AdversarialPair:
    """Narrow the return type from ``str | None`` to ``str``.

    Callers that branch on ``None`` will now have dead-code paths or runtime
    errors if the implementation ever still returns ``None`` in practice.
    """
    fqname = "mymodule:fetch_name"
    old = [
        _sig(fqname, positional=[_param("user_id")], return_type="str | None")
    ]
    new = [
        _sig(fqname, positional=[_param("user_id")], return_type="str")
        # BREAKING: return type narrowed
    ]
    return AdversarialPair(
        strategy_name="return_type_narrowing_disguised_as_guarantee",
        description=(
            "The return type is narrowed from 'str | None' to 'str', "
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


def _strategy_decorator_removal_hidden_by_optional_kwarg() -> AdversarialPair:
    """Remove a ``@cache`` decorator while adding an optional ``force`` kwarg.

    The optional kwarg is non-breaking; the decorator removal changes the
    function's caching semantics and calling convention for callers that
    depend on them.
    """
    fqname = "mymodule:get_config"
    old = [
        _sig(fqname, positional=[_param("key")], decorators=["cache"])
    ]
    new = [
        _sig(
            fqname,
            positional=[_param("key")],
            kwonly=[_param("force", has_default=True)],  # noise
            decorators=[],  # ← BREAKING: cache decorator removed
        )
    ]
    return AdversarialPair(
        strategy_name="decorator_removal_hidden_by_optional_kwarg",
        description=(
            "A ``@cache`` decorator is removed while an optional keyword-only "
            "argument is added."
        ),
        camouflage_notes=(
            "The 'force' kwarg looks like a cache-invalidation option being added, "
            "which could be mistaken for a caching improvement rather than removal."
        ),
        old_signatures=old,
        new_signatures=new,
        expected_breaking_patterns=["DECORATOR REMOVED", fqname],
        expected_nonbreaking_patterns=["OPTIONAL KWONLY ADDED", fqname],
    )


def _strategy_required_kwonly_added_with_misleading_name() -> AdversarialPair:
    """Add a required keyword-only parameter whose name implies optionality.

    Naming a required parameter ``optional_context`` or ``extra_info``
    suggests it is supplementary, but the absence of a default makes it
    mandatory.
    """
    fqname = "mymodule:create_session"
    old = [
        _sig(fqname, positional=[_param("user_id")])
    ]
    new = [
        _sig(
            fqname,
            positional=[_param("user_id")],
            kwonly=[_param("optional_context")],  # ← BREAKING: no default!
        )
    ]
    return AdversarialPair(
        strategy_name="required_kwonly_added_with_misleading_name",
        description=(
            "A required keyword-only parameter named 'optional_context' is added, "
            "breaking callers that do not supply it."
        ),
        camouflage_notes=(
            "The word 'optional' in the parameter name implies it has a default, "
            "leading reviewers to classify it as a safe addition."
        ),
        old_signatures=old,
        new_signatures=new,
        expected_breaking_patterns=["REQUIRED KWONLY ADDED", fqname],
        expected_nonbreaking_patterns=[],
    )


def _strategy_function_removal_hidden_by_rename_addition() -> AdversarialPair:
    """Remove a public function while adding a similarly-named replacement.

    From a diff perspective the change looks like a rename / upgrade, but any
    caller importing the old name will get an ``AttributeError``.
    """
    old_fqname = "mymodule:parse_config"
    new_fqname = "mymodule:parse_config_v2"
    old = [
        _sig(old_fqname, positional=[_param("path")])
    ]
    new = [
        _sig(new_fqname, positional=[_param("path"), _param("strict", has_default=True)])
        # old function REMOVED ← BREAKING; new function ADDED ← noise
    ]
    return AdversarialPair(
        strategy_name="function_removal_hidden_by_rename_addition",
        description=(
            "The original function is removed and a new '_v2' variant is added, "
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


def _strategy_kwargs_removal_hidden_by_explicit_params() -> AdversarialPair:
    """Replace ``**kwargs`` with explicit optional parameters.

    The change looks like an API clarity improvement, but callers that pass
    arbitrary keyword arguments (not in the explicit list) will get a
    ``TypeError``.
    """
    fqname = "mymodule:send_request"
    old = [
        _sig(fqname, positional=[_param("url")], kwarg=True)
    ]
    new = [
        _sig(
            fqname,
            positional=[_param("url")],
            kwonly=[
                _param("timeout", has_default=True),
                _param("retries", has_default=True),
                _param("verify_ssl", has_default=True),
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
            "Adding named parameters looks like better documentation and IDE support. "
            "The loss of forward-compatibility for unknown kwargs is easy to miss."
        ),
        old_signatures=old,
        new_signatures=new,
        expected_breaking_patterns=["**kwargs REMOVED", fqname],
        expected_nonbreaking_patterns=["OPTIONAL KWONLY ADDED", fqname],
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_STRATEGY_REGISTRY: dict[str, Any] = {
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


def generate(strategy_name: str) -> AdversarialPair:
    """Generate an :class:`AdversarialPair` for the named strategy.

    Parameters
    ----------
    strategy_name:
        One of the names returned by :func:`list_strategies`.

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
    return _STRATEGY_REGISTRY[strategy_name]()


def generate_all() -> list[AdversarialPair]:
    """Generate one :class:`AdversarialPair` for every registered strategy.

    Returns
    -------
    list[AdversarialPair]
        One entry per strategy, in registration order.
    """
    return [factory() for factory in _STRATEGY_REGISTRY.values()]
