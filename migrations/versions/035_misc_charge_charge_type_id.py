"""035 — link misc_charge to its configured charge_type.

Adds a nullable `charge_type_id` FK to `misc_charge` so a misc charge added
from a tenant's configured charge type can be attributed back to it. Powers the
charge-type usage counts on the settings page (§4.4 analytics).

Nullable by design: the `charge_type` enum column ('other', 'service_charge',
'storage_fee', …) is the wire category and stays authoritative for totals; this
FK is set only when the charge originated from a configured `charge_type` row.
Existing rows stay NULL (uncounted) — counts are accurate going forward.
ON DELETE SET NULL so deleting a charge type never blocks or orphans billing.
"""

from alembic import op

revision = "035"
down_revision = "034"


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE misc_charge
        ADD COLUMN IF NOT EXISTS charge_type_id UUID
            REFERENCES charge_type(id) ON DELETE SET NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_misc_charge_charge_type_id
            ON misc_charge(charge_type_id)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_misc_charge_charge_type_id")
    op.execute("ALTER TABLE misc_charge DROP COLUMN IF EXISTS charge_type_id")
