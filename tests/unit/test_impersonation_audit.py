"""Regression tests for services.tenant_management.impersonation's audit
trail — where impersonation start/end events are logged, and that they're
valid writes.

Ground-truth gap found live, in the same pass as auditing log coverage
generally: `start_impersonation`/`end_impersonation` called
`shared.audit.log_audit(entity_type="impersonation_session",
action="IMPERSONATION_START"/"IMPERSONATION_END", ...)` — writing into the
*tenant's own* `audit_log`. Two problems:

1. `audit_log.action` used to be CHECK-constrained to
   CREATE/UPDATE/DELETE/STATUS_CHANGE (migration 004) — neither
   IMPERSONATION_START nor IMPERSONATION_END is one of those, so every call
   silently failed the insert (log_audit never raises) since this code was
   written. Fixed by migration 045 (drops the constraint, widens the
   column) — but that fix alone would have made a *tenant admin* able to
   see impersonation sessions in their own Activity Log for the first time,
   which is a real information-boundary problem in its own right.
2. Reported directly by the user: a platform admin impersonating a tenant
   is not a tenant-side business event, and a tenant admin should never see
   it in their own activity log. Moved to `platform_audit_log` instead
   (`repository.insert_platform_audit`, already used for every other
   platform-level action, and already has no such CHECK constraint) —
   visible to platform admins only, via `PlatformAuditLog.tsx`.
"""

from datetime import UTC, datetime
from unittest.mock import patch

TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


class TestStartImpersonationAudit:
    def test_logs_to_platform_audit_not_tenant_audit_log(self):
        from services.tenant_management import impersonation

        target_user = {"user_id": "admin-1", "full_name": "Chidi Okafor"}
        session_row = {"id": "sess-1"}

        with (
            patch.object(impersonation, "_get_tenant_status", return_value="active"),
            patch.object(impersonation, "_get_tenant_admin", return_value=target_user),
            patch.object(impersonation, "_create_session", return_value=session_row),
            patch.object(impersonation, "_get_signing_secret", return_value="test-secret"),
            patch.object(impersonation, "_mint_token", return_value="signed.jwt.token"),
            patch("services.tenant_management.repository.insert_platform_audit") as mock_platform_audit,
        ):
            result = impersonation.start_impersonation("platform-admin-1", TENANT_ID)

        assert result["token"] == "signed.jwt.token"
        mock_platform_audit.assert_called_once()
        assert mock_platform_audit.call_args.kwargs["action"] == "IMPERSONATION_START"
        assert mock_platform_audit.call_args.kwargs["target_tenant_id"] == TENANT_ID
        assert mock_platform_audit.call_args.kwargs["actor_id"] == "platform-admin-1"

    def test_does_not_import_shared_audit_log_audit(self):
        """Ground-truth regression guard: this module must not write
        impersonation events into the tenant-scoped audit_log at all."""
        from services.tenant_management import impersonation

        assert not hasattr(impersonation, "log_audit")


class TestEndImpersonationAudit:
    def test_logs_to_platform_audit_not_tenant_audit_log(self):
        from services.tenant_management import impersonation

        active_session = {
            "id": "sess-1",
            "platform_admin_id": "platform-admin-1",
            "target_tenant_id": TENANT_ID,
        }
        ended_row = {**active_session, "ended_at": datetime.now(UTC), "end_reason": "manual"}

        with (
            patch.object(impersonation, "get_active_session", return_value=active_session),
            patch.object(impersonation, "_end_session", return_value=ended_row),
            patch("services.tenant_management.repository.insert_platform_audit") as mock_platform_audit,
        ):
            result = impersonation.end_impersonation("sess-1", "platform-admin-1")

        assert result["session_id"] == "sess-1"
        mock_platform_audit.assert_called_once()
        assert mock_platform_audit.call_args.kwargs["action"] == "IMPERSONATION_END"
        assert mock_platform_audit.call_args.kwargs["target_tenant_id"] == TENANT_ID
