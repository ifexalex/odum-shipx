"""037 — Drop platform_audit_log.actor_id FK to tenant_user.

Platform admins deliberately have no tenant_user row (tenant_user.tenant_id
is a NOT NULL FK to tenant(id) and its role CHECK has no 'platform_admin'
value — they exist only as Cognito identities with custom:tenant_id =
"PLATFORM"). The actor_id → tenant_user(id) FK therefore rejected every
platform-audit insert; insert_platform_audit() swallows the error with a
warning, so the platform audit log was silently always empty.

Same class of fix as migration 014 (tenant_config.updated_by FK dropped
because Cognito subs aren't tenant_user rows). actor_id stays UUID — it
records the platform admin's Cognito sub.

Revision ID: 037
Revises: 036
"""

from alembic import op

revision = "037"
down_revision = "036"


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE platform_audit_log
            DROP CONSTRAINT IF EXISTS platform_audit_log_actor_id_fkey;
        """
    )


def downgrade() -> None:
    # Re-adding the FK would fail if any platform-admin audit rows exist
    # (their actor_id has no tenant_user row) — delete those first.
    op.execute(
        """
        DELETE FROM platform_audit_log
        WHERE actor_id IS NOT NULL
          AND actor_id NOT IN (SELECT id FROM tenant_user);
        ALTER TABLE platform_audit_log
            ADD CONSTRAINT platform_audit_log_actor_id_fkey
            FOREIGN KEY (actor_id) REFERENCES tenant_user(id);
        """
    )
