"""0006 — billing tables (subscriptions, customers, payment_methods, invoices,
webhook_events) + enum types.

Webhook idempotency is enforced by UNIQUE(event_id).
"""
from __future__ import annotations

from alembic import op

revision = "0006_billing"
down_revision = "0005_achievements_seed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE billing_plan_enum AS ENUM ('free','premium','family');
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE billing_provider_enum AS ENUM ('stripe','mercadopago');
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE subscription_status_enum AS ENUM
                ('trialing','active','past_due','cancelled','incomplete');
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS billing_customers (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            provider billing_provider_enum NOT NULL,
            provider_customer_id text NOT NULL,
            country char(2) NOT NULL,
            currency char(3) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (provider, provider_customer_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_billing_customers_user ON billing_customers(user_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            plan billing_plan_enum NOT NULL,
            status subscription_status_enum NOT NULL,
            provider billing_provider_enum NOT NULL,
            provider_subscription_id text NULL,
            current_period_end timestamptz NULL,
            cancel_at_period_end bool NOT NULL DEFAULT false,
            trial_end timestamptz NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_subscriptions_user ON subscriptions(user_id, created_at DESC)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_subscriptions_provider_sub ON subscriptions(provider, provider_subscription_id) WHERE provider_subscription_id IS NOT NULL")

    op.execute("""
        CREATE TABLE IF NOT EXISTS payment_methods (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            provider billing_provider_enum NOT NULL,
            provider_pm_id text NOT NULL,
            brand text NULL,
            last4 text NULL,
            is_default bool NOT NULL DEFAULT false,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (provider, provider_pm_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_payment_methods_user ON payment_methods(user_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS invoices (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            provider billing_provider_enum NOT NULL,
            provider_invoice_id text NOT NULL,
            amount_cents int NOT NULL,
            currency char(3) NOT NULL,
            status text NOT NULL,
            paid_at timestamptz NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (provider, provider_invoice_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_invoices_user_created ON invoices(user_id, created_at DESC)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS webhook_events (
            event_id text PRIMARY KEY,
            provider billing_provider_enum NOT NULL,
            payload jsonb NOT NULL,
            received_at timestamptz NOT NULL DEFAULT now(),
            processed_at timestamptz NULL,
            error text NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_webhook_events_received ON webhook_events(received_at DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS webhook_events")
    op.execute("DROP TABLE IF EXISTS invoices")
    op.execute("DROP TABLE IF EXISTS payment_methods")
    op.execute("DROP TABLE IF EXISTS subscriptions")
    op.execute("DROP TABLE IF EXISTS billing_customers")
    op.execute("DROP TYPE IF EXISTS subscription_status_enum")
    op.execute("DROP TYPE IF EXISTS billing_provider_enum")
    op.execute("DROP TYPE IF EXISTS billing_plan_enum")
