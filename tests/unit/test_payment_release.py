"""Unit tests for services.payment_release.service — payment status, partial release."""
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from shared.exceptions import (
    BusinessRuleViolationError,
    ResourceNotFoundError,
)
from shared.tenant_context import TenantContext, UserRole

TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_TOL = Decimal("0.01")


def _ctx(role: UserRole) -> TenantContext:
    return TenantContext(tenant_id=TENANT_ID, user_id="user-1", role=role)


def _billing(**kw) -> dict:
    base = {
        "id": "billing-001",
        "tenant_id": TENANT_ID,
        "customer_id": "customer-001",
        "container_id": "container-001",
        "total_ngn": Decimal("100000.00"),
        "amount_paid_ngn": Decimal("0.00"),
        "balance_ngn": Decimal("100000.00"),
        "total_cbm": Decimal("10.00"),
        "total_cartons": 10,
        "status": "unpaid",
        "invoice_number": "INV-001",
    }
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# Payment status transitions
# ---------------------------------------------------------------------------


class TestConfirmPayment:
    def _req(self, amount: str) -> MagicMock:
        req = MagicMock()
        req.amount_ngn = Decimal(amount)
        req.payment_method = "bank_transfer"
        req.payment_reference = "REF-001"
        req.payment_date = "2026-02-01"
        return req

    def test_exact_payment_sets_paid(self):
        from services.payment_release import service

        billing = _billing(balance_ngn=Decimal("100000"))
        updated = {**billing, "amount_paid_ngn": Decimal("100000"), "balance_ngn": Decimal("0"), "status": "paid"}

        with (
            patch.object(service.repo, "get_billing_by_id", return_value=billing),
            patch.object(service.repo, "create_payment_record", return_value={"id": "pay-001", "created_at": None}),
            patch.object(service.repo, "update_billing_payment", return_value=updated),
            patch("services.payment_release.service.publish_event"),
        ):
            result = service.confirm_payment(
                TENANT_ID, "billing-001", self._req("100000"),
                actor_id="u", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF)
            )
            assert result["new_payment_status"] == "paid"

    def test_partial_payment_sets_partially_paid(self):
        from services.payment_release import service

        billing = _billing(balance_ngn=Decimal("100000"))
        updated = {**billing, "amount_paid_ngn": Decimal("60000"), "balance_ngn": Decimal("40000"), "status": "partially_paid"}

        with (
            patch.object(service.repo, "get_billing_by_id", return_value=billing),
            patch.object(service.repo, "create_payment_record", return_value={"id": "pay-001", "created_at": None}),
            patch.object(service.repo, "update_billing_payment", return_value=updated),
            patch("services.payment_release.service.publish_event"),
        ):
            result = service.confirm_payment(
                TENANT_ID, "billing-001", self._req("60000"),
                actor_id="u", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF)
            )
            assert result["new_payment_status"] == "partially_paid"

    def test_overpayment_creates_refund_request(self):
        from services.payment_release import service

        billing = _billing(balance_ngn=Decimal("100000"))
        updated = {
            **billing,
            "amount_paid_ngn": Decimal("105000"),
            "balance_ngn": Decimal("-5000"),
            "status": "overpaid",
        }

        with (
            patch.object(service.repo, "get_billing_by_id", return_value=billing),
            patch.object(service.repo, "create_payment_record", return_value={"id": "pay-001", "created_at": None}),
            patch.object(service.repo, "update_billing_payment", return_value=updated),
            patch.object(service.repo, "create_overpayment_refund_request") as mock_refund,
            patch("services.payment_release.service.publish_event"),
        ):
            service.confirm_payment(
                TENANT_ID, "billing-001", self._req("105000"),
                actor_id="u", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF)
            )
            mock_refund.assert_called_once()

    def test_payment_within_tolerance_treated_as_paid(self):
        """Payment of 99999.99 on a 100000 bill is within ±0.01 tolerance → paid."""
        from services.payment_release import service

        billing = _billing(balance_ngn=Decimal("100000"))
        updated = {**billing, "balance_ngn": Decimal("0.01"), "status": "paid"}

        with (
            patch.object(service.repo, "get_billing_by_id", return_value=billing),
            patch.object(service.repo, "create_payment_record", return_value={"id": "pay-001", "created_at": None}),
            patch.object(service.repo, "update_billing_payment", return_value=updated),
            patch("services.payment_release.service.publish_event"),
        ):
            result = service.confirm_payment(
                TENANT_ID, "billing-001", self._req("99999.99"),
                actor_id="u", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF)
            )
            assert result["new_payment_status"] == "paid"

    def test_billing_not_found_raises(self):
        from services.payment_release import service

        with patch.object(service.repo, "get_billing_by_id", return_value=None):
            with pytest.raises(ResourceNotFoundError):
                service.confirm_payment(
                    TENANT_ID, "nonexistent", self._req("100000"),
                    actor_id="u", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF)
                )


