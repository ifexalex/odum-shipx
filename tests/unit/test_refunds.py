"""Unit tests for services.refunds.service — refund workflow and debt check."""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from shared.exceptions import (
    ApprovalThresholdExceededError,
    IllegalTransitionError,
    InsufficientPermissionsError,
    ResourceNotFoundError,
)
from shared.tenant_context import TenantContext, UserRole

TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
NOW = datetime(2026, 2, 1, tzinfo=UTC)


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


class TestCreateRefundCustomerFlow:
    """Ground-truth regression: RefundRequest.tsx's self-service "Request a
    Refund" flow always 403'd — _CREATE_ROLES (handler.py) never included
    CUSTOMER. Behind that, create_refund() used req.customer_id
    unconditionally, but the frontend deliberately sends customer_id=""
    with the comment "Server derives from JWT for customer role" — a
    derivation that never existed. Both fixed together.
    """

    def _req(self, **overrides) -> MagicMock:
        req = MagicMock()
        req.customer_id = ""  # exactly what RefundRequest.tsx actually sends
        req.billing_id = "billing-001"
        req.damage_claim_id = None
        req.refund_type = "overpayment"
        req.amount_requested_ngn = Decimal("15000")
        req.customer_choice = "immediate_refund"
        req.notes = "e2e test"
        for k, v in overrides.items():
            setattr(req, k, v)
        return req

    def test_customer_id_is_derived_from_the_session_not_the_blank_request_field(self):
        from services.refunds import service

        req = self._req()
        with (
            patch.object(service.repo, "get_customer_by_user_id", return_value={"id": "real-customer-001"}),
            patch.object(
                service.repo, "get_billing_by_id", return_value={"id": "billing-001", "customer_id": "real-customer-001"}
            ),
            patch.object(
                service.repo, "create_refund_request", return_value=_refund(customer_id="real-customer-001")
            ) as mock_create,
            patch("services.refunds.service.log_audit"),
        ):
            ctx = _ctx(UserRole.CUSTOMER)
            service.create_refund(TENANT_ID, req, actor_id="user-1", ctx=ctx)

        assert mock_create.call_args.args[1]["customer_id"] == "real-customer-001"

    def test_customer_cannot_request_a_refund_against_another_customers_billing(self):
        """Without this, a customer could request a refund against any
        billing record in the tenant by guessing or enumerating ids."""
        from services.refunds import service

        req = self._req()
        with (
            patch.object(service.repo, "get_customer_by_user_id", return_value={"id": "real-customer-001"}),
            patch.object(
                service.repo, "get_billing_by_id", return_value={"id": "billing-001", "customer_id": "someone-elses-customer-id"}
            ),
            patch.object(service.repo, "create_refund_request") as mock_create,
        ):
            ctx = _ctx(UserRole.CUSTOMER)
            with pytest.raises(ResourceNotFoundError):
                service.create_refund(TENANT_ID, req, actor_id="user-1", ctx=ctx)

        mock_create.assert_not_called()

    def test_staff_still_supplies_customer_id_directly(self):
        """Non-customer callers (nigeria_office_staff creating a refund on a
        customer's behalf) are unaffected — customer_id comes from the body."""
        from services.refunds import service

        req = self._req(customer_id="staff-provided-customer-001")
        with (
            patch.object(
                service.repo,
                "get_billing_by_id",
                return_value={"id": "billing-001", "customer_id": "staff-provided-customer-001"},
            ),
            patch.object(service.repo, "create_refund_request", return_value=_refund()) as mock_create,
            patch("services.refunds.service.log_audit"),
        ):
            ctx = _ctx(UserRole.NIGERIA_OFFICE_STAFF)
            service.create_refund(TENANT_ID, req, actor_id="user-1", ctx=ctx)

        assert mock_create.call_args.args[1]["customer_id"] == "staff-provided-customer-001"


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

    def _customer_reads(self, refund: dict) -> dict:
        from services.refunds import service

        with (
            patch.object(service.repo, "get_refund_request_by_id", return_value=refund),
            patch.object(service.repo, "get_customer_by_user_id", return_value={"id": "customer-001"}),
        ):
            return service.get_refund(TENANT_ID, "refund-001", _ctx(UserRole.CUSTOMER))

    def test_a_customer_is_not_shown_why_staff_decided_a_claim_in_their_favour(self):
        # A refund raised from a claim decision copies what staff typed. The decision was for the customer, so the
        # reason stays internal: it must not come back through the refund either (owner decision, 2026-11-17).
        refund = _refund(refund_type="damage_or_loss", requested_by=None, reason="Damage claim resolution — repeat claimant")
        assert self._customer_reads(refund)["reason"] is None

    def test_a_customer_reads_back_the_reason_they_wrote_themselves(self):
        refund = _refund(requested_by="user-1", reason="I paid twice")
        assert self._customer_reads(refund)["reason"] == "I paid twice"

    def test_a_customer_is_told_why_a_refund_was_rejected(self):
        refund = _refund(status="rejected", requested_by=None, reason="internal", rejection_reason="An invoice is unpaid")
        result = self._customer_reads(refund)
        assert result["rejection_reason"] == "An invoice is unpaid" and result["reason"] is None

    def test_a_customer_is_not_shown_staffs_working_record(self):
        refund = _refund(
            requested_by="user-1", approval_level="admin", debt_check_passed=False, debt_check_notes="owes 2 invoices"
        )
        result = self._customer_reads(refund)
        assert result["approval_level"] is None and result["debt_check_passed"] is None
        assert result["debt_check_notes"] is None and result["threshold"] is None

    def test_staff_still_read_the_reason_and_the_working_record(self):
        from services.refunds import service

        refund = _refund(requested_by=None, reason="Damage claim resolution — repeat claimant", approval_level="admin")
        with (
            patch.object(service.repo, "get_refund_request_by_id", return_value=refund),
            patch.object(service.repo, "get_refund_threshold_config", return_value={"staff_limit": 50}),
            patch.object(service, "get_effective_dollar_rate", return_value={"rate": Decimal("1600.00")}),
        ):
            result = service.get_refund(TENANT_ID, "refund-001", _ctx(UserRole.NIGERIA_OFFICE_STAFF))
        assert result["reason"] == "Damage claim resolution — repeat claimant" and result["approval_level"] == "admin"

    def test_customer_cannot_get_other_refund(self):
        from services.refunds import service

        refund = _refund(customer_id="customer-999")
        customer = {"id": "customer-001"}
        with (
            patch.object(service.repo, "get_refund_request_by_id", return_value=refund),
            patch.object(service.repo, "get_customer_by_user_id", return_value=customer),
        ):
            ctx = _ctx(UserRole.CUSTOMER)
            with pytest.raises(ResourceNotFoundError):
                service.get_refund(TENANT_ID, "refund-001", ctx)

    def test_not_found_raises_resource_not_found(self):
        from services.refunds import service

        with patch.object(service.repo, "get_refund_request_by_id", return_value=None):
            with pytest.raises(ResourceNotFoundError):
                service.get_refund(TENANT_ID, "nonexistent", _ctx(UserRole.TENANT_ADMIN))

    def test_threshold_uses_the_effective_bybit_plus_markup_dollar_rate(self):
        # Ground-truth change: the dollar rate used to convert staff_limit
        # (USD) into a NGN threshold is no longer a tenant_config value —
        # it's shared.fx_rate.get_effective_dollar_rate (Bybit base + this
        # tenant's markup).
        from services.refunds import service

        refund = _refund(amount_ngn=Decimal("100000.00"))
        with (
            patch.object(service.repo, "get_refund_request_by_id", return_value=refund),
            patch.object(service.repo, "get_refund_threshold_config", return_value={"staff_limit": 50}),
            patch.object(service, "get_effective_dollar_rate", return_value={"rate": Decimal("1600.00")}),
        ):
            result = service.get_refund(TENANT_ID, "refund-001", _ctx(UserRole.NIGERIA_OFFICE_STAFF))

        assert result["threshold"]["dollar_rate"] == 1600.00
        assert result["threshold"]["staff_limit_ngn"] == 80000.00
        assert result["threshold"]["exceeds_staff_limit"] is True  # 100,000 > 80,000

    def test_threshold_is_none_when_the_rate_lookup_fails(self):
        from services.refunds import service

        refund = _refund()
        with (
            patch.object(service.repo, "get_refund_request_by_id", return_value=refund),
            patch.object(service.repo, "get_refund_threshold_config", side_effect=RuntimeError("db down")),
        ):
            result = service.get_refund(TENANT_ID, "refund-001", _ctx(UserRole.NIGERIA_OFFICE_STAFF))

        assert result["threshold"] is None


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
                TENANT_ID, "refund-001", self._req(True), actor_id="user-1", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF)
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
                TENANT_ID, "refund-001", self._req(False), actor_id="user-1", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF)
            )
            assert result["status"] == "rejected"

    def test_raises_illegal_transition_if_not_pending_review(self):
        from services.refunds import service

        refund = _refund(status="pending_approval")
        with patch.object(service.repo, "get_refund_request_by_id", return_value=refund):
            with pytest.raises(IllegalTransitionError):
                service.accounts_review(
                    TENANT_ID, "refund-001", self._req(True), actor_id="user-1", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF)
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
            patch.object(service.repo, "approve_refund_and_adjust_billing", return_value=updated),
            patch("services.refunds.service.publish_event"),
        ):
            # nigeria_office_staff (manager) can approve overpayment
            ctx = _ctx(UserRole.NIGERIA_OFFICE_STAFF)
            result = service.approve_refund(TENANT_ID, "refund-001", self._approve_req(), actor_id="u", ctx=ctx)
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
                service.approve_refund(TENANT_ID, "refund-001", self._approve_req(), actor_id="u", ctx=ctx)

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
            patch.object(service.repo, "approve_refund_and_adjust_billing", return_value=updated),
            patch("services.refunds.service.publish_event"),
        ):
            ctx = _ctx(UserRole.TENANT_ADMIN)
            result = service.approve_refund(TENANT_ID, "refund-001", self._approve_req(), actor_id="u", ctx=ctx)
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
                    TENANT_ID, "refund-001", self._approve_req("35000"), actor_id="u", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF)
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
            patch.object(service.repo, "approve_refund_and_adjust_billing", return_value=updated),
            patch("services.refunds.service.publish_event"),
        ):
            ctx = _ctx(UserRole.NIGERIA_OFFICE_STAFF)
            result = service.approve_refund(TENANT_ID, "refund-001", self._approve_req("20000"), actor_id="u", ctx=ctx)
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
            patch.object(service.repo, "approve_refund_and_adjust_billing", return_value=updated),
            patch("services.refunds.service.publish_event"),
        ):
            result = service.approve_refund(
                TENANT_ID, "refund-001", self._approve_req(), actor_id="u", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF)
            )
            assert result["status"] == "applied_as_credit"

    def test_nigeria_staff_blocked_above_threshold_using_effective_dollar_rate(self):
        # staff_limit=50 USD * effective rate 1600 = 80,000 NGN ceiling.
        from services.refunds import service

        refund = _refund(status="pending_approval", refund_type="overpayment", amount_ngn=Decimal("100000.00"))
        with (
            patch.object(service.repo, "get_refund_request_by_id", return_value=refund),
            patch.object(service.repo, "get_refund_threshold_config", return_value={"staff_limit": 50}),
            patch.object(service, "get_effective_dollar_rate", return_value={"rate": Decimal("1600.00")}),
        ):
            with pytest.raises(ApprovalThresholdExceededError):
                service.approve_refund(
                    TENANT_ID, "refund-001", self._approve_req("90000.00"), actor_id="u", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF)
                )

    def test_nigeria_staff_allowed_at_or_below_threshold(self):
        from services.refunds import service

        refund = _refund(
            status="pending_approval",
            refund_type="overpayment",
            amount_ngn=Decimal("70000.00"),
            customer_choice="immediate_refund",
            billing_id=None,
        )
        updated = _refund(status="processed")
        with (
            patch.object(service.repo, "get_refund_request_by_id", return_value=refund),
            patch.object(service.repo, "get_refund_threshold_config", return_value={"staff_limit": 50}),
            patch.object(service, "get_effective_dollar_rate", return_value={"rate": Decimal("1600.00")}),
            patch.object(service.repo, "approve_refund_and_adjust_billing", return_value=updated),
            patch("services.refunds.service.publish_event"),
        ):
            result = service.approve_refund(
                TENANT_ID, "refund-001", self._approve_req("70000.00"), actor_id="u", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF)
            )
        assert result["status"] == "processed"

    def test_tenant_admin_can_override_above_staff_threshold(self):
        from services.refunds import service

        refund = _refund(
            status="pending_approval",
            refund_type="overpayment",
            amount_ngn=Decimal("100000.00"),
            customer_choice="immediate_refund",
            billing_id=None,
        )
        updated = _refund(status="processed")
        with (
            patch.object(service.repo, "get_refund_request_by_id", return_value=refund),
            patch.object(service.repo, "approve_refund_and_adjust_billing", return_value=updated),
            patch("services.refunds.service.publish_event"),
        ):
            # tenant_admin never hits the staff-limit branch at all.
            result = service.approve_refund(
                TENANT_ID, "refund-001", self._approve_req("100000.00"), actor_id="u", ctx=_ctx(UserRole.TENANT_ADMIN)
            )
        assert result["status"] == "processed"

    def test_raises_illegal_transition_if_not_pending_approval(self):
        from services.refunds import service

        refund = _refund(status="pending_review")
        with patch.object(service.repo, "get_refund_request_by_id", return_value=refund):
            with pytest.raises(IllegalTransitionError):
                service.approve_refund(
                    TENANT_ID, "refund-001", self._approve_req(), actor_id="u", ctx=_ctx(UserRole.TENANT_ADMIN)
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
                TENANT_ID, "refund-001", "Not eligible", actor_id="u", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF)
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
            result = service.reject_refund(TENANT_ID, "refund-001", "Rejected", actor_id="u", ctx=_ctx(UserRole.TENANT_ADMIN))
            assert result["status"] == "rejected"

    def test_cannot_reject_approved_refund(self):
        from services.refunds import service

        refund = _refund(status="processed")
        with patch.object(service.repo, "get_refund_request_by_id", return_value=refund):
            with pytest.raises(IllegalTransitionError):
                service.reject_refund(TENANT_ID, "refund-001", "reason", actor_id="u", ctx=_ctx(UserRole.TENANT_ADMIN))


