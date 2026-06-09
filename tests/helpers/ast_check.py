"""AST-based assertions for source code analysis.

Replaces brittle string-matching (`assert "..." in source`) with
structured AST checks that survive refactors, formatting changes,
and variable renames.
"""

import ast
from pathlib import Path


def _parse(path: str | Path):
    with open(path) as f:
        return ast.parse(f.read())


def assert_call_has_arg(source_path: str | Path, func_name: str, arg_name: str) -> None:
    """Assert every call to *func_name* in *source_path* passes *arg_name* as a keyword argument.

    Handles both ``func(x, owner=…)`` and ``module.func(x, owner=…)`` patterns.
    Does NOT fail for calls inside comments, strings, or conditional branches
    that are unreachable — it walks the entire AST.
    """
    tree = _parse(source_path)
    missing = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if name != func_name:
            continue
        kwarg_names = {kw.arg for kw in node.keywords if kw.arg is not None}
        if arg_name not in kwarg_names:
            missing.append(node.lineno)
    if missing:
        lines = ", ".join(str(l) for l in missing)
        raise AssertionError(
            f"{source_path}: calls to {func_name!r} at lines [{lines}] "
            f"missing keyword argument {arg_name!r}"
        )


def assert_call_has_arg_any(source_path: str | Path, func_names: list[str], arg_name: str) -> None:
    """Like assert_call_has_arg but checks any of *func_names*."""
    tree = _parse(source_path)
    missing = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if name not in func_names:
            continue
        kwarg_names = {kw.arg for kw in node.keywords if kw.arg is not None}
        if arg_name not in kwarg_names:
            missing.append((name, node.lineno))
    if missing:
        details = "; ".join(f"{n} at line {l}" for n, l in missing)
        raise AssertionError(
            f"{source_path}: calls [{details}] "
            f"missing keyword argument {arg_name!r}"
        )


def call_count(source_path: str | Path, func_name: str) -> int:
    """Return how many times *func_name* is called in *source_path*."""
    tree = _parse(source_path)
    return sum(
        1 for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _call_name(node) == func_name
    )


def assert_contains_call(source_path: str | Path, func_name: str) -> None:
    """Assert *func_name* is called at least once in *source_path*."""
    tree = _parse(source_path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _call_name(node) == func_name:
            return
    raise AssertionError(f"{source_path}: no call to {func_name!r} found")


def assert_not_contains_call(source_path: str | Path, func_name: str) -> None:
    """Assert *func_name* is never called in *source_path*."""
    tree = _parse(source_path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _call_name(node) == func_name:
            raise AssertionError(
                f"{source_path}: call to {func_name!r} at line {node.lineno} should not exist"
            )


def assert_source_has(source_path: str | Path, pattern: str) -> None:
    """Legacy escape hatch: raw string check for patterns that AST cannot express.

    Only for assertions that truly cannot be expressed as AST checks
    (e.g. checking that a specific *value* literal like ``"owner"``
    as a string appears, not a variable name).  Prefer AST functions above.
    """
    src = Path(source_path).read_text()
    if pattern not in src:
        raise AssertionError(f"{source_path}: string {pattern!r} not found")


def _call_name(node: ast.Call) -> str:
    """Extract the qualified name of the called function.

    ``foo()`` -> ``"foo"``
    ``mod.foo()`` -> ``"foo"``
    ``obj.foo()`` -> ``"foo"``
    """
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""
