"""045 — drop audit_log.action's CHECK constraint; widen to VARCHAR(100).

Ground-truth gap found live, discovered while auditing log coverage for a
second time in the same session: `audit_log.action` (migration 004) is
`VARCHAR(30) CHECK (action IN ('CREATE', 'UPDATE', 'DELETE',
'STATUS_CHANGE'))`. A grep across every `log_audit()` call site found 20
of them passing a more descriptive action verb the check doesn't allow —
`EXPORT`, `CANCEL`, `RETRY`, `EXEMPT`, `DEACTIVATE`, `SELF_REGISTER`,
`INVITE_ACCEPTED`, `DISCREPANCY_RESOLVED`, `WAIVE_STORAGE_FEES`,
`APPLY_CARRYOVER`, `BULK_APPROVE`, `BULK_SUBMIT`, `BULK_REJECT`,
`IMPERSONATION_START`, `IMPERSONATION_END`, and more. `log_audit()` never
raises on failure (by design — audit logging must never break a primary
operation), so every one of these calls has been silently failing the
INSERT with a check-constraint violation, logged only as a WARNING, since
the code was written. Reproduced live: `IMPERSONATION_START` raises
`new row for relation "audit_log" violates check constraint
"audit_log_action_check"` — the exact same failure mode already found and
fixed once this session for a bad `actor_id` (see 02_shared_utilities.md).

Fix: drop the CHECK constraint and widen the column to VARCHAR(100),
matching `platform_audit_log.action`'s existing, already-looser design
(VARCHAR(100), no CHECK at all) — the two tables are siblings in the same
audit system, and platform_audit_log has taken free-text action verbs
without incident since it was created. This is a permanent fix, not a
one-time backfill of the current 20 call sites: any future action verb a
developer chooses is valid immediately, with no migration required and no
way for this exact silent-failure shape to recur.

Revision ID: 045
Revises: 044
Create Date: 2026-09-07 00:00:00
"""

from alembic import op

revision = "045"
down_revision = "044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE audit_log DROP CONSTRAINT audit_log_action_check")
    op.execute("ALTER TABLE audit_log ALTER COLUMN action TYPE VARCHAR(100)")


def downgrade() -> None:
    op.execute("ALTER TABLE audit_log ALTER COLUMN action TYPE VARCHAR(30)")
    op.execute(
        """
        ALTER TABLE audit_log ADD CONSTRAINT audit_log_action_check
        CHECK (action IN ('CREATE', 'UPDATE', 'DELETE', 'STATUS_CHANGE'))
        """
    )
