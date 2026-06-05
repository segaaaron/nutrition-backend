"""Audit log immutability contract.

The `audit_log` table is the only general-purpose forensic trail in the system.
Migration 0001 declares two constraints that must hold for the life of the
project:

    REVOKE UPDATE, DELETE ON audit_log FROM PUBLIC
    REVOKE UPDATE, DELETE ON audit_log FROM nova  (the app role)

These tests pin three layers of that contract:

1. **Schema contract** — the migration text revokes UPDATE/DELETE.
2. **Codebase contract** — no Python code under `app/` issues UPDATE or DELETE
   against `audit_log` (grep at test time so any future drift fails CI fast).
3. **Runtime contract (integration)** — against a real Postgres container,
   verify that an UPDATE/DELETE issued by a normal connection is rejected,
   and that INSERT produces an immutable `ts` column.

The runtime tier is integration-gated; the first two run as unit tests.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_DIR = REPO_ROOT / "app"
MIGRATIONS_DIR = REPO_ROOT / "migrations" / "versions"


# ---------------------------------------------------------------------------
# Layer 1 — schema contract (migration text).
# ---------------------------------------------------------------------------


def test_migration_0001_revokes_update_and_delete_on_audit_log() -> None:
    """The append-only contract is part of the schema, not application code."""
    src = (MIGRATIONS_DIR / "0001_init.py").read_text(encoding="utf-8")

    # PUBLIC revoke is the catch-all.
    assert re.search(
        r"REVOKE\s+UPDATE\s*,\s*DELETE\s+ON\s+audit_log\s+FROM\s+PUBLIC",
        src,
    ), "audit_log must REVOKE UPDATE, DELETE FROM PUBLIC"

    # App role revoke wins against PUBLIC=>app grants in some hosting setups.
    assert (
        "REVOKE UPDATE, DELETE ON audit_log FROM nova" in src
    ), "audit_log must REVOKE UPDATE, DELETE FROM nova app role"


def test_audit_log_table_carries_immutable_timestamp_column() -> None:
    """`ts timestamptz NOT NULL DEFAULT now()` — no client-provided timestamps."""
    src = (MIGRATIONS_DIR / "0001_init.py").read_text(encoding="utf-8")

    # Pull the audit_log CREATE TABLE block and assert ts defaults to now().
    m = re.search(r"CREATE TABLE audit_log\s*\((.*?)\)\s*\n\s*\"\"\"\)", src, re.DOTALL)
    assert m is not None, "audit_log table definition not found"
    body = m.group(1)
    assert re.search(r"ts\s+timestamptz\s+NOT NULL\s+DEFAULT\s+now\(\)", body), (
        "audit_log.ts must be timestamptz NOT NULL DEFAULT now() so clients "
        "cannot backdate or alter the timestamp"
    )


# ---------------------------------------------------------------------------
# Layer 2 — codebase contract (no UPDATE / DELETE against audit_log).
# ---------------------------------------------------------------------------


def _grep_app(*patterns: str) -> list[str]:
    """Run a literal-string grep against app/ and return matching lines.

    We use plain ripgrep/grep so the test fails when ANY new code path
    introduces an UPDATE/DELETE against audit_log — including string-built
    SQL we'd miss with a SQLAlchemy AST walk.
    """
    matches: list[str] = []
    for pattern in patterns:
        # -F = fixed string, -I = skip binary, -n = line numbers, -r = recursive
        proc = subprocess.run(  # noqa: S603 — `grep` audit guard; inputs are literal strings owned by this test
            ["grep", "-rInF", "--include=*.py", pattern, str(APP_DIR)],  # noqa: S607 — PATH-resolved `grep` is fine in CI/dev
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.stdout:
            matches.extend(proc.stdout.strip().splitlines())
    return matches


def test_no_update_against_audit_log_anywhere_in_app() -> None:
    """Mutation of audit rows is forbidden by schema; double-check codebase."""
    forbidden = _grep_app(
        "UPDATE audit_log",
        "update(audit_log",
        "update audit_log",
    )
    assert forbidden == [], "audit_log is append-only. Found UPDATE references:\n" + "\n".join(
        forbidden
    )


def test_no_delete_against_audit_log_anywhere_in_app() -> None:
    """Including soft-delete: the table is the trail, not the data."""
    forbidden = _grep_app(
        "DELETE FROM audit_log",
        "delete(audit_log",
        "delete from audit_log",
    )
    assert forbidden == [], "audit_log is append-only. Found DELETE references:\n" + "\n".join(
        forbidden
    )


def test_audit_log_inserts_use_parameterised_sql() -> None:
    """Audit writes carry user_id + action + payload — all user-controlled.
    They MUST use bind params, never f-string substitution into INSERT.
    """
    # Find every INSERT INTO audit_log site, ensure the same line/block uses
    # SQLAlchemy text() bind parameter syntax (`:name`) and not f-string subs.
    proc = subprocess.run(  # noqa: S603 — `grep` audit guard; inputs are literal regexes owned by this test
        ["grep", "-rInE", "--include=*.py", r"INSERT INTO audit_log", str(APP_DIR)],  # noqa: S607 — PATH-resolved `grep` is fine in CI/dev
        capture_output=True,
        text=True,
        check=False,
    )
    hits = proc.stdout.strip().splitlines()
    assert hits, "expected at least one INSERT INTO audit_log site under app/"

    # Bind-parameter signature: a colon followed by an identifier, used in a
    # VALUES (...) clause near the INSERT. We check the file contains at least
    # one such bind param inside a VALUES clause, AND that no audit_log INSERT
    # site uses f-string formatting (`f"INSERT INTO audit_log`) for the row.
    bind_re = re.compile(r"VALUES\s*\([^)]*:[a-zA-Z_]\w*", re.DOTALL)
    fstring_re = re.compile(r"f[\"']\s*INSERT INTO audit_log", re.IGNORECASE)

    for hit in hits:
        # hit format: "path:lineno:matched line"
        path_str, _lineno, _line = hit.split(":", 2)
        file_src = Path(path_str).read_text(encoding="utf-8")
        assert bind_re.search(file_src), (
            f"{path_str}: audit_log INSERT site has no VALUES (...) bind "  # noqa: S608 — pytest assertion message text, not SQL
            "parameters. User-controlled fields MUST be bound."
        )
        assert not fstring_re.search(
            file_src
        ), f"{path_str}: audit_log INSERT must NEVER use f-string formatting"


# ---------------------------------------------------------------------------
# Layer 3 — runtime contract (live Postgres rejection of UPDATE / DELETE).
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_postgres_rejects_update_and_delete_on_audit_log_for_app_role() -> None:
    """Against a real Postgres + applied migrations, attempt UPDATE / DELETE
    as the `nova` app role and assert both are rejected with
    `permission denied` (insufficient_privilege)."""
    try:
        import docker as _docker

        _docker.from_env().ping()  # type: ignore[attr-defined]
    except Exception:
        pytest.skip("Docker daemon not reachable")

    import sqlalchemy as sa
    from alembic import command
    from alembic.config import Config
    from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]

    # PostgresContainer's default superuser is the username we pass. We need
    # a non-superuser `nova` role for the REVOKE to actually bite — superusers
    # bypass GRANT/REVOKE in Postgres.
    with PostgresContainer(
        image="pgvector/pgvector:pg16",
        username="postgres",
        password="postgres",  # noqa: S106 — ephemeral testcontainer admin creds
        dbname="nova_test",
    ) as pg:
        admin_url = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")

        admin_engine = sa.create_engine(admin_url)
        with admin_engine.begin() as conn:
            conn.execute(sa.text("CREATE ROLE nova WITH LOGIN PASSWORD 'nova'"))
            conn.execute(sa.text("GRANT CONNECT ON DATABASE nova_test TO nova"))
        admin_engine.dispose()

        cfg = Config(str(REPO_ROOT / "alembic.ini"))
        cfg.set_main_option("sqlalchemy.url", admin_url)
        command.upgrade(cfg, "0010_user_profile_onboarding_extensions")

        # Grant default INSERT/SELECT to nova so we can exercise the contract.
        admin_engine = sa.create_engine(admin_url)
        with admin_engine.begin() as conn:
            conn.execute(sa.text("GRANT INSERT, SELECT ON audit_log TO nova"))
            conn.execute(sa.text("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO nova"))
            # Re-apply the REVOKE — migration 0001 ran before nova existed.
            conn.execute(sa.text("REVOKE UPDATE, DELETE ON audit_log FROM nova"))
        admin_engine.dispose()

        # Now connect AS nova and verify the contract.
        nova_url = admin_url.replace("postgres:postgres", "nova:nova")
        nova_engine = sa.create_engine(nova_url)

        with nova_engine.begin() as conn:
            # INSERT is allowed.
            conn.execute(
                sa.text(
                    "INSERT INTO audit_log (actor_type, action) " "VALUES ('system', 'test_event')"
                )
            )

        # UPDATE must be rejected.
        with pytest.raises(Exception) as exc_update:
            with nova_engine.begin() as conn:
                conn.execute(sa.text("UPDATE audit_log SET action = 'tampered'"))
        assert "permission denied" in str(exc_update.value).lower()

        # DELETE must be rejected.
        with pytest.raises(Exception) as exc_delete:
            with nova_engine.begin() as conn:
                conn.execute(sa.text("DELETE FROM audit_log"))
        assert "permission denied" in str(exc_delete.value).lower()

        nova_engine.dispose()
