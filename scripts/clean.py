#!/usr/bin/env python3
"""Wipe all runtime artifacts for a clean simulation run.

Usage:
    python scripts/clean.py          # interactive confirmation
    python scripts/clean.py --yes    # skip confirmation
"""

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

TARGETS = [
    # Memory stores
    ROOT / "data" / "memory",

    # Collected data
    ROOT / "data" / "collected",

    # CrewAI runtime storage
    ROOT / "data" / "crewai_storage",
    ROOT / "data" / "crewai_local",
    ROOT / "data" / "crewai_storage_runtime",
    ROOT / "data" / "crewai_local_runtime",
]

# Workspace files to remove (everything except .gitkeep)
WORKSPACE_DIR = ROOT / "workspace"

# Files/dirs that should survive cleaning
WORKSPACE_KEEP = {".gitkeep", ".gitignore"}


def _workspace_generated_files() -> list[Path]:
    """List workspace files that are generated (not tracked/kept)."""
    if not WORKSPACE_DIR.exists():
        return []
    items = []
    for p in WORKSPACE_DIR.iterdir():
        if p.name in WORKSPACE_KEEP:
            continue
        items.append(p)
    return items


def _remove(path: Path) -> tuple[str, bool]:
    """Remove a file or directory.

    Returns
    -------
    tuple[str, bool]
        Status line and whether removal succeeded.
    """
    rel = path.relative_to(ROOT)
    if not path.exists():
        return f"  skip  {rel}  (not found)", True

    try:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        return f"  rm    {rel}", True
    except PermissionError as exc:
        return f"  busy  {rel}  ({exc})", False
    except OSError as exc:
        return f"  fail  {rel}  ({exc})", False


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean runtime artifacts for a fresh run.")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")
    args = parser.parse_args()

    all_paths = list(TARGETS) + _workspace_generated_files()

    existing = [p for p in all_paths if p.exists()]
    if not existing:
        print("Nothing to clean — already fresh.")
        return

    print("Will remove:")
    for p in existing:
        label = "dir " if p.is_dir() else "file"
        print(f"  {label}  {p.relative_to(ROOT)}")

    if not args.yes:
        answer = input("\nProceed? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("Aborted.")
            sys.exit(1)

    print()
    failures = 0
    for p in all_paths:
        line, ok = _remove(p)
        print(line)
        if not ok:
            failures += 1

    if failures:
        print(
            "\nDone with warnings. "
            f"{failures} path(s) could not be removed (likely in use by another process)."
        )
        print("Stop running simulations/servers and rerun clean.")
        sys.exit(2)

    print("\nDone. Ready for a clean run.")


if __name__ == "__main__":
    main()
