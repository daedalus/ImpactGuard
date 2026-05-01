import ast
import json
import sys
from pathlib import Path

# ImpactGuard signature extractor

def serialize_function(node, file):
    def arg_info(arg, default):
        return {
            "name": arg.arg,
            "has_default": default is not None
        }

    args = node.args

    pos = []
    defaults = [None] * (len(args.args) - len(args.defaults)) + args.defaults
    for a, d in zip(args.args, defaults):
        pos.append(arg_info(a, d))

    kwonly = []
    for a, d in zip(args.kwonlyargs, args.kw_defaults):
        kwonly.append(arg_info(a, d))

    return {
        "fqname": f"{file}:{node.name}",
        "name": node.name,
        "positional": pos,
        "kwonly": kwonly,
        "vararg": args.vararg is not None,
        "kwarg": args.kwarg is not None,
    }

def extract(path):
    try:
        tree = ast.parse(path.read_text())
    except Exception:
        return []

    out = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append(serialize_function(node, str(path)))
    return out

def main():
    files = sys.argv[1:]
    all_funcs = []

    for f in files:
        all_funcs.extend(extract(Path(f)))

    # stable ordering
    all_funcs.sort(key=lambda x: x["fqname"])

    print(json.dumps(all_funcs, indent=2))

def dummy_func(x: int, y: str = "default") -> bool:
    return True

if __name__ == "__main__":
    main()
