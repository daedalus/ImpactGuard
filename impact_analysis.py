import json
import sys

def load_funcs(path):
    data = json.load(open(path))
    return {f["name"]: f for f in data}  # still lossy

def load_calls(path):
    return json.load(open(path))


def required_positional(func):
    return sum(1 for a in func["positional"] if not a["has_default"])

def total_positional(func):
    return len(func["positional"])

def normalize(name):
    return name.split(":")[-1]  # adapt if needed


funcs = load_funcs(sys.argv[1])
calls = load_calls(sys.argv[2])

issues = []

for call in calls:
    target = call["name"]

    # try exact match
    if target not in funcs:
        # fallback: match by suffix (last part)
        matches = [f for f in funcs if f.endswith("." + target.split(".")[-1])]
        if len(matches) == 1:
            target = matches[0]
        else:
            continue

    f = funcs[target]

    if call["has_starargs"] or call["has_kwargs"]:
        continue

    min_args = required_positional(f)
    max_args = total_positional(f) if not f["vararg"] else float("inf")

    argc = call["args"]

    if argc < min_args:
        issues.append(f"{call['file']}:{call['lineno']} -> {target} missing args ({argc} < {min_args})")
    elif argc > max_args:
        issues.append(f"{call['file']}:{call['lineno']} -> {target} too many args ({argc} > {max_args})")

print("=== POTENTIAL BREAKAGES ===")
print("\n".join(issues) or "None")

if issues:
    sys.exit(1)