class TestRefundApprovalIsAtomic:
    """Overpayment settlement and approval commit together, and compensation never shrinks total_ngn."""

    def _refund(self, *, refund_type: str = "overpayment", customer_choice: str = "immediate_refund"):
        return _refund(
            status="pending_approval",
            refund_type=refund_type,
            amount_ngn=Decimal("20000.00"),
            customer_choice=customer_choice,
            billing_id="billing-001",
        )

    def _req(self):
        req = MagicMock()
        req.amount_approved_ngn = Decimal("20000")
        return req

    def test_an_overpayment_refund_hands_settlement_to_the_atomic_repo_call(self):
        from services.refunds import service

        with (
            patch.object(service.repo, "get_refund_request_by_id", return_value=self._refund(refund_type="overpayment")),
            patch.object(
                service.repo, "approve_refund_and_adjust_billing", return_value=_refund(status="processed")
            ) as mock_approve,
            patch("services.refunds.service.publish_event"),
        ):
            service.approve_refund(TENANT_ID, "refund-001", self._req(), actor_id="u", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF))

        kwargs = mock_approve.call_args.kwargs
        assert kwargs["billing_id"] == "billing-001"
        assert kwargs["reduction_ngn"] == Decimal("20000")
        assert mock_approve.call_args.args[2] == "processed"

    def test_a_damage_compensation_refund_does_not_reduce_any_invoice(self):
        from services.refunds import service

        with (
            patch.object(service.repo, "get_refund_request_by_id", return_value=self._refund(refund_type="damage_or_loss")),
            patch.object(
                service.repo, "approve_refund_and_adjust_billing", return_value=_refund(status="processed")
            ) as mock_approve,
            patch("services.refunds.service.publish_event"),
        ):
            service.approve_refund(TENANT_ID, "refund-001", self._req(), actor_id="u", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF))

        assert mock_approve.call_args.kwargs["billing_id"] is None
        assert mock_approve.call_args.kwargs["reduction_ngn"] is None

    def test_overpayment_applied_as_credit_also_settles_the_overpaid_invoice(self):
        from services.refunds import service

        refund = self._refund(refund_type="overpayment", customer_choice="credit_next_shipment")
        with (
            patch.object(service.repo, "get_refund_request_by_id", return_value=refund),
            patch.object(
                service.repo, "approve_refund_and_adjust_billing", return_value=_refund(status="applied_as_credit")
            ) as mock_approve,
            patch("services.refunds.service.publish_event"),
        ):
            service.approve_refund(TENANT_ID, "refund-001", self._req(), actor_id="u", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF))

        assert mock_approve.call_args.kwargs["billing_id"] == "billing-001"
        assert mock_approve.call_args.kwargs["reduction_ngn"] == Decimal("20000")
        assert mock_approve.call_args.args[2] == "applied_as_credit"

    def test_an_approval_that_lost_the_race_is_refused_and_publishes_nothing(self):
        from services.refunds import service

        with (
            patch.object(service.repo, "get_refund_request_by_id", return_value=self._refund()),
            patch.object(service.repo, "approve_refund_and_adjust_billing", return_value={}),
            patch("services.refunds.service.publish_event") as mock_publish,
            patch("services.refunds.service.log_audit") as mock_audit,
        ):
            with pytest.raises(IllegalTransitionError):
                service.approve_refund(
                    TENANT_ID, "refund-001", self._req(), actor_id="u", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF)
                )

        mock_publish.assert_not_called()
        mock_audit.assert_not_called()

    def test_a_review_that_lost_the_race_is_refused(self):
        from services.refunds import service

        req = MagicMock()
        req.debt_check_passed = True
        req.debt_check_notes = "ok"
        with (
            patch.object(service.repo, "get_refund_request_by_id", return_value=_refund(status="pending_review")),
            patch.object(service.repo, "get_outstanding_carryovers_for_customer", return_value=[]),
            patch.object(service.repo, "get_unpaid_billing_totals_for_customer", return_value=Decimal("0")),
            patch.object(service.repo, "update_refund_status", return_value={}) as mock_update,
        ):
            with pytest.raises(IllegalTransitionError):
                service.accounts_review(TENANT_ID, "refund-001", req, actor_id="u", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF))

        assert mock_update.call_args.kwargs["expected_status"] == "pending_review"
