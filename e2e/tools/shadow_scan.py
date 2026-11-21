"""Usage: python -I e2e/tools/shadow_scan.py backend/app

Read-only AST scan: names that shadow an imported module / imported name.

1. class body: an annotated field whose name equals a module-level import that is used in an
   annotation *after* it in the same class (the `github: github.GitHub` / `date: date` bug).
2. any class field / function parameter / local assignment named like a module-level import
   (weaker: only a problem if the import is used later in that scope).
"""

import ast
import sys
from pathlib import Path


def imported_names(tree: ast.Module) -> dict[str, int]:
    names: dict[str, int] = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                names[(alias.asname or alias.name).split(".")[0]] = node.lineno
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names[alias.asname or alias.name] = node.lineno
        elif isinstance(node, ast.If):  # TYPE_CHECKING blocks
            for sub in node.body:
                if isinstance(sub, ast.Import | ast.ImportFrom):
                    for alias in sub.names:
                        names[(alias.asname or alias.name).split(".")[0]] = sub.lineno
    return names


def names_in(node: ast.AST | None) -> set[str]:
    if node is None:
        return set()
    found = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
    # string annotations
    for n in ast.walk(node):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            try:
                found |= names_in(ast.parse(n.value, mode="eval"))
            except SyntaxError:
                pass
    return found


def scan(path: Path) -> list[str]:
    out: list[str] = []
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = imported_names(tree)
    for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
        body = cls.body
        for i, stmt in enumerate(body):
            target = None
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                target = stmt.target.id
            elif isinstance(stmt, ast.Assign):
                for t in stmt.targets:
                    if isinstance(t, ast.Name):
                        target = t.id
            if target is None or target not in imports:
                continue
            later = set()
            for after in body[i + 1 :]:
                if isinstance(after, ast.AnnAssign):
                    later |= names_in(after.annotation) | names_in(after.value)
                elif isinstance(after, ast.Assign):
                    later |= names_in(after.value)
                elif isinstance(after, ast.FunctionDef | ast.AsyncFunctionDef):
                    # default values and decorators are evaluated in class scope
                    later |= names_in(after.args) - {a.arg for a in after.args.args}
                    for d in after.decorator_list:
                        later |= names_in(d)
            own = names_in(stmt.annotation) if isinstance(stmt, ast.AnnAssign) else set()
            severity = "RISK" if target in later or target in own else "shadow"
            out.append(f"{severity}: {path}:{stmt.lineno} class {cls.name}: field `{target}` shadows import (line {imports[target]})")
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]:
        params = [a.arg for a in fn.args.args + fn.args.kwonlyargs + fn.args.posonlyargs]
        body_names = set()
        for n in ast.walk(fn):
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name):
                body_names.add(n.value.id)
        for p in params:
            if p in imports and p in body_names:
                out.append(f"RISK?: {path}:{fn.lineno} def {fn.name}: parameter `{p}` shadows import and `{p}.attr` is used")
        for n in ast.walk(fn):
            if isinstance(n, ast.Assign):
                for t in n.targets:
                    if isinstance(t, ast.Name) and t.id in imports and t.id in body_names:
                        out.append(f"RISK?: {path}:{n.lineno} def {fn.name}: local `{t.id}` shadows import and `{t.id}.attr` is used")
    return out


if __name__ == "__main__":
    root = Path(sys.argv[1])
    for file in sorted(root.rglob("*.py")):
        for line in scan(file):
            print(line)
