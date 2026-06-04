#!/usr/bin/env python3
"""NOVA Nutrition — Guided DB schema change workflow.

Interactive script that walks the owner through:
  1. Detecting model changes
  2. Autogenerating an Alembic migration
  3. Showing the diff for review
  4. Applying it to the local dev DB
  5. Reminding to commit

Usage:
    .venv/bin/python scripts/db_change.py

Or via Make:
    make db.new name=descriptive_name      # one-liner
    make db.help                            # workflow help
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / ".venv" / "bin" / "python"
MIGRATIONS_DIR = ROOT / "migrations" / "versions"


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    print(f"\n$ {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=ROOT, check=check)


def prompt(msg: str) -> str:
    return input(f"\n>>> {msg}\n    ").strip()


def confirm(msg: str) -> bool:
    return prompt(f"{msg} [y/N]").lower() in {"y", "yes", "si", "sí"}


def list_recent_migrations(n: int = 5) -> list[Path]:
    files = sorted(MIGRATIONS_DIR.glob("*.py"), key=lambda p: p.stat().st_mtime)
    return files[-n:]


def main() -> int:
    print("=" * 60)
    print("NOVA Nutrition — Guided DB Schema Change")
    print("=" * 60)

    name = prompt(
        "Describe the change in snake_case (e.g. add_user_subscription_tier)"
    )
    if not name or " " in name:
        print("ERROR: invalid name. Use snake_case.")
        return 1

    print("\nStep 1: Generating migration via Alembic autogenerate...")
    result = run(
        [str(PY), "-m", "alembic", "revision", "--autogenerate", "-m", name],
        check=False,
    )
    if result.returncode != 0:
        print("\nERROR: alembic revision failed. Check models + DB connection.")
        return result.returncode

    print("\nStep 2: Locating new migration file...")
    recent = list_recent_migrations(1)
    if not recent:
        print("ERROR: no migration file found.")
        return 1
    migration_file = recent[0]
    print(f"Created: {migration_file.relative_to(ROOT)}")

    print("\nStep 3: Migration preview")
    print("-" * 60)
    print(migration_file.read_text())
    print("-" * 60)

    print("\nReview checklist:")
    print("  [ ] upgrade() makes sense")
    print("  [ ] downgrade() is symmetric and safe")
    print("  [ ] No accidental drop of columns/tables")
    print("  [ ] Enum changes use op.execute (autogenerate misses these)")
    print("  [ ] Index strategy correct (CONCURRENTLY needed for prod?)")
    print("  [ ] Foreign key cascades match intent")

    if not confirm("Migration looks correct?"):
        print("\nABORTED. Edit the file manually or delete it and retry.")
        print(f"File: {migration_file}")
        return 1

    if not confirm("Apply to local dev DB now (alembic upgrade head)?"):
        print("\nMigration created but NOT applied.")
        print("Apply later with: make db.upgrade")
        return 0

    print("\nStep 4: Applying migration...")
    result = run([str(PY), "-m", "alembic", "upgrade", "head"], check=False)
    if result.returncode != 0:
        print("\nERROR: upgrade failed. Investigate, then rerun or downgrade.")
        return result.returncode

    print("\nStep 5: Verifying current revision...")
    run([str(PY), "-m", "alembic", "current"])

    print("\n" + "=" * 60)
    print("DONE")
    print("=" * 60)
    print("\nNext steps:")
    print(f"  1. Run tests:        make test")
    print(f"  2. Commit:           git add {migration_file.relative_to(ROOT)} "
          f"app/<context>/infrastructure/models.py")
    print(f"  3. Commit message:   feat(db): {name}")
    print(f"  4. Push -> Dokploy auto-runs alembic on next deploy")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\nABORTED by user.")
        sys.exit(130)
