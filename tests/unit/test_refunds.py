"""Unit tests for services.refunds.service — refund workflow and debt check."""
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from shared.exceptions import (
    IllegalTransitionError,
    InsufficientPermissionsError,
    ResourceNotFoundError,
)
from shared.tenant_context import TenantContext, UserRole

TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
NOW = datetime(2026, 2, 1, tzinfo=timezone.utc)


def _ctx(role: UserRole) -> TenantContext:
    return TenantContext(tenant_id=TENANT_ID, user_id="user-1", role=role)


def _refund(**kwargs) -> dict:
    base = {
        "id": "refund-001",
        "tenant_id": TENANT_ID,
        "customer_id": "customer-001",
        "billing_id": "billing-001",
        "damage_claim_id": None,
        "refund_type": "overpayment",
        "amount_ngn": Decimal("5000.00"),
        "amount_approved_ngn": None,
        "status": "pending_review",
        "customer_choice": "immediate_refund",
        "reason": "",
        "created_at": NOW,
    }
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# _fmt_refund formatter
# ---------------------------------------------------------------------------


class TestFmtRefund:
    def test_maps_amount_ngn_to_amount_requested_ngn(self):
        from services.refunds.service import _fmt_refund
        row = _refund()
        result = _fmt_refund(row)
        assert "amount_requested_ngn" in result
        assert result["amount_requested_ngn"] == Decimal("5000.00")

    def test_amount_approved_ngn_none_when_not_set(self):
        from services.refunds.service import _fmt_refund
        row = _refund(amount_approved_ngn=None)
        assert _fmt_refund(row)["amount_approved_ngn"] is None

    def test_amount_approved_ngn_set_when_present(self):
        from services.refunds.service import _fmt_refund
        row = _refund(amount_approved_ngn=Decimal("4500.00"))
        assert _fmt_refund(row)["amount_approved_ngn"] == Decimal("4500.00")


# ---------------------------------------------------------------------------
# get_refund — customer ownership check
# ---------------------------------------------------------------------------


class TestGetRefund:
    def test_staff_can_get_any_refund(self):
        from services.refunds import service
        refund = _refund()
        with patch.object(service.repo, "get_refund_request_by_id", return_value=refund):
            ctx = _ctx(UserRole.NIGERIA_OFFICE_STAFF)
            result = service.get_refund(TENANT_ID, "refund-001", ctx)
            assert result["id"] == "refund-001"

    def test_customer_can_get_own_refund(self):
        from services.refunds import service
        refund = _refund(customer_id="customer-001")
        customer = {"id": "customer-001"}
        with (
            patch.object(service.repo, "get_refund_request_by_id", return_value=refund),
            patch.object(service.repo, "get_customer_by_user_id", return_value=customer),
        ):
            ctx = _ctx(UserRole.CUSTOMER)
            result = service.get_refund(TENANT_ID, "refund-001", ctx)
            assert result["id"] == "refund-001"

    def test_customer_cannot_get_other_refund(self):
        from services.refunds import service
        refund = _refund(customer_id="customer-999")
        customer = {"id": "customer-001"}
        with (
            patch.object(service.repo, "get_refund_request_by_id", return_value=refund),
            patch.object(service.repo, "get_customer_by_user_id", return_value=customer),
        ):
            ctx = _ctx(UserRole.CUSTOMER)
            with pytest.raises(InsufficientPermissionsError):
                service.get_refund(TENANT_ID, "refund-001", ctx)

    def test_not_found_raises_resource_not_found(self):
        from services.refunds import service
        with patch.object(service.repo, "get_refund_request_by_id", return_value=None):
            with pytest.raises(ResourceNotFoundError):
                service.get_refund(TENANT_ID, "nonexistent", _ctx(UserRole.TENANT_ADMIN))


# ---------------------------------------------------------------------------
# accounts_review
# ---------------------------------------------------------------------------


