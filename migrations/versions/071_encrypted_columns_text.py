"""071 — encrypted columns are TEXT: a ciphertext does not fit the plaintext's width.

``shared.encryption.encrypt_field`` stores ``base64(wrapped data key || Fernet token)``. With a key configured that is
roughly 260 characters for a 10-digit number against an in-memory KMS, and more against real AWS KMS or Azure Key
Vault, whose wrapped keys are larger. Three encrypted columns kept the width of the plaintext they replaced:

* ``refund_request.account_number`` VARCHAR(50)
* ``refund_request.account_name`` VARCHAR(255)
* ``pickup_record.id_number`` VARCHAR(100)

so every write would have failed with ``StringDataRightTruncation`` once encryption was switched on (it is off in local
dev, where values are stored as plaintext). Nothing wrote the two refund columns before 2026-11-19, when the customer
refund form started collecting bank details; recording a pickup with an ID number would have failed in production.

Widening VARCHAR to TEXT rewrites no rows.

Revision ID: 071
Revises: 070
Create Date: 2026-11-19 16:00:00
"""

from alembic import op

revision = "071"
down_revision = "070"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE refund_request
            ALTER COLUMN account_number TYPE TEXT,
            ALTER COLUMN account_name TYPE TEXT
        """
    )
    op.execute("ALTER TABLE pickup_record ALTER COLUMN id_number TYPE TEXT")


def downgrade() -> None:
    # Fails if a stored ciphertext is longer than the old width, which is the point: do not truncate encrypted data.
    op.execute("ALTER TABLE pickup_record ALTER COLUMN id_number TYPE VARCHAR(100)")
    op.execute(
        """
        ALTER TABLE refund_request
            ALTER COLUMN account_number TYPE VARCHAR(50),
            ALTER COLUMN account_name TYPE VARCHAR(255)
        """
    )
