import json
import sys

def load(path):
    with open(path) as f:
        data = json.load(f)
    return {f["fqname"]: f for f in data}

def is_required(arg):
    return not arg["has_default"]

old = load(sys.argv[1])
new = load(sys.argv[2])

breaking = []
nonbreaking = []

# Removed functions
for k in old:
    if k not in new:
        breaking.append(f"REMOVED: {k}")

# Added functions
for k in new:
    if k not in old:
        nonbreaking.append(f"ADDED: {k}")

# Compare shared
for k in old:
    if k not in new:
        continue

    o = old[k]
    n = new[k]

    o_pos = o["positional"]
    n_pos = n["positional"]

    # positional argument removal
    if len(n_pos) < len(o_pos):
        breaking.append(f"POSITIONAL REMOVED: {k}")
        continue

    # positional arg changes
    for i in range(len(o_pos)):
        if o_pos[i]["name"] != n_pos[i]["name"]:
            breaking.append(f"POSITIONAL REORDER/RENAME: {k}")
            break

    # new positional args
    if len(n_pos) > len(o_pos):
        added = n_pos[len(o_pos):]
        if any(is_required(a) for a in added):
            breaking.append(f"REQUIRED POSITIONAL ADDED: {k}")
        else:
            nonbreaking.append(f"OPTIONAL POSITIONAL ADDED: {k}")

    # kwonly args
    o_kw = {a["name"]: a for a in o["kwonly"]}
    n_kw = {a["name"]: a for a in n["kwonly"]}

    for name in o_kw:
        if name not in n_kw:
            breaking.append(f"KWONLY REMOVED: {k}")

    for name in n_kw:
        if name not in o_kw:
            if is_required(n_kw[name]):
                breaking.append(f"REQUIRED KWONLY ADDED: {k}")
            else:
                nonbreaking.append(f"OPTIONAL KWONLY ADDED: {k}")

    # varargs changes
    if o["vararg"] and not n["vararg"]:
        breaking.append(f"*args REMOVED: {k}")

    if o["kwarg"] and not n["kwarg"]:
        breaking.append(f"**kwargs REMOVED: {k}")

print("=== BREAKING ===")
print("\n".join(sorted(set(breaking))) or "None")

print("\n=== NON-BREAKING ===")
print("\n".join(sorted(set(nonbreaking))) or "None")

if breaking:
    sys.exit(1)
