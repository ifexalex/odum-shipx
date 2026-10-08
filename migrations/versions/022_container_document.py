"""Create container_document table for Bill of Lading / customs certificate uploads.

Each row tracks an S3 object attached to a container. The S3 key is validated
against the tenant prefix before issuance (enforced in the application layer).

Revision ID: 022
Revises: 021
Create Date: 2026-05-05 00:00:00
"""

from alembic import op

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE container_document (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
            container_id    UUID NOT NULL REFERENCES container(id) ON DELETE CASCADE,
            document_type   VARCHAR(50) NOT NULL CHECK (document_type IN (
                                'bill_of_lading',
                                'customs_certificate',
                                'insurance',
                                'inspection_report',
                                'other'
                            )),
            s3_key          TEXT NOT NULL,
            filename        TEXT NOT NULL,
            content_type    VARCHAR(100),
            uploaded_by     VARCHAR(255),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX idx_container_document_container ON container_document(container_id)")
    op.execute("CREATE INDEX idx_container_document_tenant ON container_document(tenant_id)")

    # RLS — tenant-scoped
    op.execute("ALTER TABLE container_document ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY container_document_tenant_isolation ON container_document
        USING (tenant_id::text = current_setting('app.tenant_id', TRUE))
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS container_document CASCADE")
