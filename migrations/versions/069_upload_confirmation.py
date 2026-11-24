"""069 — an uploaded file is listed only once its upload is confirmed.

The browser uploads evidence and container documents straight to storage with a presigned URL, and the row was
written when the URL was issued. Two problems followed:

* A row was listed whether or not the file ever arrived: an abandoned upload showed as a file whose link did not open.
* On Azure nothing checked the stored file's size: a SAS cannot bind the length, so a file over the 5 MB limit was
  kept and listed (AWS refuses it at the PUT, because the declared length is signed).

The client now confirms each upload after the PUT; the confirm call reads the stored size, deletes a file over the
limit, and stamps ``confirmed_at``. Lists and downloads show confirmed rows only.

* ``confirmed_at`` on ``claim_evidence``, ``manifest_evidence`` and ``container_document``. Existing rows are
  backfilled to ``created_at`` so nothing already listed disappears; their files were never checked.
* ``container_document.file_size_bytes``, which the other two tables already have, filled in at confirmation.

Revision ID: 069
Revises: 068
Create Date: 2026-11-19 10:00:00
"""

from alembic import op

revision = "069"
down_revision = "068"
branch_labels = None
depends_on = None

_COMMENT = (
    "'When the client confirmed the upload and its stored size was checked. NULL: not uploaded yet, not listed. "
    "Rows before migration 069 are backfilled to created_at.'"
)


def upgrade() -> None:
    op.execute("ALTER TABLE claim_evidence ADD COLUMN IF NOT EXISTS confirmed_at TIMESTAMPTZ")
    op.execute("ALTER TABLE manifest_evidence ADD COLUMN IF NOT EXISTS confirmed_at TIMESTAMPTZ")
    op.execute(
        """
        ALTER TABLE container_document
            ADD COLUMN IF NOT EXISTS confirmed_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS file_size_bytes INTEGER
        """
    )
    op.execute("UPDATE claim_evidence SET confirmed_at = created_at WHERE confirmed_at IS NULL")
    op.execute("UPDATE manifest_evidence SET confirmed_at = created_at WHERE confirmed_at IS NULL")
    op.execute("UPDATE container_document SET confirmed_at = created_at WHERE confirmed_at IS NULL")
    op.execute("COMMENT ON COLUMN claim_evidence.confirmed_at IS " + _COMMENT)
    op.execute("COMMENT ON COLUMN manifest_evidence.confirmed_at IS " + _COMMENT)
    op.execute("COMMENT ON COLUMN container_document.confirmed_at IS " + _COMMENT)


def downgrade() -> None:
    op.execute("ALTER TABLE container_document DROP COLUMN IF EXISTS file_size_bytes, DROP COLUMN IF EXISTS confirmed_at")
    op.execute("ALTER TABLE manifest_evidence DROP COLUMN IF EXISTS confirmed_at")
    op.execute("ALTER TABLE claim_evidence DROP COLUMN IF EXISTS confirmed_at")
