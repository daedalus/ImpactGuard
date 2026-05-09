try:
    import libcst as cst
    from libcst import matchers as m

    LIBCST_AVAILABLE = True

    # Supported patch transformations:
    #   AddDefaultTransformer — adds a default value to an existing parameter
    #       on the function definition side (covers OPTIONAL / REQUIRED changes).
    #   FixCallTransformer — injects a missing keyword argument at every call
    #       site (covers REQUIRED_POSITIONAL_ADDED and similar changes).
    #
    # NOTE: POSITIONAL_REORDER (reordering of positional parameters) is
    # intentionally NOT handled by the patch generator.  Such a change requires
    # updating *every* positional call site in the correct order, which cannot
    # be done safely without full type-inference.  When a diff contains a
    # POSITIONAL_REORDER entry, no patch will be produced and the caller must
    # make the fix manually.

    class AddDefaultTransformer(cst.CSTTransformer):
        def __init__(self, func_name: str, param_name: str) -> None:
            self.func_name = func_name
            self.param_name = param_name

        def leave_FunctionDef(  # noqa: N802, V105
            self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef
        ) -> cst.FunctionDef:
            if original_node.name.value != self.func_name:
                return updated_node

            new_params = []

            for p in updated_node.params.params:
                if p.name.value == self.param_name and p.default is None:
                    new_params.append(p.with_changes(default=cst.Name("None")))
                else:
                    new_params.append(p)

            return updated_node.with_changes(
                params=updated_node.params.with_changes(params=new_params)
            )

    class FixCallTransformer(cst.CSTTransformer):
        def __init__(self, func_name: str, param_name: str) -> None:
            self.func_name = func_name
            self.param_name = param_name

        def leave_Call(  # noqa: N802, V105
            self, original_node: cst.Call, updated_node: cst.Call
        ) -> cst.Call:
            # match foo(...)
            if m.matches(original_node.func, m.Name(self.func_name)):
                # skip if already provided
                for arg in original_node.args:
                    if arg.keyword and arg.keyword.value == self.param_name:
                        return updated_node

                new_arg = cst.Arg(
                    keyword=cst.Name(self.param_name), value=cst.Name("FIXME")
                )

                return updated_node.with_changes(
                    args=list(updated_node.args) + [new_arg]
                )

            return updated_node

except ImportError:
    LIBCST_AVAILABLE = False

    class AddDefaultTransformer:  # type: ignore[no-redef]
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            raise ImportError("libcst not installed")

    class FixCallTransformer:  # type: ignore[no-redef]
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            raise ImportError("libcst not installed")


def patch_function(
    source: str, func_name: str, param_name: str
) -> tuple[str | None, str | None]:
    if not LIBCST_AVAILABLE:
        return None, "libcst not installed"

    try:
        tree = cst.parse_module(source)
        transformer = AddDefaultTransformer(func_name, param_name)
        modified = tree.visit(transformer)
        return modified.code, None
    except Exception as e:
        return None, str(e)


def patch_call(
    source: str, func_name: str, param_name: str
) -> tuple[str | None, str | None]:
    if not LIBCST_AVAILABLE:
        return None, "libcst not installed"

    try:
        tree = cst.parse_module(source)
        transformer = FixCallTransformer(func_name, param_name)
        modified = tree.visit(transformer)
        return modified.code, None
    except Exception as e:
        return None, str(e)
