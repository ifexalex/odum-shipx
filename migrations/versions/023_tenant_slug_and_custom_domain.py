"""Add slug and custom_domain to tenant for subdomain + white-label routing.

slug       — URL-safe identifier used for subdomain routing (acme.shipx.com).
             Auto-derived from company_name on backfill.
custom_domain — optional white-label domain (track.acmelogistics.com).
             Enterprise tier only. Null for all existing tenants.

Both columns have UNIQUE constraints so tenant resolution is O(1).

Revision ID: 023
Revises: 022
Create Date: 2026-05-05 00:00:00
"""

from alembic import op

revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add nullable first so backfill can run
    op.execute("ALTER TABLE tenant ADD COLUMN slug VARCHAR(63)")
    op.execute("ALTER TABLE tenant ADD COLUMN custom_domain VARCHAR(255)")

    # Backfill slug from company_name: lowercase, non-alnum → hyphen, trim hyphens
    op.execute(
        """
        UPDATE tenant
        SET slug = LOWER(
            TRIM(BOTH '-' FROM
                REGEXP_REPLACE(
                    REGEXP_REPLACE(company_name, '[^a-zA-Z0-9]+', '-', 'g'),
                    '-+', '-', 'g'
                )
            )
        )
        WHERE slug IS NULL
        """
    )

    # Make slug NOT NULL + UNIQUE after backfill
    op.execute("ALTER TABLE tenant ALTER COLUMN slug SET NOT NULL")
    op.execute("CREATE UNIQUE INDEX tenant_slug_unique ON tenant(slug)")
    op.execute("CREATE UNIQUE INDEX tenant_custom_domain_unique ON tenant(custom_domain) WHERE custom_domain IS NOT NULL")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS tenant_custom_domain_unique")
    op.execute("DROP INDEX IF EXISTS tenant_slug_unique")
    op.execute("ALTER TABLE tenant DROP COLUMN IF EXISTS custom_domain")
    op.execute("ALTER TABLE tenant DROP COLUMN IF EXISTS slug")