# ---------------------------------------------------------------------------
# Generate release note
# ---------------------------------------------------------------------------


class TestGenerateReleaseNote:
    def _req(self, carton_tags=None, release_with_outstanding=False) -> MagicMock:
        req = MagicMock()
        req.billing_id = "billing-001"
        req.carton_tags = carton_tags or ["TAG-001", "TAG-002"]
        req.release_with_outstanding = release_with_outstanding
        req.approval_notes = "Approved by manager" if release_with_outstanding else None
        req.notes = ""
        return req

    def test_unpaid_billing_blocks_release(self):
        from services.payment_release import service

        billing = _billing(status="unpaid", balance_ngn=Decimal("100000"))

        with patch.object(service.repo, "get_billing_by_id", return_value=billing):
            with pytest.raises(BusinessRuleViolationError):
                service.generate_release_note(
                    TENANT_ID, self._req(),
                    actor_id="u", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF)
                )

    def test_release_with_outstanding_flag_bypasses_payment_check(self):
        from services.payment_release import service

        billing = _billing(status="partially_paid", balance_ngn=Decimal("10000"))
        release_note = {
            "id": "note-001",
            "reference_number": "ACME-RN-001",
            "status": "active",
            "carton_tags": ["TAG-001", "TAG-002"],
            "total_cartons": 2,
            "is_partial": False,
            "created_at": None,
        }

        with (
            patch.object(service.repo, "get_billing_by_id", return_value=billing),
            patch.object(service.repo, "mark_billing_released_with_outstanding"),
            patch.object(service.repo, "create_carryover_entry", return_value={"id": "co-001"}),
            patch.object(service.repo, "get_tenant_short", return_value="ACME"),
            patch.object(service.repo, "get_next_release_note_seq", return_value=1),
            patch.object(service.repo, "create_release_note", return_value=release_note),
            patch("services.payment_release.service.publish_event"),
        ):
            result = service.generate_release_note(
                TENANT_ID, self._req(release_with_outstanding=True),
                actor_id="u", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF)
            )
            assert result["id"] == "note-001"

    def test_paid_billing_allows_release(self):
        from services.payment_release import service

        billing = _billing(status="paid", balance_ngn=Decimal("0"))
        release_note = {
            "id": "note-001",
            "reference_number": "ACME-RN-001",
            "status": "active",
            "carton_tags": ["TAG-001", "TAG-002"],
            "total_cartons": 2,
            "is_partial": False,
            "created_at": None,
        }

        with (
            patch.object(service.repo, "get_billing_by_id", return_value=billing),
            patch.object(service.repo, "get_tenant_short", return_value="ACME"),
            patch.object(service.repo, "get_next_release_note_seq", return_value=1),
            patch.object(service.repo, "create_release_note", return_value=release_note),
            patch("services.payment_release.service.publish_event"),
        ):
            result = service.generate_release_note(
                TENANT_ID, self._req(),
                actor_id="u", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF)
            )
            assert result["id"] == "note-001"


# ---------------------------------------------------------------------------
# Release note reference number format
# ---------------------------------------------------------------------------


class TestReleaseNoteReferenceFormat:
    def test_reference_number_format(self):
        """Release note reference: {TENANT_SHORT}-RN-{YYYYMMDD}-{seq:04d}."""
        from datetime import date

        tenant_short = "ACME"
        today = date(2026, 3, 1)
        seq = 12

        ref = f"{tenant_short}-RN-{today.strftime('%Y%m%d')}-{seq:04d}"
        assert ref == "ACME-RN-20260301-0012"

    def test_sequence_zero_padded_to_four_digits(self):
        from datetime import date

        ref = f"TEST-RN-{date(2026, 1, 1).strftime('%Y%m%d')}-{1:04d}"
        assert ref.endswith("-0001")

        ref_large = f"TEST-RN-{date(2026, 1, 1).strftime('%Y%m%d')}-{1234:04d}"
        assert ref_large.endswith("-1234")
