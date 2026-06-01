"""Plan algorithm infrastructure — plan_versions, outbox, plan_weight_vectors

- plan_versions: immutable per-user plan snapshots (provenance, A/B variant,
  weights checksum, recalibration parent pointer).
- outbox: transactional outbox for reliable event dispatch (PlanRecalibrated etc).
- plan_weight_vectors: algorithm A/B weight vectors; baseline seeded.

Weights are stored as canonical decimal strings inside JSONB to preserve
precision (Decimal-first policy — float forbidden in clinical math).
"""
import hashlib
import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0009_plan_algorithm_infra"
down_revision = "0008_recipe_micronutrients"
branch_labels = None
depends_on = None


_BASELINE_WEIGHTS = {
    "cosine_taste": "0.40",
    "jaccard_variety": "0.30",
    "prep_time": "0.10",
    "kcal_fit": "0.10",
    "goal_alignment": "0.10",
}


def _canonical_json(obj: dict) -> str:
    # Sorted-keys, no whitespace — deterministic for checksum stability.
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def upgrade() -> None:
    # ---------------------------------------------------------------- #
    # plan_versions                                                    #
    # ---------------------------------------------------------------- #
    op.create_table(
        "plan_versions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "generated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("inputs_hash", sa.Text(), nullable=False),
        sa.Column("plan", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("algorithm_version", sa.Text(), nullable=False),
        sa.Column("kcal_target", sa.Numeric(7, 2), nullable=False),
        sa.Column("macros", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "variant_id",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'baseline'"),
        ),
        sa.Column("weights_checksum", sa.Text(), nullable=False),
        sa.Column(
            "parent_plan_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("plan_versions.id"),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.UniqueConstraint("user_id", "version", name="uq_plan_versions_user_version"),
        sa.CheckConstraint(
            "status IN ('active','pending_acceptance','rejected','superseded')",
            name="ck_plan_versions_status",
        ),
        sa.CheckConstraint("version >= 1", name="ck_plan_versions_version_pos"),
        sa.CheckConstraint("kcal_target > 0", name="ck_plan_versions_kcal_pos"),
    )
    op.create_index(
        "ix_plan_versions_user_generated_desc",
        "plan_versions",
        ["user_id", sa.text("generated_at DESC")],
    )
    op.execute(
        "CREATE INDEX ix_plan_versions_pending_acceptance "
        "ON plan_versions (status) WHERE status = 'pending_acceptance'"
    )

    # ---------------------------------------------------------------- #
    # outbox                                                           #
    # ---------------------------------------------------------------- #
    op.create_table(
        "outbox",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("aggregate", sa.Text(), nullable=False),
        sa.Column("aggregate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("dispatched_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "attempts",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.CheckConstraint("attempts >= 0", name="ck_outbox_attempts_nonneg"),
    )
    op.execute(
        "CREATE INDEX outbox_undispatched_idx ON outbox (created_at) "
        "WHERE dispatched_at IS NULL"
    )
    op.create_index(
        "ix_outbox_aggregate", "outbox", ["aggregate", "aggregate_id"]
    )

    # ---------------------------------------------------------------- #
    # plan_weight_vectors                                              #
    # ---------------------------------------------------------------- #
    op.create_table(
        "plan_weight_vectors",
        sa.Column("variant_id", sa.Text(), primary_key=True),
        sa.Column("weights", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("checksum", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "weights IS NOT NULL AND jsonb_typeof(weights) = 'object'",
            name="ck_plan_weight_vectors_weights_obj",
        ),
    )

    # --- Seed baseline weight vector ---
    canonical = _canonical_json(_BASELINE_WEIGHTS)
    checksum = _sha256_hex(canonical)
    op.execute(
        sa.text(
            "INSERT INTO plan_weight_vectors "
            "(variant_id, weights, checksum, active, description) VALUES "
            "('baseline', CAST(:weights AS jsonb), :checksum, true, "
            "'H1 baseline weights')"
        ).bindparams(weights=canonical, checksum=checksum)
    )


def downgrade() -> None:
    # Reverse FK / dependency order.
    op.drop_table("plan_weight_vectors")

    op.drop_index("ix_outbox_aggregate", table_name="outbox")
    op.execute("DROP INDEX IF EXISTS outbox_undispatched_idx")
    op.drop_table("outbox")

    op.execute("DROP INDEX IF EXISTS ix_plan_versions_pending_acceptance")
    op.drop_index(
        "ix_plan_versions_user_generated_desc", table_name="plan_versions"
    )
    op.drop_table("plan_versions")
