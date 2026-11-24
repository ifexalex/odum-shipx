"""062 — atomic per-tenant counters, and one live invoice per customer per container.

Two defects in the invoice path, fixed together because they interact.

Invoice numbers collided under concurrency
------------------------------------------
`get_next_invoice_seq` was ``SELECT COUNT(*) + 1 FROM billing``. Two invoices
created at the same moment for one tenant read the same count and so got the same
number; the `UNIQUE (tenant_id, invoice_number)` constraint then rejected the
second insert. Invoice generation on `cleared` swallows per-customer errors, so
that customer was simply never billed. Receipt and release-note numbers used the
same pattern; their unique indexes made the collision loud rather than silent, but
a payment failing at random is no better.

`tenant_counter` holds one row per (tenant, name). `shared.db.next_tenant_counter`
increments it with an upsert, which takes a row lock, so concurrent callers are
serialised and every number is distinct. It is seeded here from each existing
table so numbering continues from where it is today.

Nothing stopped a second invoice for the same customer and container
--------------------------------------------------------------------
Marking a container `cleared` bills every customer on it, and the manual
`POST /v1/billing` route does the same for one pair. Calling either twice created
a second invoice. A partial unique index on live (non-cancelled) invoices makes
the second attempt impossible and lets the service return the existing one.
Cancelled invoices are excluded on purpose: cancelling and re-issuing is a
legitimate correction.

If duplicate live invoices already exist the index cannot be built, and the
migration stops with the list of them. They are money records and are not merged
or cancelled automatically — resolve them by cancelling the wrong ones, then
re-run the migration.

Revision ID: 062
Revises: 061
Create Date: 2026-11-14 00:00:00
"""

from alembic import op

revision = "062"
down_revision = "061"
branch_labels = None
depends_on = None

# (counter name, source table, SQL expression for the highest number in use).
# The seed is the larger of the row count and the highest trailing number in an
# existing reference, so the next value cannot land on a number already issued.
_SEEDS = (
    ("invoice", "billing", "invoice_number"),
    ("receipt", "payment_record", "receipt_number"),
    ("release_note", "release_note", "reference_number"),
)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE tenant_counter (
            tenant_id  UUID NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            name       VARCHAR(50) NOT NULL,
            last_value BIGINT NOT NULL DEFAULT 0 CHECK (last_value >= 0),
            PRIMARY KEY (tenant_id, name)
        )
        """
    )
    op.execute("ALTER TABLE tenant_counter ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON tenant_counter FOR ALL
        USING (
            current_setting('app.current_tenant_id', TRUE) = 'PLATFORM'
            OR tenant_id::text = current_setting('app.current_tenant_id', TRUE)
        )
        WITH CHECK (
            current_setting('app.current_tenant_id', TRUE) = 'PLATFORM'
            OR tenant_id::text = current_setting('app.current_tenant_id', TRUE)
        )
        """
    )
    op.execute("ALTER TABLE tenant_counter FORCE ROW LEVEL SECURITY")

    for name, table, column in _SEEDS:
        op.execute(
            f"""
            INSERT INTO tenant_counter (tenant_id, name, last_value)
            SELECT tenant_id,
                   '{name}',
                   GREATEST(
                       COUNT(*),
                       COALESCE(MAX(NULLIF(substring({column} FROM '(\\d{{1,9}})$'), '')::bigint), 0)
                   )
              FROM {table}
             WHERE {column} IS NOT NULL
             GROUP BY tenant_id
            """  # noqa: S608 - table/column come from the constant above, not input
        )

    op.execute(
        """
        DO $$
        DECLARE
            dupes TEXT;
        BEGIN
            SELECT string_agg(
                       format('tenant %s customer %s container %s (%s invoices)', tenant_id, customer_id, container_id, n),
                       E'\\n'
                   )
              INTO dupes
              FROM (
                  SELECT tenant_id, customer_id, container_id, COUNT(*) AS n
                    FROM billing
                   WHERE status <> 'cancelled'
                   GROUP BY tenant_id, customer_id, container_id
                  HAVING COUNT(*) > 1
              ) d;
            IF dupes IS NOT NULL THEN
                RAISE EXCEPTION
                    E'Cannot enforce one live invoice per customer per container; duplicates exist:\\n%\\n'
                    'Cancel the wrong ones, then re-run.', dupes;
            END IF;
        END $$
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX idx_billing_one_live_per_customer_container
            ON billing (tenant_id, customer_id, container_id)
         WHERE status <> 'cancelled'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_billing_one_live_per_customer_container")
    op.execute("DROP TABLE IF EXISTS tenant_counter")
