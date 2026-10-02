"""036 — manifest verification evidence (photos/docs).

Mirrors `claim_evidence` (migration 003) for the manifest-verify workflow: staff
attach a photo when logging a discrepancy (prototype §6.3). S3-backed — the row
holds the `file_key`; the object is uploaded directly to S3 via a presigned POST.

Like `claim_evidence` it has NO RLS — tenant isolation is enforced at write time
(the manifest is looked up tenant-scoped before the row is created) and by the
`{tenant_id}/manifests/...` S3 key prefix. Scoped to reads via the manifest_id FK.
`label` carries the optional discrepancy descriptor (customer / carton tag).
"""

from alembic import op

revision = "036"
down_revision = "035"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS manifest_evidence (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            manifest_id UUID NOT NULL REFERENCES manifest(id) ON DELETE CASCADE,
            file_key VARCHAR(500) NOT NULL,
            file_name VARCHAR(255) NOT NULL,
            file_type VARCHAR(50) NOT NULL,
            file_size_bytes INTEGER,
            label VARCHAR(255),
            uploaded_by UUID REFERENCES tenant_user(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_manifest_evidence_manifest " "ON manifest_evidence(manifest_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS manifest_evidence")
