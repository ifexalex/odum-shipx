"""Phase 2 permissioning regression tests (H-6, H-7, H-8, H-10, M-1, M-4, M-5, M-10, L-1)."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from services.billing import handler as billing_handler
from services.billing import service as billing_service
from services.claims import handler as claims_handler
from services.claims import service as claims_service
from services.excel import handler as excel_handler
from services.packing_list import handler as pl_handler
from services.payment_release import service as pr_service
from services.refunds import handler as refunds_handler
from services.refunds import service as refunds_service
from services.tenant_management import handler as tm_handler
from services.tenant_management import users as tm_users
from services.tracking import handler as tracking_handler
from shared import pickup_code, platform_audit
from shared.exceptions import (
    BusinessRuleViolationError,
    InsufficientPermissionsError,
    ResourceNotFoundError,
    SelfApprovalForbiddenError,
    UsageLimitExceededError,
)
from shared.tenant_context import TenantContext, UserRole


class TestFinancialFourEyesAndSoD:
    def test_billing_dispute_blocks_self_resolution_and_restricts_china_staff(self) -> None:
        staff_ctx = TenantContext(tenant_id="t1", user_id="u-staff", role=UserRole.NIGERIA_OFFICE_STAFF)
        china_ctx = TenantContext(tenant_id="t1", user_id="u-china", role=UserRole.CHINA_OFFICE_STAFF)
        req = SimpleNamespace(status="resolved_no_change", corrected_cbm=None, resolution_notes="ok")

        with patch.object(
            billing_service.repo,
            "get_cbm_dispute_by_id",
            return_value={"id": "d1", "status": "investigating", "raised_by": "u-staff", "billing_id": "b1"},
        ):
            with pytest.raises(SelfApprovalForbiddenError):
                billing_service.resolve_dispute("t1", "d1", req, actor_id="u-staff", ctx=staff_ctx)

            with pytest.raises(InsufficientPermissionsError):
                billing_service.resolve_dispute("t1", "d1", req, actor_id="u-china", ctx=china_ctx)

    def test_claims_blocks_self_resolution_for_non_admin(self) -> None:
        staff_ctx = TenantContext(tenant_id="t1", user_id="u-staff", role=UserRole.NIGERIA_OFFICE_STAFF)
        req = SimpleNamespace(resolution_type="rejected", notes="nope")
        with patch.object(
            claims_service.repo,
            "get_damage_claim_by_id",
            return_value={"id": "c1", "status": "under_inspection", "submitted_by": "u-staff"},
        ):
            with pytest.raises(SelfApprovalForbiddenError):
                claims_service.resolve_claim("t1", "c1", req, actor_id="u-staff", ctx=staff_ctx)

    def test_customer_refund_requires_billing_id_and_overpayment_type(self) -> None:
        cust_ctx = TenantContext(tenant_id="t1", user_id="u-cust", role=UserRole.CUSTOMER)
        req_wrong_type = SimpleNamespace(
            customer_id="",
            billing_id="b1",
            damage_claim_id=None,
            refund_type="damage_or_loss",
            amount_requested_ngn=Decimal("1000"),
        )
        with patch.object(refunds_service.repo, "get_customer_by_user_id", return_value={"id": "cust-1"}):
            with pytest.raises(BusinessRuleViolationError) as exc:
                refunds_service.create_refund("t1", req_wrong_type, actor_id="u-cust", ctx=cust_ctx)
            assert exc.value.rule_id == "CUSTOMER_REFUND_TYPE_FORBIDDEN"

            req_no_billing = SimpleNamespace(
                customer_id="",
                billing_id=None,
                damage_claim_id=None,
                refund_type="overpayment",
                amount_requested_ngn=Decimal("1000"),
            )
            with pytest.raises(BusinessRuleViolationError) as exc2:
                refunds_service.create_refund("t1", req_no_billing, actor_id="u-cust", ctx=cust_ctx)
            assert exc2.value.rule_id == "BILLING_ID_REQUIRED"

    def test_release_with_outstanding_restricted_to_tenant_admin(self) -> None:
        staff_ctx = TenantContext(tenant_id="t1", user_id="u-staff", role=UserRole.NIGERIA_OFFICE_STAFF)
        req = SimpleNamespace(
            billing_id="b1",
            carton_tags=["TAG-1"],
            packages_released=None,
            release_with_outstanding=True,
            approval_notes="approved",
            warehouse_id=None,
            credit_granted_by_name="Staff",
        )
        with patch.object(pr_service.repo, "get_billing_by_id", return_value={"id": "b1", "customer_id": "c1"}):
            with pytest.raises(InsufficientPermissionsError):
                pr_service.generate_release_note("t1", req, actor_id="u-staff", ctx=staff_ctx)

    def test_confirm_online_payment_returns_404_on_ownership_mismatch(self) -> None:
        cust_ctx = TenantContext(tenant_id="t1", user_id="u-cust", role=UserRole.CUSTOMER)
        with (
            patch.object(pr_service.repo, "get_billing_by_id", return_value={"id": "b1", "customer_id": "c-other"}),
            patch.object(pr_service.repo, "get_customer_by_user_id", return_value={"id": "c-own"}),
        ):
            with pytest.raises(ResourceNotFoundError):
                pr_service.confirm_online_payment("t1", "b1", "b1.ref", cust_ctx)

    def test_pickup_code_fails_closed_in_production_without_pepper(self, monkeypatch) -> None:
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.delenv("PICKUP_CODE_PEPPER", raising=False)
        with pytest.raises(RuntimeError, match="PICKUP_CODE_PEPPER"):
            pickup_code.is_configured()


class TestRbacParityDeadlocksAndQuotas:
    def test_platform_admin_removed_from_tenant_scoped_role_tuples(self) -> None:
        assert UserRole.PLATFORM_ADMIN not in tm_handler._STAFF_ROLES
        assert UserRole.PLATFORM_ADMIN not in pl_handler._READ_ROLES
        assert UserRole.PLATFORM_ADMIN not in tracking_handler._ALL_AUTH_ROLES
        assert UserRole.PLATFORM_ADMIN not in excel_handler._EXPORT_ROLES
        assert UserRole.PLATFORM_ADMIN not in excel_handler._BILLING_EXPORT_ROLES

    def test_tenant_admin_included_in_acknowledge_inspect_and_review_roles(self) -> None:
        assert UserRole.TENANT_ADMIN in billing_handler._ACKNOWLEDGE_ROLES
        assert UserRole.TENANT_ADMIN in claims_handler._INSPECT_ROLES
        assert UserRole.TENANT_ADMIN in claims_handler._STAFF_ROLES
        assert UserRole.TENANT_ADMIN in refunds_handler._REVIEW_ROLES
        assert billing_handler._CANCEL_BILLING_ROLES == (UserRole.TENANT_ADMIN,)

    def test_promoting_customer_to_staff_enforces_user_seat_quota(self) -> None:
        existing = {"id": "u1", "email": "c@acme.test", "status": "active", "role": "customer", "roles": ["customer"]}
        with (
            patch.object(tm_users, "get_user", return_value=existing),
            patch.object(tm_users, "get_tenant", return_value={"id": "t1", "subscription_tier": "starter"}),
            patch.object(tm_users, "get_effective_limits", return_value={"max_users": 5}),
            patch.object(tm_users.repo, "count_active_users", return_value=5),
        ):
            with pytest.raises(UsageLimitExceededError):
                tm_users.update_user(
                    "t1",
                    "u1",
                    {"roles": ["nigeria_office_staff"], "primary_role": "nigeria_office_staff"},
                    actor_id="admin-1",
                )

    def test_platform_audit_masks_sensitive_keys(self) -> None:
        captured: dict = {}

        def _fake_write(scope, sql, params):
            captured.update(params)

        with patch.object(platform_audit, "execute_write_with_tenant", side_effect=_fake_write):
            platform_audit.insert_platform_audit(
                "TEST_ACTION",
                "admin-1",
                "t1",
                details={"password": "plain-secret", "token": "tok-123", "safe": "ok"},
            )
        assert '"safe": "ok"' in captured["details"]
        assert "plain-secret" not in captured["details"]
        assert "tok-123" not in captured["details"]