class TestAccountsReview:
    def _req(self, passed: bool = True) -> MagicMock:
        req = MagicMock()
        req.debt_check_passed = passed
        req.debt_check_notes = "Verified"
        return req

    def test_advances_to_pending_approval_when_passed(self):
        from services.refunds import service
        refund = _refund(status="pending_review")
        updated = _refund(status="pending_approval")
        with (
            patch.object(service.repo, "get_refund_request_by_id", return_value=refund),
            patch.object(service.repo, "get_outstanding_carryovers_for_customer", return_value=[]),
            patch.object(service.repo, "get_unpaid_billing_totals_for_customer", return_value=Decimal("0")),
            patch.object(service.repo, "update_refund_status", return_value=updated),
        ):
            result = service.accounts_review(
                TENANT_ID, "refund-001", self._req(True),
                actor_id="user-1", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF)
            )
            assert result["status"] == "pending_approval"

    def test_rejects_when_debt_check_failed(self):
        from services.refunds import service
        refund = _refund(status="pending_review")
        updated = _refund(status="rejected")
        with (
            patch.object(service.repo, "get_refund_request_by_id", return_value=refund),
            patch.object(service.repo, "get_outstanding_carryovers_for_customer", return_value=[]),
            patch.object(service.repo, "get_unpaid_billing_totals_for_customer", return_value=Decimal("0")),
            patch.object(service.repo, "update_refund_status", return_value=updated),
        ):
            result = service.accounts_review(
                TENANT_ID, "refund-001", self._req(False),
                actor_id="user-1", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF)
            )
            assert result["status"] == "rejected"

    def test_raises_illegal_transition_if_not_pending_review(self):
        from services.refunds import service
        refund = _refund(status="pending_approval")
        with patch.object(service.repo, "get_refund_request_by_id", return_value=refund):
            with pytest.raises(IllegalTransitionError):
                service.accounts_review(
                    TENANT_ID, "refund-001", self._req(True),
                    actor_id="user-1", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF)
                )


# ---------------------------------------------------------------------------
# approve_refund — authority enforcement
# ---------------------------------------------------------------------------


