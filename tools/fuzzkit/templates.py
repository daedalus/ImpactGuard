"""Per-language source templates and character pools for regression mutators."""

from __future__ import annotations

# (comment prefix, function template, file header, file footer) per language.
# Templates use {name}; classes wrap methods for Java/C#.
LANG_TEMPLATES: dict[str, tuple[str, str, str, str]] = {
    "python": ("#", "def {name}(x, y=1):\n    return g(x)\n", "", ""),
    "ruby": ("#", "def {name}(x, y = 1)\n  g(x)\nend\n", "", ""),
    "c": ("//", "int {name}(int x, int y) {{ return g(x); }}\n", "", ""),
    "cpp": ("//", "int {name}(int x, int y) {{ return g(x); }}\n", "", ""),
    "go": (
        "//",
        "func {name}(x int, y int) int {{ return g(x) }}\n",
        "package p\n",
        "",
    ),
    "rust": ("//", "pub fn {name}(x: i32, y: i32) -> i32 {{ g(x) }}\n", "", ""),
    "javascript": (
        "//",
        "export function {name}(x, y = 1) {{ return g(x); }}\n",
        "",
        "",
    ),
    "typescript": (
        "//",
        "export function {name}(x: number, y?: number): number {{ return g(x); }}\n",
        "",
        "",
    ),
    "java": (
        "//",
        "  public int {name}(int x, int y) {{ return g(x); }}\n",
        "class A {\n",
        "}\n",
    ),
    "csharp": (
        "//",
        "  public int {name}(int x, int y) {{ return G(x); }}\n",
        "class A {\n",
        "}\n",
    ),
    "kotlin": ("//", "fun {name}(x: Int, y: Int = 1): Int {{ return g(x) }}\n", "", ""),
    "swift": (
        "//",
        "func {name}(x: Int, y: Int = 1) -> Int {{ return g(x) }}\n",
        "",
        "",
    ),
    "zig": ("//", "pub fn {name}(x: i32, y: i32) i32 {{ return g(x); }}\n", "", ""),
}

# Body statement holding a long ``1 + 1 + ...`` chain, per language.
CHAIN_FUNCS: dict[str, str] = {
    "python": "def chainfn(a):\n    s = {expr}\n    return g(a)\n",
    "ruby": "def chainfn(a)\n  s = {expr}\n  g(a)\nend\n",
    "c": "int chainfn(int a) {{ int s = {expr}; return g(a); }}\n",
    "cpp": "int chainfn(int a) {{ int s = {expr}; return g(a); }}\n",
    "go": "func chainfn(a int) int {{ s := {expr}; _ = s; return g(a) }}\n",
    "rust": "pub fn chainfn(a: i32) -> i32 {{ let s = {expr}; g(a) }}\n",
    "javascript": "export function chainfn(a) {{ const s = {expr}; return g(a); }}\n",
    "typescript": "export function chainfn(a: number): number {{ const s = {expr}; return g(a); }}\n",
    "java": "  public int chainfn(int a) {{ int s = {expr}; return g(a); }}\n",
    "csharp": "  public int chainfn(int a) {{ var s = {expr}; return G(a); }}\n",
    "kotlin": "fun chainfn(a: Int): Int {{ val s = {expr}\n return g(a) }}\n",
    "swift": "func chainfn(a: Int) -> Int {{ let s = {expr}\n return g(a) }}\n",
    "zig": "pub fn chainfn(a: i32) i32 {{ const s = {expr}; _ = s; return g(a); }}\n",
}

# Line separators that str.splitlines() honours but parsers do not.  JS/TS
# treat U+2028 as a real line terminator, so it is excluded there.
EXOTIC_SEPARATORS = ["\f", "\v", "\x1c", "\x1d", "\x1e", "\x85", " ", " "]

JS_LIKE = {"javascript", "typescript"}

CHAINED_CALL_FUNCS: dict[str, str] = {
    "python": "def outer(a):\n    return g{calls}\n",
    "javascript": "export function outer(a) {{ return g{calls}; }}\n",
    "typescript": "export function outer(a: number) {{ return g{calls}; }}\n",
    "go": "func outer(a int) int {{ return g{calls} }}\n",
    "rust": "pub fn outer(a: i32) -> i32 {{ g{calls} }}\n",
    "c": "int outer(int a) {{ return g{calls}; }}\n",
    "cpp": "int outer(int a) {{ return g{calls}; }}\n",
}

NAME_CHARS = "abcdefghijklmnopqrstuvwxyz"

PATH_SPECIALS = [" ", "é", "日", '"', "\\", "-", "ü", "\t"]
