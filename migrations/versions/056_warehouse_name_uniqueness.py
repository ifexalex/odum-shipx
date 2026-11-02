"""056 — scope warehouse name uniqueness to active rows.

Migration 041 declared `UNIQUE (tenant_id, name)` across *every* row of
`warehouse`. Deletion, however, was soft (`is_active = FALSE`), so a removed
warehouse kept its name reserved permanently: recreating "Lagos — Trade Fair"
after removing it failed, and surfaced as a raw unique-violation rather than a
message a user could act on. Reported from live use — "I deleted it and tried to
recreate it again. I was not able to until I changed the name."

Two changes make the name space behave the way an operator expects:

1. The table-wide constraint becomes a **partial** unique index covering only
   `is_active` rows, so a deactivated warehouse no longer blocks its own name.
   An active tenant still cannot hold two warehouses called the same thing.
2. `release_note`/`pickup_record`/`payment_record` keep their FK with no
   ON DELETE action **on purpose** — deleting a warehouse that a handover
   document references must stay refused at the database level. The service
   checks for references first and returns a 422 naming them, so the FK is the
   backstop rather than the error the user sees.

Note on duplicates already in the table: the old global constraint guaranteed at
most one row per (tenant_id, name), so every existing row satisfies the narrower
partial index and no data needs cleaning first.
"""

from alembic import op

revision = "056"
down_revision = "055"


def upgrade() -> None:
    # Postgres names a column-list UNIQUE constraint <table>_<cols>_key. Drop by
    # that name but tolerate its absence, so a database created from a later
    # baseline (or one already repaired by hand) still migrates.
    op.execute("ALTER TABLE warehouse DROP CONSTRAINT IF EXISTS warehouse_tenant_id_name_key")
    # Also drop any index of that name — DROP CONSTRAINT removes the backing
    # index, but a hand-created index would otherwise survive and keep enforcing
    # the old, table-wide rule.
    op.execute("DROP INDEX IF EXISTS warehouse_tenant_id_name_key")
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_warehouse_active_name
            ON warehouse(tenant_id, name)
            WHERE is_active
        """
    )


def downgrade() -> None:
    # Reinstating the table-wide constraint can fail if inactive rows now share a
    # name with an active one — exactly the state this migration permits. Drop
    # the partial index first and let the ADD CONSTRAINT surface that conflict
    # loudly rather than silently discarding a row.
    op.execute("DROP INDEX IF EXISTS idx_warehouse_active_name")
    op.execute("ALTER TABLE warehouse ADD CONSTRAINT warehouse_tenant_id_name_key UNIQUE (tenant_id, name)")