class TestApproveRefund:
    def _approve_req(self, amount: str = "5000.00") -> MagicMock:
        req = MagicMock()
        req.amount_approved_ngn = Decimal(amount)
        return req

    def test_overpayment_manager_can_approve(self):
        from services.refunds import service
        refund = _refund(
            status="pending_approval",
            refund_type="overpayment",
            amount_ngn=Decimal("5000.00"),
            customer_choice="immediate_refund",
            billing_id=None,
        )
        updated = _refund(status="processed")
        with (
            patch.object(service.repo, "get_refund_request_by_id", return_value=refund),
            patch.object(service.repo, "update_refund_status", return_value=updated),
            patch("services.refunds.service.publish_event"),
        ):
            # nigeria_office_staff (manager) can approve overpayment
            ctx = _ctx(UserRole.NIGERIA_OFFICE_STAFF)
            result = service.approve_refund(
                TENANT_ID, "refund-001", self._approve_req(), actor_id="u", ctx=ctx
            )
            assert result["status"] == "processed"

    def test_cbm_correction_requires_tenant_admin(self):
        from services.refunds import service
        refund = _refund(
            status="pending_approval",
            refund_type="cbm_correction",
            amount_ngn=Decimal("5000.00"),
        )
        with patch.object(service.repo, "get_refund_request_by_id", return_value=refund):
            ctx = _ctx(UserRole.NIGERIA_OFFICE_STAFF)  # not admin
            with pytest.raises(InsufficientPermissionsError):
                service.approve_refund(
                    TENANT_ID, "refund-001", self._approve_req(), actor_id="u", ctx=ctx
                )

    def test_cbm_correction_tenant_admin_can_approve(self):
        from services.refunds import service
        refund = _refund(
            status="pending_approval",
            refund_type="cbm_correction",
            amount_ngn=Decimal("5000.00"),
            customer_choice="credit_next_shipment",
            billing_id=None,
        )
        updated = _refund(status="applied_as_credit")
        with (
            patch.object(service.repo, "get_refund_request_by_id", return_value=refund),
            patch.object(service.repo, "update_refund_status", return_value=updated),
            patch("services.refunds.service.publish_event"),
        ):
            ctx = _ctx(UserRole.TENANT_ADMIN)
            result = service.approve_refund(
                TENANT_ID, "refund-001", self._approve_req(), actor_id="u", ctx=ctx
            )
            assert result["status"] == "applied_as_credit"

    def test_damage_above_threshold_requires_tenant_admin(self):
        from services.refunds import service
        # > 30000 NGN damage_or_loss requires head_of_finance
        refund = _refund(
            status="pending_approval",
            refund_type="damage_or_loss",
            amount_ngn=Decimal("35000.00"),
        )
        with patch.object(service.repo, "get_refund_request_by_id", return_value=refund):
            with pytest.raises(InsufficientPermissionsError):
                service.approve_refund(
                    TENANT_ID, "refund-001", self._approve_req("35000"),
                    actor_id="u", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF)
                )

    def test_damage_below_threshold_manager_can_approve(self):
        from services.refunds import service
        refund = _refund(
            status="pending_approval",
            refund_type="damage_or_loss",
            amount_ngn=Decimal("20000.00"),
            customer_choice="immediate_refund",
            billing_id=None,
        )
        updated = _refund(status="processed")
        with (
            patch.object(service.repo, "get_refund_request_by_id", return_value=refund),
            patch.object(service.repo, "update_refund_status", return_value=updated),
            patch("services.refunds.service.publish_event"),
        ):
            ctx = _ctx(UserRole.NIGERIA_OFFICE_STAFF)
            result = service.approve_refund(
                TENANT_ID, "refund-001", self._approve_req("20000"),
                actor_id="u", ctx=ctx
            )
            assert result["status"] == "processed"

    def test_credit_next_shipment_sets_applied_as_credit(self):
        from services.refunds import service
        refund = _refund(
            status="pending_approval",
            refund_type="overpayment",
            amount_ngn=Decimal("5000.00"),
            customer_choice="credit_next_shipment",
            billing_id=None,
        )
        updated = _refund(status="applied_as_credit")
        with (
            patch.object(service.repo, "get_refund_request_by_id", return_value=refund),
            patch.object(service.repo, "update_refund_status", return_value=updated),
            patch("services.refunds.service.publish_event"),
        ):
            result = service.approve_refund(
                TENANT_ID, "refund-001", self._approve_req(),
                actor_id="u", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF)
            )
            assert result["status"] == "applied_as_credit"

    def test_raises_illegal_transition_if_not_pending_approval(self):
        from services.refunds import service
        refund = _refund(status="pending_review")
        with patch.object(service.repo, "get_refund_request_by_id", return_value=refund):
            with pytest.raises(IllegalTransitionError):
                service.approve_refund(
                    TENANT_ID, "refund-001", self._approve_req(),
                    actor_id="u", ctx=_ctx(UserRole.TENANT_ADMIN)
                )


# ---------------------------------------------------------------------------
# reject_refund
# ---------------------------------------------------------------------------


class TestRejectRefund:
    def test_rejects_from_pending_review(self):
        from services.refunds import service
        refund = _refund(status="pending_review")
        updated = _refund(status="rejected")
        with (
            patch.object(service.repo, "get_refund_request_by_id", return_value=refund),
            patch.object(service.repo, "update_refund_status", return_value=updated),
        ):
            result = service.reject_refund(
                TENANT_ID, "refund-001", "Not eligible",
                actor_id="u", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF)
            )
            assert result["status"] == "rejected"

    def test_rejects_from_pending_approval(self):
        from services.refunds import service
        refund = _refund(status="pending_approval")
        updated = _refund(status="rejected")
        with (
            patch.object(service.repo, "get_refund_request_by_id", return_value=refund),
            patch.object(service.repo, "update_refund_status", return_value=updated),
        ):
            result = service.reject_refund(
                TENANT_ID, "refund-001", "Rejected",
                actor_id="u", ctx=_ctx(UserRole.TENANT_ADMIN)
            )
            assert result["status"] == "rejected"

    def test_cannot_reject_approved_refund(self):
        from services.refunds import service
        refund = _refund(status="processed")
        with patch.object(service.repo, "get_refund_request_by_id", return_value=refund):
            with pytest.raises(IllegalTransitionError):
                service.reject_refund(
                    TENANT_ID, "refund-001", "reason",
                    actor_id="u", ctx=_ctx(UserRole.TENANT_ADMIN)
                )
