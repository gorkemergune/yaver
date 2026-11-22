"""Import every module under app/ on its own, each in a fresh Python process.

Why: one process importing everything (tests/test_smoke.py, the running API) loads the
modules in one order, and a circular import that only breaks in another order stays
hidden. `python -m app.materials.bundle` on live failed that way (2026-11-22):
bundle -> ingest -> mapping -> app.agent.tools (registers every tool) -> tools/materials
-> ingest (half loaded) -> ImportError. Here each module is the first thing imported.

    python scripts/import_each.py                 all of app/ (from backend/)
    python scripts/import_each.py app.materials   one package
Exit 1 and the error's last lines for every module that fails. Used by
tests/test_import_each.py, the pre-commit hook and scripts/deploy-live.ps1.
"""

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
TIMEOUT_S = 120


def modules(root: Path = BACKEND, prefix: str = "app") -> list[str]:
    """Module names from the files (no import needed to list them; __main__ skipped)."""
    found = []
    for path in sorted((root / "app").rglob("*.py")):
        parts = path.relative_to(root).with_suffix("").parts
        if parts[-1] == "__main__" or "__pycache__" in parts:
            continue
        if parts[-1] == "__init__":
            parts = parts[:-1]
        name = ".".join(parts)
        if name == prefix or name.startswith(prefix + "."):
            found.append(name)
    return found


def import_alone(module: str) -> str | None:
    """None when `import <module>` works in a fresh interpreter, else the error's tail."""
    env = {**os.environ, "PYTHONPATH": str(BACKEND), "PYTHONDONTWRITEBYTECODE": "1"}
    try:
        done = subprocess.run(
            [sys.executable, "-c", f"import {module}"],
            cwd=BACKEND,
            env=env,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return f"timed out after {TIMEOUT_S} s"
    if done.returncode == 0:
        return None
    lines = done.stderr.strip().splitlines()
    return "\n".join(lines[-6:]) or f"exit {done.returncode}"


def failures(names: list[str], workers: int | None = None) -> dict[str, str]:
    workers = workers or min(8, os.cpu_count() or 2)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = pool.map(import_alone, names)
    return {name: error for name, error in zip(names, results, strict=True) if error}


def main(argv: list[str]) -> int:
    prefix = argv[0] if argv else "app"
    names = modules(prefix=prefix)
    if not names:
        print(f"no module under {prefix}")
        return 1
    failed = failures(names)
    for name, error in failed.items():
        print(f"FAIL {name}\n    " + error.replace("\n", "\n    "))
    print(f"{len(names) - len(failed)}/{len(names)} modules import on their own")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
