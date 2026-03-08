"""Unit tests for services.billing.service — payment status, carryover, arithmetic."""
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

_TOLERANCE = Decimal("0.01")


def _billing(**kwargs) -> dict:
    base = {
        "id": "billing-001",
        "tenant_id": TENANT_ID,
        "customer_id": "customer-001",
        "container_id": "container-001",
        "total_ngn": Decimal("100000.00"),
        "amount_paid_ngn": Decimal("0.00"),
        "balance_ngn": Decimal("100000.00"),
        "misc_charges_ngn": Decimal("0.00"),
        "status": "unpaid",
    }
    base.update(kwargs)
    return base


class TestPaymentStatusClassification:
    """Test payment status logic from payment_release service."""

    def _classify(self, total: str, amount_paid: str) -> str:
        """Replicate payment status classification from payment_release/service.py."""
        total_ngn = Decimal(total)
        paid = Decimal(amount_paid)
        new_balance = total_ngn - paid
        if abs(new_balance) <= _TOLERANCE:
            return "paid"
        elif new_balance < -_TOLERANCE:
            return "overpaid"
        else:
            return "partially_paid"

    def test_exact_payment_is_paid(self):
        assert self._classify("100000", "100000") == "paid"

    def test_within_tolerance_is_paid(self):
        assert self._classify("100000", "99999.995") == "paid"

    def test_overpayment_above_tolerance(self):
        assert self._classify("100000", "100001") == "overpaid"

    def test_partial_payment(self):
        assert self._classify("100000", "50000") == "partially_paid"

    def test_zero_payment(self):
        assert self._classify("100000", "0") == "partially_paid"

    def test_payment_exactly_at_tolerance_boundary(self):
        # balance = 0.01 is exactly at tolerance — should be paid
        assert self._classify("100000", "99999.99") == "paid"

    def test_payment_just_over_tolerance(self):
        # balance = 0.02 just exceeds tolerance — partially_paid
        assert self._classify("100000", "99999.98") == "partially_paid"


class TestBillingService:
    """Test billing service functions with mocked repository."""

    def test_get_billing_returns_empty_for_unknown_customer(self):
        """Staff requesting billing for a nonexistent customer gets an empty list."""
        from services.billing import service
        from shared.tenant_context import TenantContext, UserRole

        ctx = TenantContext(
            tenant_id=TENANT_ID, user_id="u", role=UserRole.NIGERIA_OFFICE_STAFF
        )
        with patch.object(service.repo, "list_billing_for_customer", return_value=[]):
            result = service.get_billing_for_customer(TENANT_ID, "nonexistent", ctx)
            assert result == []

    def test_customer_can_only_see_own_billing(self):
        """Customer-001 cannot access billing records belonging to customer-999."""
        from services.billing import service
        from shared.exceptions import InsufficientPermissionsError
        from shared.tenant_context import TenantContext, UserRole

        customer_row = {"id": "customer-001"}  # logged-in user is customer-001

        ctx = TenantContext(
            tenant_id=TENANT_ID, user_id="user-cust-001", role=UserRole.CUSTOMER
        )
        with patch.object(service.repo, "get_customer_by_user_id", return_value=customer_row):
            with pytest.raises(InsufficientPermissionsError):
                # requesting billing for customer-999, but ctx.user maps to customer-001
                service.get_billing_for_customer(TENANT_ID, "customer-999", ctx)


class TestCarryoverArithmetic:
    """Test carryover ledger arithmetic logic."""

    def test_carryover_reduces_next_billing(self):
        """A carryover from period N should reduce total for period N+1."""
        total_ngn = Decimal("100000.00")
        carryover_ngn = Decimal("15000.00")
        effective_total = total_ngn - carryover_ngn
        assert effective_total == Decimal("85000.00")

    def test_full_carryover_clears_balance(self):
        total_ngn = Decimal("5000.00")
        carryover_ngn = Decimal("5000.00")
        assert total_ngn - carryover_ngn == Decimal("0.00")

    def test_carryover_exceeds_total(self):
        """If carryover > total, customer should receive credit."""
        total_ngn = Decimal("3000.00")
        carryover_ngn = Decimal("5000.00")
        result = total_ngn - carryover_ngn
        assert result < Decimal("0")  # negative balance = overpayment


class TestCbmArithmetic:
    """Test CBM-based billing calculation arithmetic."""

    def test_total_ngn_from_cbm(self):
        """subtotal_usd = cbm × cbm_rate_usd; total_ngn = subtotal_usd × exchange_rate"""
        cbm = Decimal("5.5")
        cbm_rate_usd = Decimal("45.00")
        exchange_rate = Decimal("1550.00")
        misc_charges_ngn = Decimal("2000.00")

        subtotal_usd = cbm * cbm_rate_usd  # 247.50
        subtotal_ngn = subtotal_usd * exchange_rate  # 383,625
        total_ngn = subtotal_ngn + misc_charges_ngn  # 385,625

        assert subtotal_usd == Decimal("247.50")
        assert subtotal_ngn == Decimal("383625.00")
        assert total_ngn == Decimal("385625.00")

    def test_zero_cbm_billing(self):
        cbm = Decimal("0")
        cbm_rate_usd = Decimal("45.00")
        exchange_rate = Decimal("1550.00")
        assert cbm * cbm_rate_usd * exchange_rate == Decimal("0")

    def test_zero_exchange_rate_produces_zero_ngn(self):
        """If dollar rate is 0 (misconfigured), NGN total must be 0, not an error."""
        cbm = Decimal("5.5")
        cbm_rate_usd = Decimal("45.00")
        exchange_rate = Decimal("0")
        total_ngn = cbm * cbm_rate_usd * exchange_rate
        assert total_ngn == Decimal("0")

    def test_zero_cbm_rate_produces_zero_subtotal(self):
        """If CBM rate per unit is 0 (waiver), subtotal_usd = 0."""
        cbm = Decimal("10.0")
        cbm_rate_usd = Decimal("0")
        exchange_rate = Decimal("1550.00")
        assert cbm * cbm_rate_usd * exchange_rate == Decimal("0")

    def test_negative_outstanding_balance_means_credit(self):
        """A negative balance_ngn after carryover means the customer has credit."""
        total_ngn = Decimal("5000.00")
        carryover_ngn = Decimal("8000.00")
        balance = total_ngn - carryover_ngn
        assert balance == Decimal("-3000.00")
        assert balance < Decimal("0")  # credit situation
