"""057 — country on warehouse.

The warehouse form asks for a State, but the table had no country, so "State"
had no anchor: a picker could only guess which country's subdivisions to offer.
Adding the country makes the address self-describing and lets the state field be
a real dropdown (Nigeria's 36 states + FCT today, another market's later)
instead of free text.

Backfilled from each tenant's own `destination_country` rather than a blanket
'Nigeria': warehouses are the destination-side branches, so the tenant's
configured destination is the correct answer for existing rows, and a tenant
already set up for a different market does not get silently mislabelled.
`NOT NULL DEFAULT 'Nigeria'` after the backfill keeps the platform's primary
market as the default for new rows.
"""

from alembic import op

revision = "057"
down_revision = "056"


def upgrade() -> None:
    # Added nullable first so the backfill decides each row's value, rather than
    # the column default stamping 'Nigeria' onto every existing warehouse.
    op.execute("ALTER TABLE warehouse ADD COLUMN IF NOT EXISTS country VARCHAR(100)")
    op.execute(
        """
        UPDATE warehouse w
           SET country = COALESCE(NULLIF(TRIM(t.destination_country), ''), 'Nigeria')
          FROM tenant t
         WHERE t.id = w.tenant_id
           AND w.country IS NULL
        """
    )
    # Any row whose tenant somehow went missing (shouldn't happen — the FK is
    # ON DELETE RESTRICT — but the NOT NULL below would fail on it).
    op.execute("UPDATE warehouse SET country = 'Nigeria' WHERE country IS NULL")
    op.execute("ALTER TABLE warehouse ALTER COLUMN country SET DEFAULT 'Nigeria'")
    op.execute("ALTER TABLE warehouse ALTER COLUMN country SET NOT NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE warehouse DROP COLUMN IF EXISTS country")
