"""Sprint 3 D5 — Migration 0012 syntax + reversibility sanity check.

Loads the migration module by file path and asserts:
  - `upgrade` and `downgrade` are callable
  - `revision` and `down_revision` chain into 0011
  - both functions reference `one_current_goals` (the canonical index name)

A full upgrade/downgrade/upgrade cycle against a real Postgres lives in
tests/integration/ and is skipped without Docker.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "migrations"
    / "versions"
    / "0012_nutritional_goals_active_unique.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("mig_0012", _MIGRATION)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_migration_metadata():
    m = _load()
    assert m.revision == "0012_nutritional_goals_active_unique"
    assert m.down_revision == "0011_vision_jobs_sha_idx"
    assert m.branch_labels is None


def test_upgrade_and_downgrade_callable():
    m = _load()
    assert callable(m.upgrade)
    assert callable(m.downgrade)


def test_index_name_canonical():
    """The index must reuse the name `one_current_goals` from 0001 so
    the upgrade is a no-op against any cleanly-migrated database."""
    raw = _MIGRATION.read_text()
    assert "one_current_goals" in raw
    assert "IF NOT EXISTS" in raw  # idempotent upgrade
    assert "IF EXISTS" in raw  # idempotent downgrade
    assert "CONCURRENTLY" in raw  # non-blocking on live table
