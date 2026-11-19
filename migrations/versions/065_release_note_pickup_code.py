"""065 — a pickup code on each release note (audit UX-09).

An in-person pickup needed only a typed collector name, so anyone who knew a release-note reference could collect the
goods. Each release note now carries a short code that is sent to the customer and that the collector must give the
warehouse attendant.

Only a keyed hash of the code is stored (``shared/pickup_code.py``); the plaintext exists in the message to the customer
and nowhere else. ``pickup_code_failed_attempts`` counts wrong codes so the code cannot be guessed: after the limit the
note stops accepting codes until staff reissue one. A note issued before this migration has no hash and keeps working
without a code.

Revision ID: 065
Revises: 064
Create Date: 2026-11-16 12:00:00
"""

from alembic import op

revision = "065"
down_revision = "064"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE release_note
            ADD COLUMN pickup_code_hash            VARCHAR(64),
            ADD COLUMN pickup_code_issued_at       TIMESTAMPTZ,
            ADD COLUMN pickup_code_failed_attempts INTEGER NOT NULL DEFAULT 0
                CHECK (pickup_code_failed_attempts >= 0)
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE release_note
            DROP COLUMN pickup_code_failed_attempts,
            DROP COLUMN pickup_code_issued_at,
            DROP COLUMN pickup_code_hash
        """
    )
