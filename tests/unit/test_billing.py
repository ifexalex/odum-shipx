"""Unit tests for services.billing.service — payment status, carryover, arithmetic."""

from decimal import Decimal
from unittest.mock import patch

import pytest

from shared.tenant_context import TenantContext, UserRole

TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def _ctx(role: UserRole, user_id: str = "user-1") -> TenantContext:
    return TenantContext(tenant_id=TENANT_ID, user_id=user_id, role=role)


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

        ctx = TenantContext(tenant_id=TENANT_ID, user_id="u", role=UserRole.NIGERIA_OFFICE_STAFF)
        with patch.object(service.repo, "list_billing_for_customer", return_value=[]):
            result = service.get_billing_for_customer(TENANT_ID, "nonexistent", ctx)
            assert result == []

    def test_customer_can_only_see_own_billing(self):
        """Customer-001 cannot access billing records belonging to customer-999."""
        from services.billing import service
        from shared.exceptions import InsufficientPermissionsError
        from shared.tenant_context import TenantContext, UserRole

        customer_row = {"id": "customer-001"}  # logged-in user is customer-001

        ctx = TenantContext(tenant_id=TENANT_ID, user_id="user-cust-001", role=UserRole.CUSTOMER)
        with patch.object(service.repo, "get_customer_by_user_id", return_value=customer_row):
            with pytest.raises(InsufficientPermissionsError):
                # requesting billing for customer-999, but ctx.user maps to customer-001
                service.get_billing_for_customer(TENANT_ID, "customer-999", ctx)

    def test_get_billing_by_id_returns_enriched_record(self):
        """GET /v1/billing/{id}/detail returns the same shape as a list row."""
        from services.billing import service

        ctx = _ctx(UserRole.NIGERIA_OFFICE_STAFF)
        row = _billing(
            invoice_number="INV-001",
            customer_name="Ada",
            container_number="CONT-9",
            total_cbm=Decimal("2.5"),
            cbm_rate_usd=Decimal("250"),
            exchange_rate_ngn=Decimal("1600"),
            subtotal_usd=Decimal("625"),
            subtotal_ngn=Decimal("1000000"),
        )
        with (
            patch.object(service.repo, "get_billing_by_id", return_value=row),
            patch.object(service.repo, "get_misc_charges", return_value=[]),
            patch.object(service.repo, "get_payment_records", return_value=[]),
            patch.object(service.repo, "get_applied_carryovers", return_value=[]),
            patch.object(service.repo, "get_active_disputes", return_value=[]),
        ):
            result = service.get_billing(TENANT_ID, "billing-001", ctx)

        assert result["id"] == "billing-001"
        assert result["invoice_number"] == "INV-001"
        assert result["customer_name"] == "Ada"
        assert result["payment_status"] == "unpaid"

    def test_get_billing_by_id_unknown_raises_not_found(self):
        """An id that is not in this tenant is a 404, not an empty success."""
        from services.billing import service
        from shared.exceptions import ResourceNotFoundError

        ctx = _ctx(UserRole.NIGERIA_OFFICE_STAFF)
        with patch.object(service.repo, "get_billing_by_id", return_value=None):
            with pytest.raises(ResourceNotFoundError):
                service.get_billing(TENANT_ID, "billing-nope", ctx)

    def test_get_billing_by_id_rejects_other_customers_record(self):
        """A customer addressing another customer's billing id is refused.

        The whole point of a by-id read is that the id is guessable from a URL,
        so the ownership check has to live in the service, not in the caller.
        """
        from services.billing import service
        from shared.exceptions import InsufficientPermissionsError

        ctx = _ctx(UserRole.CUSTOMER, user_id="user-cust-001")
        with (
            patch.object(service.repo, "get_billing_by_id", return_value=_billing(customer_id="customer-999")),
            patch.object(service.repo, "get_customer_by_user_id", return_value={"id": "customer-001"}),
        ):
            with pytest.raises(InsufficientPermissionsError):
                service.get_billing(TENANT_ID, "billing-001", ctx)

    def test_get_billing_by_id_allows_own_record(self):
        """The same customer reading their own billing id succeeds."""
        from services.billing import service

        ctx = _ctx(UserRole.CUSTOMER, user_id="user-cust-001")
        row = _billing(
            customer_id="customer-001",
            total_cbm=Decimal("1"),
            cbm_rate_usd=Decimal("250"),
            exchange_rate_ngn=Decimal("1600"),
            subtotal_usd=Decimal("250"),
            subtotal_ngn=Decimal("400000"),
        )
        with (
            patch.object(service.repo, "get_billing_by_id", return_value=row),
            patch.object(service.repo, "get_customer_by_user_id", return_value={"id": "customer-001"}),
            patch.object(service.repo, "get_misc_charges", return_value=[]),
            patch.object(service.repo, "get_payment_records", return_value=[]),
            patch.object(service.repo, "get_applied_carryovers", return_value=[]),
            patch.object(service.repo, "get_active_disputes", return_value=[]),
        ):
            result = service.get_billing(TENANT_ID, "billing-001", ctx)

        assert result["customer_id"] == "customer-001"

    def test_get_billing_by_id_fails_closed_when_customer_unmapped(self):
        """A customer-role JWT with no customer row is denied, not served."""
        from services.billing import service
        from shared.exceptions import InsufficientPermissionsError

        ctx = _ctx(UserRole.CUSTOMER, user_id="user-orphan")
        with (
            patch.object(service.repo, "get_billing_by_id", return_value=_billing()),
            patch.object(service.repo, "get_customer_by_user_id", return_value=None),
        ):
            with pytest.raises(InsufficientPermissionsError):
                service.get_billing(TENANT_ID, "billing-001", ctx)

    def test_get_billing_stats_normalises_row(self):
        """Stats aggregates: money fields returned as strings, counts as ints."""
        from services.billing import service

        raw = {
            "outstanding_ngn": "28658693.98",
            "paid_this_month_ngn": 0,
            "overdue": 3,
            "total": 325,
            "unpaid": 104,
            "partially_paid": 111,
            "paid": 90,
            "overpaid": 8,
            "waived": 6,
            "released_with_outstanding": 6,
        }
        with patch.object(service.repo, "get_billing_stats", return_value=raw) as m:
            result = service.get_billing_stats(TENANT_ID)
        assert m.call_args[0][0] == TENANT_ID
        assert result["total"] == 325
        assert result["outstanding_ngn"] == "28658693.98"


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


class TestHandlePaymentDueCbmPricing:
    """handle_payment_due against real per-package-type/currency CBM rate
    configs (shared/cbm_rate.py) — "flat" is just carton_rate == bag_rate
    == bale_rate, so there's no separate mode branch to test in the money
    math itself, only the rate config's actual values."""

    def _mock_repo(self, cbm_config: dict, cbm_by_unit: dict, dollar_rate=Decimal("1550")):
        from services.billing import service

        captured: dict = {}

        def _create_billing(tid, data):
            captured.update(data)
            return {**data, "id": "billing-001"}

        defaults = dict(
            get_tenant_config_value=lambda tid, key: None,
            get_cbm_and_carton_totals=lambda *a: {
                "total_cbm": sum(Decimal(str(v)) for v in cbm_by_unit.values()),
                "total_cartons": 10,
            },
            get_cbm_by_package_type=lambda *a: cbm_by_unit,
            get_outstanding_carryovers=lambda *a: [],
            get_pending_credit_refunds=lambda *a: [],
            get_tenant_short=lambda tid: "ACM",
            get_next_invoice_seq=lambda tid: 1,
            create_billing=_create_billing,
            mark_carryovers_applied=lambda *a: None,
            mark_credit_refunds_applied=lambda *a: None,
            get_customer_contact=lambda tid, cid: None,
        )
        patchers = [patch.object(service.repo, name, side_effect=fn) for name, fn in defaults.items()]
        patchers.append(patch.object(service, "get_effective_dollar_rate", return_value={"rate": dollar_rate}))
        patchers.append(patch.object(service, "get_cbm_rate_config", return_value=cbm_config))
        for p in patchers:
            p.start()
        return patchers, captured

    def _run(self, cbm_config: dict, cbm_by_unit: dict, dollar_rate=Decimal("1550")) -> dict:
        from services.billing import service

        patchers, captured = self._mock_repo(cbm_config, cbm_by_unit, dollar_rate)
        try:
            with patch("services.billing.service.publish_event"):
                service.handle_payment_due(TENANT_ID, "container-001", "customer-001", "ACME001")
        finally:
            for p in patchers:
                p.stop()
        return captured

    def test_flat_usd_rate_stays_exact_no_rounding_drift(self):
        # total_cbm=5.333 is not a round number — the blended-average
        # back-derivation would introduce drift here if it applied whenever
        # there's genuinely one effective rate, which it should not.
        config = {
            "currency": "usd",
            "rate_mode": "flat",
            "carton_rate": Decimal("45"),
            "bag_rate": Decimal("45"),
            "bale_rate": Decimal("45"),
        }
        billing = self._run(config, {"carton": Decimal("5.333")})

        assert billing["cbm_rate_usd"] == Decimal("45")
        assert billing["cbm_rate_currency"] == "USD"
        assert billing["cbm_rate_mode"] == "flat"

    def test_genuine_per_package_type_mix_uses_blended_average_and_records_breakdown(self):
        import json

        config = {
            "currency": "usd",
            "rate_mode": "per_package_type",
            "carton_rate": Decimal("45"),
            "bag_rate": Decimal("45"),
            "bale_rate": Decimal("60"),
        }
        billing = self._run(config, {"carton": Decimal("10"), "bag": Decimal("5"), "bale": Decimal("2")})

        # subtotal_usd = 10*45 + 5*45 + 2*60 = 450 + 225 + 120 = 795
        assert billing["subtotal_usd"] == Decimal("795.00")
        # total_cbm = 17; blended rate = 795 / 17 = 46.7647 (4dp)
        assert billing["cbm_rate_usd"] == Decimal("46.7647")
        assert billing["cbm_rate_mode"] == "per_package_type"
        breakdown = json.loads(billing["cbm_breakdown"])
        assert breakdown["carton"]["subtotal"] == "450.00"
        assert breakdown["bag"]["subtotal"] == "225.00"
        assert breakdown["bale"]["subtotal"] == "120.00"

    def test_ngn_currency_back_derives_subtotal_usd(self):
        config = {
            "currency": "ngn",
            "rate_mode": "flat",
            "carton_rate": Decimal("45000"),
            "bag_rate": Decimal("45000"),
            "bale_rate": Decimal("45000"),
        }
        billing = self._run(config, {"carton": Decimal("10")}, dollar_rate=Decimal("1500"))

        assert billing["subtotal_ngn"] == Decimal("450000.00")
        assert billing["subtotal_usd"] == Decimal("300.00")  # 450000 / 1500
        assert billing["cbm_rate_currency"] == "NGN"
        # single effective rate (all three equal) -> exact, not a blended
        # back-division: 45000 / 1500 = 30.0000
        assert billing["cbm_rate_usd"] == Decimal("30.0000")

    def test_skip_guard_fires_when_all_three_rates_are_zero(self):
        from services.billing import service

        config = {
            "currency": "usd",
            "rate_mode": "flat",
            "carton_rate": Decimal("0"),
            "bag_rate": Decimal("0"),
            "bale_rate": Decimal("0"),
        }
        patchers, captured = self._mock_repo(config, {"carton": Decimal("10")})
        try:
            with patch("services.billing.service.publish_event"):
                service.handle_payment_due(TENANT_ID, "container-001", "customer-001", "ACME001")
        finally:
            for p in patchers:
                p.stop()
        assert captured == {}  # create_billing never called

    def test_one_zero_rate_among_others_still_bills_normally(self):
        """A tenant intentionally offering free bale shipping (bale_rate=0)
        must still bill the carton/bag portion — only a fully-unconfigured
        config (all three zero) should skip billing entirely."""
        config = {
            "currency": "usd",
            "rate_mode": "per_package_type",
            "carton_rate": Decimal("45"),
            "bag_rate": Decimal("45"),
            "bale_rate": Decimal("0"),
        }
        billing = self._run(config, {"carton": Decimal("10"), "bale": Decimal("5")})

        assert billing["subtotal_usd"] == Decimal("450.00")  # 10*45 + 5*0


class TestCancelBilling:
    """Test cancel_billing service function."""

    def test_cancel_unpaid_billing_succeeds(self):
        from services.billing import service

        billing = _billing(status="unpaid")
        cancelled = {**billing, "status": "cancelled"}

        with (
            patch.object(service.repo, "get_billing_by_id", return_value=billing),
            patch.object(service.repo, "get_confirmed_payment_count", return_value=0),
            patch.object(service.repo, "get_active_release_note_count", return_value=0),
            patch.object(service.repo, "cancel_billing", return_value=cancelled),
            patch("services.billing.service.log_audit"),
        ):
            result = service.cancel_billing(TENANT_ID, "billing-001", "Data entry error", actor_id="u")
            assert result["status"] == "cancelled"

    def test_billing_not_found_raises(self):
        from services.billing import service
        from shared.exceptions import ResourceNotFoundError

        with patch.object(service.repo, "get_billing_by_id", return_value=None):
            with pytest.raises(ResourceNotFoundError):
                service.cancel_billing(TENANT_ID, "nonexistent", "reason", actor_id="u")

    def test_partially_paid_billing_raises(self):
        from services.billing import service
        from shared.exceptions import BusinessRuleViolationError

        billing = _billing(status="partially_paid")

        with patch.object(service.repo, "get_billing_by_id", return_value=billing):
            with pytest.raises(BusinessRuleViolationError):
                service.cancel_billing(TENANT_ID, "billing-001", "reason", actor_id="u")

    def test_paid_billing_raises(self):
        from services.billing import service
        from shared.exceptions import BusinessRuleViolationError

        billing = _billing(status="paid")

        with patch.object(service.repo, "get_billing_by_id", return_value=billing):
            with pytest.raises(BusinessRuleViolationError):
                service.cancel_billing(TENANT_ID, "billing-001", "reason", actor_id="u")

    def test_confirmed_payment_exists_raises(self):
        from services.billing import service
        from shared.exceptions import BusinessRuleViolationError

        billing = _billing(status="unpaid")

        with (
            patch.object(service.repo, "get_billing_by_id", return_value=billing),
            patch.object(service.repo, "get_confirmed_payment_count", return_value=1),
        ):
            with pytest.raises(BusinessRuleViolationError):
                service.cancel_billing(TENANT_ID, "billing-001", "reason", actor_id="u")

    def test_active_release_note_raises(self):
        from services.billing import service
        from shared.exceptions import BusinessRuleViolationError

        billing = _billing(status="unpaid")

        with (
            patch.object(service.repo, "get_billing_by_id", return_value=billing),
            patch.object(service.repo, "get_confirmed_payment_count", return_value=0),
            patch.object(service.repo, "get_active_release_note_count", return_value=1),
        ):
            with pytest.raises(BusinessRuleViolationError):
                service.cancel_billing(TENANT_ID, "billing-001", "reason", actor_id="u")

    def test_repo_cancel_returns_none_raises(self):
        """Race condition: row deleted between the guard read and the cancel write."""
        from services.billing import service
        from shared.exceptions import ResourceNotFoundError

        billing = _billing(status="unpaid")

        with (
            patch.object(service.repo, "get_billing_by_id", return_value=billing),
            patch.object(service.repo, "get_confirmed_payment_count", return_value=0),
            patch.object(service.repo, "get_active_release_note_count", return_value=0),
            patch.object(service.repo, "cancel_billing", return_value=None),
        ):
            with pytest.raises(ResourceNotFoundError):
                service.cancel_billing(TENANT_ID, "billing-001", "reason", actor_id="u")


# ---------------------------------------------------------------------------
# Apply carryover
# ---------------------------------------------------------------------------


def _carryover(**kwargs) -> dict:
    base = {
        "id": "carryover-001",
        "tenant_id": TENANT_ID,
        "customer_id": "customer-001",
        "source_billing_id": "billing-000",
        "carryover_amount_ngn": Decimal("5000.00"),
        "status": "outstanding",
    }
    base.update(kwargs)
    return base


class TestApplyCarryover:
    def test_applies_outstanding_carryover_successfully(self):
        from services.billing import service

        billing = _billing(status="unpaid", total_ngn=Decimal("100000"))
        carryover = _carryover()
        updated = {**billing, "total_ngn": Decimal("105000"), "balance_ngn": Decimal("105000")}

        with (
            patch.object(service.repo, "get_billing_by_id", return_value=billing),
            patch.object(service.repo, "get_carryover_by_id", return_value=carryover),
            patch.object(service.repo, "mark_carryovers_applied"),
            patch.object(service.repo, "increment_billing_misc_fees", return_value=updated),
            patch("services.billing.service.log_audit"),
        ):
            result = service.apply_carryover(TENANT_ID, "billing-001", "carryover-001", actor_id="u")
            assert result["carryover_amount_ngn"] == Decimal("5000.00")
            assert result["new_total_ngn"] == Decimal("105000")

    def test_applying_to_a_paid_billing_recomputes_status_to_partially_paid(self):
        # Adding carried-forward debt to a fully-paid record means it now owes
        # again — the status must not stay 'paid'.
        from services.billing import service

        billing = _billing(
            status="paid",
            total_ngn=Decimal("100000"),
            amount_paid_ngn=Decimal("100000"),
            balance_ngn=Decimal("0"),
        )
        carryover = _carryover()
        updated = {**billing, "total_ngn": Decimal("105000"), "balance_ngn": Decimal("5000")}

        with (
            patch.object(service.repo, "get_billing_by_id", return_value=billing),
            patch.object(service.repo, "get_carryover_by_id", return_value=carryover),
            patch.object(service.repo, "mark_carryovers_applied"),
            patch.object(service.repo, "increment_billing_misc_fees", return_value=updated),
            patch.object(service.repo, "set_billing_status", return_value={**updated, "status": "partially_paid"}) as mock_status,
            patch("services.billing.service.log_audit"),
        ):
            service.apply_carryover(TENANT_ID, "billing-001", "carryover-001", actor_id="u")

        mock_status.assert_called_once_with(TENANT_ID, "billing-001", "partially_paid")

    def test_billing_not_found_raises(self):
        from services.billing import service
        from shared.exceptions import ResourceNotFoundError

        with patch.object(service.repo, "get_billing_by_id", return_value=None):
            with pytest.raises(ResourceNotFoundError):
                service.apply_carryover(TENANT_ID, "billing-001", "carryover-001", actor_id="u")

    def test_cancelled_billing_raises(self):
        from services.billing import service
        from shared.exceptions import BusinessRuleViolationError

        with patch.object(service.repo, "get_billing_by_id", return_value=_billing(status="cancelled")):
            with pytest.raises(BusinessRuleViolationError):
                service.apply_carryover(TENANT_ID, "billing-001", "carryover-001", actor_id="u")

    def test_waived_billing_raises(self):
        from services.billing import service
        from shared.exceptions import BusinessRuleViolationError

        with patch.object(service.repo, "get_billing_by_id", return_value=_billing(status="waived")):
            with pytest.raises(BusinessRuleViolationError):
                service.apply_carryover(TENANT_ID, "billing-001", "carryover-001", actor_id="u")

    def test_carryover_not_found_raises(self):
        from services.billing import service
        from shared.exceptions import ResourceNotFoundError

        with (
            patch.object(service.repo, "get_billing_by_id", return_value=_billing()),
            patch.object(service.repo, "get_carryover_by_id", return_value=None),
        ):
            with pytest.raises(ResourceNotFoundError):
                service.apply_carryover(TENANT_ID, "billing-001", "carryover-001", actor_id="u")

    def test_already_applied_carryover_raises(self):
        from services.billing import service
        from shared.exceptions import BusinessRuleViolationError

        with (
            patch.object(service.repo, "get_billing_by_id", return_value=_billing()),
            patch.object(service.repo, "get_carryover_by_id", return_value=_carryover(status="applied")),
        ):
            with pytest.raises(BusinessRuleViolationError):
                service.apply_carryover(TENANT_ID, "billing-001", "carryover-001", actor_id="u")

    def test_customer_mismatch_raises(self):
        from services.billing import service
        from shared.exceptions import BusinessRuleViolationError

        billing = _billing(customer_id="customer-001")
        carryover = _carryover(customer_id="customer-999")

        with (
            patch.object(service.repo, "get_billing_by_id", return_value=billing),
            patch.object(service.repo, "get_carryover_by_id", return_value=carryover),
        ):
            with pytest.raises(BusinessRuleViolationError):
                service.apply_carryover(TENANT_ID, "billing-001", "carryover-001", actor_id="u")

    def test_mark_carryovers_applied_called_with_correct_args(self):
        from services.billing import service

        billing = _billing()
        carryover = _carryover()
        updated = {**billing, "total_ngn": Decimal("105000"), "balance_ngn": Decimal("105000")}

        with (
            patch.object(service.repo, "get_billing_by_id", return_value=billing),
            patch.object(service.repo, "get_carryover_by_id", return_value=carryover),
            patch.object(service.repo, "mark_carryovers_applied") as mock_mark,
            patch.object(service.repo, "increment_billing_misc_fees", return_value=updated),
            patch("services.billing.service.log_audit"),
        ):
            service.apply_carryover(TENANT_ID, "billing-001", "carryover-001", actor_id="u")
            mock_mark.assert_called_once_with(TENANT_ID, ["carryover-001"], "billing-001")


class TestAddMiscCharge:
    """B8 — a misc charge added from a configured charge type carries charge_type_id."""

    def _charge_row(self) -> dict:
        return {
            "id": "mc-1",
            "billing_id": "billing-001",
            "description": "Customs",
            "amount_ngn": Decimal("15000"),
            "charge_type": "service_charge",
            "created_at": "2026-07-13T00:00:00Z",
        }

    def test_charge_type_id_passed_through_to_repo(self):
        from services.billing import service

        with (
            patch.object(service.repo, "get_billing_by_id", return_value=_billing()),
            patch.object(service.repo, "add_misc_charge", return_value=self._charge_row()) as mock_add,
            patch.object(service.repo, "increment_billing_misc_fees", return_value=_billing()),
            patch("services.billing.service.log_audit"),
        ):
            service.add_misc_charge(
                TENANT_ID,
                "billing-001",
                {"description": "Customs", "amount_ngn": "15000", "charge_type": "service_charge", "charge_type_id": "ct-9"},
                actor_id="u",
            )

        assert mock_add.call_args[0][1]["charge_type_id"] == "ct-9"

    def test_free_form_charge_has_null_charge_type_id(self):
        from services.billing import service

        with (
            patch.object(service.repo, "get_billing_by_id", return_value=_billing()),
            patch.object(service.repo, "add_misc_charge", return_value=self._charge_row()) as mock_add,
            patch.object(service.repo, "increment_billing_misc_fees", return_value=_billing()),
            patch("services.billing.service.log_audit"),
        ):
            service.add_misc_charge(
                TENANT_ID,
                "billing-001",
                {"description": "Ad-hoc", "amount_ngn": "500", "charge_type": "other"},
                actor_id="u",
            )

        assert mock_add.call_args[0][1]["charge_type_id"] is None


class TestListRecentPayments:
    """P2-5 — §6.1 dashboard recent-payments feed."""

    def test_serializes_rows(self):
        from services.billing import service

        rows = [
            {
                "id": "p1",
                "billing_id": "b1",
                "customer_name": "Ngozi",
                "amount_ngn": Decimal("50000.00"),
                "payment_method": "bank_transfer",
                "reference_number": "TRF-123",
                "payment_date": "2026-07-16",
                "created_at": "2026-07-16T09:00:00Z",
            }
        ]
        with patch.object(service.repo, "list_recent_payments", return_value=rows) as mock_list:
            out = service.list_recent_payments(TENANT_ID, limit=8)

        mock_list.assert_called_once_with(TENANT_ID, 8)
        assert out[0]["amount_ngn"] == "50000.00"
        assert out[0]["customer_name"] == "Ngozi"
        assert out[0]["payment_method"] == "bank_transfer"


class TestListBilling:
    """GET /v1/billing — _BILLING_READ_ROLES allows the customer role too.

    Ground-truth security fix (2026-07-19): this endpoint had no ownership
    scoping at all — any customer could list every other customer's billing
    (amounts, payment status) in the tenant. CUSTOMER role must be force-
    scoped to their own customer_id, not merely permitted through.
    """

    def test_staff_sees_unfiltered_results(self):
        from services.billing import service

        rows = [{"id": "b1", "customer_id": "cust-1"}, {"id": "b2", "customer_id": "cust-2"}]
        with (
            patch.object(service.repo, "list_billing_all", return_value=(rows, None, False)) as mock_list,
            patch.object(service, "_enrich_billing", side_effect=lambda tid, r: r),
        ):
            page, _, _ = service.list_billing(TENANT_ID, {}, limit=50, cursor=None, ctx=_ctx(UserRole.TENANT_ADMIN))

        assert len(page) == 2
        # No customer_id was injected into the filters passed to the repo.
        assert mock_list.call_args.args[1] == {}

    def test_customer_is_force_scoped_to_their_own_customer_id(self):
        from services.billing import service

        with (
            patch.object(service.repo, "get_customer_by_user_id", return_value={"id": "cust-1"}) as mock_get_customer,
            patch.object(service.repo, "list_billing_all", return_value=([], None, False)) as mock_list,
        ):
            service.list_billing(TENANT_ID, {}, limit=50, cursor=None, ctx=_ctx(UserRole.CUSTOMER, user_id="u-1"))

        mock_get_customer.assert_called_once_with(TENANT_ID, "u-1")
        assert mock_list.call_args.args[1]["customer_id"] == "cust-1"

    def test_customer_cannot_override_the_customer_id_filter(self):
        """A customer passing ?customer_id=<someone-else> must be silently
        overridden to their own id, not honoured — that was the exact leak."""
        from services.billing import service

        with (
            patch.object(service.repo, "get_customer_by_user_id", return_value={"id": "cust-1"}),
            patch.object(service.repo, "list_billing_all", return_value=([], None, False)) as mock_list,
        ):
            service.list_billing(
                TENANT_ID,
                {"customer_id": "someone-elses-customer-id"},
                limit=50,
                cursor=None,
                ctx=_ctx(UserRole.CUSTOMER, user_id="u-1"),
            )

        assert mock_list.call_args.args[1]["customer_id"] == "cust-1"

    def test_customer_with_no_linked_customer_row_gets_empty_page(self):
        from services.billing import service

        with (
            patch.object(service.repo, "get_customer_by_user_id", return_value=None),
            patch.object(service.repo, "list_billing_all") as mock_list,
        ):
            page, next_cursor, has_more = service.list_billing(
                TENANT_ID, {}, limit=50, cursor=None, ctx=_ctx(UserRole.CUSTOMER, user_id="orphan-user")
            )

        assert page == []
        assert next_cursor is None
        assert has_more is False
        mock_list.assert_not_called()

    def test_no_ctx_behaves_as_unscoped_staff_call(self):
        """Internal/legacy callers that don't pass ctx must not be scoped —
        keeps this a strictly additive fix."""
        from services.billing import service

        with (
            patch.object(service.repo, "list_billing_all", return_value=([], None, False)) as mock_list,
        ):
            service.list_billing(TENANT_ID, {}, limit=50, cursor=None)

        assert mock_list.call_args.args[1] == {}

    def test_sort_field_and_direction_passed_through_to_repo(self):
        """BillingList's 'Reference'/'Billed' sortable columns — service.list_billing
        must forward sort_field/sort_direction to the repo unchanged."""
        from services.billing import service

        with patch.object(service.repo, "list_billing_all", return_value=([], None, False)) as mock_list:
            service.list_billing(
                TENANT_ID,
                {},
                limit=50,
                cursor=None,
                sort_field="invoice_number",
                sort_direction="asc",
            )

        assert mock_list.call_args.kwargs["sort_field"] == "invoice_number"
        assert mock_list.call_args.kwargs["sort_direction"] == "asc"

    def test_sort_field_defaults_to_created_at(self):
        from services.billing import service

        with patch.object(service.repo, "list_billing_all", return_value=([], None, False)) as mock_list:
            service.list_billing(TENANT_ID, {}, limit=50, cursor=None)

        assert mock_list.call_args.kwargs["sort_field"] == "created_at"
        assert mock_list.call_args.kwargs["sort_direction"] == "DESC"


class TestListBillingAllRepositorySort:
    """services/billing/repository.py::list_billing_all — sort_field is prefixed
    with the `b.` table alias before hitting build_paginated_query, since this
    query sorts against the aliased `billing b` table directly (unlike
    tracking's list_containers, which sorts a flattened subquery)."""

    def test_sorts_by_billed_at_for_the_billed_column(self):
        from services.billing import repository

        with patch.object(repository, "execute_with_tenant", return_value=[]) as mock_exec:
            repository.list_billing_all(
                TENANT_ID,
                {},
                limit=50,
                cursor=None,
                sort_field="billed_at",
                sort_direction="asc",
            )

        query = mock_exec.call_args[0][1]
        assert "ORDER BY b.billed_at ASC" in query

    def test_sorts_by_invoice_number_for_the_reference_column(self):
        from services.billing import repository

        with patch.object(repository, "execute_with_tenant", return_value=[]) as mock_exec:
            repository.list_billing_all(
                TENANT_ID,
                {},
                limit=50,
                cursor=None,
                sort_field="invoice_number",
                sort_direction="desc",
            )

        query = mock_exec.call_args[0][1]
        assert "ORDER BY b.invoice_number DESC" in query

    def test_default_sort_is_created_at_desc(self):
        from services.billing import repository

        with patch.object(repository, "execute_with_tenant", return_value=[]) as mock_exec:
            repository.list_billing_all(TENANT_ID, {}, limit=50, cursor=None)

        query = mock_exec.call_args[0][1]
        assert "ORDER BY b.created_at DESC" in query


class TestListBillingAllRepositoryFilters:
    """Ground-truth gap found live, reported by the user: "let's double check
    the billing details filters and date ranges search and other filters are
    correctly doing what they should do." GET /v1/billing's "calendar" and
    "Filters" buttons rendered with no onClick — dead UI — and list_billing_all
    had zero support for a date range or multi-status filtering to back them.
    """

    def test_status_filter_uses_any_for_multi_select(self):
        from services.billing import repository

        with patch.object(repository, "execute_with_tenant", return_value=[]) as mock_exec:
            repository.list_billing_all(
                TENANT_ID,
                {"status": ["unpaid", "partially_paid"]},
                limit=50,
                cursor=None,
            )

        query, params = mock_exec.call_args[0][1], mock_exec.call_args[0][2]
        assert "b.status = ANY(%(statuses)s)" in query
        assert params["statuses"] == ["unpaid", "partially_paid"]

    def test_status_filter_accepts_a_bare_string(self):
        from services.billing import repository

        with patch.object(repository, "execute_with_tenant", return_value=[]) as mock_exec:
            repository.list_billing_all(TENANT_ID, {"status": "unpaid"}, limit=50, cursor=None)

        params = mock_exec.call_args[0][2]
        assert params["statuses"] == ["unpaid"]

    def test_created_after_filters_on_billed_at(self):
        from services.billing import repository

        with patch.object(repository, "execute_with_tenant", return_value=[]) as mock_exec:
            repository.list_billing_all(
                TENANT_ID,
                {"created_after": "2026-09-01"},
                limit=50,
                cursor=None,
            )

        query, params = mock_exec.call_args[0][1], mock_exec.call_args[0][2]
        assert "b.billed_at >= %(created_after)s" in query
        assert params["created_after"] == "2026-09-01"

    def test_created_before_filters_on_billed_at(self):
        from services.billing import repository

        with patch.object(repository, "execute_with_tenant", return_value=[]) as mock_exec:
            repository.list_billing_all(
                TENANT_ID,
                {"created_before": "2026-09-07"},
                limit=50,
                cursor=None,
            )

        query, params = mock_exec.call_args[0][1], mock_exec.call_args[0][2]
        assert "b.billed_at <= %(created_before)s" in query
        assert params["created_before"] == "2026-09-07"

    def test_no_date_filter_by_default(self):
        from services.billing import repository

        with patch.object(repository, "execute_with_tenant", return_value=[]) as mock_exec:
            repository.list_billing_all(TENANT_ID, {}, limit=50, cursor=None)

        query = mock_exec.call_args[0][1]
        assert "billed_at" not in query


class TestBillingListHandlerQueryParams:
    """GET /v1/billing — handler-level parsing of the Filters panel's
    comma-separated multi-status param and the date-range params, mirroring
    tracking's TestContainersHandlerQueryParams for GET /v1/containers."""

    def _event(self, query: dict | None = None) -> dict:
        return {
            "requestContext": {
                "requestId": "req-billing-001",
                "http": {"method": "GET", "path": "/v1/billing"},
                "authorizer": {"claims": {"sub": "user-1", "custom:tenant_id": TENANT_ID}},
                "identity": {"sourceIp": "127.0.0.1"},
            },
            "headers": {},
            "body": "{}",
            "queryStringParameters": query or {},
            "pathParameters": {},
        }

    def test_comma_separated_status_becomes_a_list_filter(self):
        from services.billing import handler, service

        with (
            patch("services.billing.handler.get_tenant_context", return_value=_ctx(UserRole.NIGERIA_OFFICE_STAFF)),
            patch.object(service, "list_billing", return_value=([], None, False)) as mock_list,
        ):
            resp = handler.lambda_handler(self._event({"status": "unpaid,partially_paid"}), None)

        assert resp["statusCode"] == 200
        filters = mock_list.call_args.args[1]
        assert filters["status"] == ["unpaid", "partially_paid"]

    def test_created_after_and_before_query_params_reach_the_service(self):
        from services.billing import handler, service

        with (
            patch("services.billing.handler.get_tenant_context", return_value=_ctx(UserRole.NIGERIA_OFFICE_STAFF)),
            patch.object(service, "list_billing", return_value=([], None, False)) as mock_list,
        ):
            resp = handler.lambda_handler(
                self._event({"created_after": "2026-09-01", "created_before": "2026-09-07"}),
                None,
            )

        assert resp["statusCode"] == 200
        filters = mock_list.call_args.args[1]
        assert filters["created_after"] == "2026-09-01"
        assert filters["created_before"] == "2026-09-07"

    def test_no_date_filters_when_query_params_absent(self):
        from services.billing import handler, service

        with (
            patch("services.billing.handler.get_tenant_context", return_value=_ctx(UserRole.NIGERIA_OFFICE_STAFF)),
            patch.object(service, "list_billing", return_value=([], None, False)) as mock_list,
        ):
            resp = handler.lambda_handler(self._event(), None)

        assert resp["statusCode"] == 200
        filters = mock_list.call_args.args[1]
        assert "created_after" not in filters
        assert "created_before" not in filters

    def test_search_query_param_reaches_the_service(self):
        # Regression: the ?q= search param from BillingList was silently dropped
        # by the handler, so the search box never did anything.
        from services.billing import handler, service

        with (
            patch("services.billing.handler.get_tenant_context", return_value=_ctx(UserRole.NIGERIA_OFFICE_STAFF)),
            patch.object(service, "list_billing", return_value=([], None, False)) as mock_list,
        ):
            resp = handler.lambda_handler(self._event({"q": "INV-2026"}), None)

        assert resp["statusCode"] == 200
        filters = mock_list.call_args.args[1]
        assert filters["q"] == "INV-2026"


class TestHandlePaymentDueNotification:
    """Ground-truth gap found live, reported by the user (while investigating
    a separate missing notification on payment-claim rejection — the user
    then asked to check every notification in the app): handle_payment_due
    creates a real invoice and publishes PaymentDue to EventBridge, but that
    event was never routed anywhere and enqueue_notifications was never
    called — a customer's invoice appeared with zero notification, ever."""

    def _mock_repo(self, **overrides):
        from services.billing import service

        defaults = dict(
            get_tenant_config_value=lambda tid, key: (
                {"address": "12 Warehouse Rd", "city": "Lagos", "state": "Lagos"} if key == "warehouse_address" else None
            ),
            get_cbm_and_carton_totals=lambda *a: {"total_cbm": Decimal("5.0"), "total_cartons": 10},
            get_cbm_by_package_type=lambda *a: {"carton": Decimal("5.0")},
            get_outstanding_carryovers=lambda *a: [],
            get_pending_credit_refunds=lambda *a: [],
            get_tenant_short=lambda tid: "ACM",
            get_next_invoice_seq=lambda tid: 1,
            create_billing=lambda tid, data: {**data, "id": "billing-001"},
            mark_carryovers_applied=lambda *a: None,
            mark_credit_refunds_applied=lambda *a: None,
            get_customer_contact=lambda tid, cid: {
                "id": cid,
                "name": "Ngozi",
                "phone": "+2348012345678",
                "email": "n@x.com",
                "whatsapp": None,
                "locale": "en",
            },
        )
        defaults.update(overrides)
        patchers = [patch.object(service.repo, name, side_effect=fn) for name, fn in defaults.items()]
        # Dollar rate is no longer read off tenant_config — it's the Bybit
        # base rate + tenant markup (shared/fx_rate.py); CBM rate is now
        # currency + carton/bag/bale rates (shared/cbm_rate.py). Both are
        # imported directly into service's namespace rather than living on
        # service.repo.
        patchers.append(patch.object(service, "get_effective_dollar_rate", return_value={"rate": Decimal("1550")}))
        patchers.append(
            patch.object(
                service,
                "get_cbm_rate_config",
                return_value={
                    "currency": "usd",
                    "rate_mode": "flat",
                    "carton_rate": Decimal("45"),
                    "bag_rate": Decimal("45"),
                    "bale_rate": Decimal("45"),
                },
            )
        )
        for p in patchers:
            p.start()
        return patchers

    def test_creating_billing_notifies_the_customer(self):
        from services.billing import service

        patchers = self._mock_repo()
        try:
            with (
                patch("services.billing.service.publish_event"),
                patch("services.billing.service.enqueue_notifications") as mock_notify,
            ):
                service.handle_payment_due(TENANT_ID, "container-001", "customer-001", "ACME001")
        finally:
            for p in patchers:
                p.stop()

        mock_notify.assert_called_once()
        assert mock_notify.call_args.kwargs["event_type"] == "payment_due"
        assert mock_notify.call_args.kwargs["recipient"]["phone"] == "+2348012345678"
        assert mock_notify.call_args.kwargs["template_data"]["container_number"] == "ACME001"
        assert mock_notify.call_args.kwargs["template_data"]["warehouse_address"] == "12 Warehouse Rd, Lagos, Lagos"
        assert mock_notify.call_args.kwargs["customer_id"] == "customer-001"

    def test_a_notification_failure_does_not_fail_billing_creation(self):
        from services.billing import service

        patchers = self._mock_repo(get_customer_contact=lambda *a: (_ for _ in ()).throw(RuntimeError("db down")))
        try:
            with patch("services.billing.service.publish_event"):
                # Must not raise despite the notification lookup failing.
                service.handle_payment_due(TENANT_ID, "container-001", "customer-001", "ACME001")
        finally:
            for p in patchers:
                p.stop()

    def test_no_notification_when_customer_contact_is_missing(self):
        from services.billing import service

        patchers = self._mock_repo(get_customer_contact=lambda *a: None)
        try:
            with (
                patch("services.billing.service.publish_event"),
                patch("services.billing.service.enqueue_notifications") as mock_notify,
            ):
                service.handle_payment_due(TENANT_ID, "container-001", "customer-001", "ACME001")
        finally:
            for p in patchers:
                p.stop()

        mock_notify.assert_not_called()

    def test_creating_billing_also_notifies_the_customer_in_app_when_they_have_a_portal_account(self):
        """Ground-truth follow-up, reported live by the user: SMS/WhatsApp/
        email can each fail for reasons entirely outside this app, and the
        customer portal itself showed nothing at all until they happened to
        open the specific billing record."""
        from services.billing import service

        patchers = self._mock_repo(
            get_customer_contact=lambda tid, cid: {
                "id": cid,
                "user_id": "portal-user-001",
                "name": "Ngozi",
                "phone": "+2348012345678",
                "email": "n@x.com",
                "whatsapp": None,
                "locale": "en",
            },
        )
        try:
            with (
                patch("services.billing.service.publish_event"),
                patch("services.billing.service.enqueue_notifications"),
                patch("services.billing.service.notify_staff") as mock_notify_staff,
            ):
                service.handle_payment_due(TENANT_ID, "container-001", "customer-001", "ACME001")
        finally:
            for p in patchers:
                p.stop()

        mock_notify_staff.assert_called_once()
        assert mock_notify_staff.call_args.kwargs["target_user_id"] == "portal-user-001"
        assert mock_notify_staff.call_args.kwargs["event_type"] == "payment_due"

    def test_no_in_app_notification_for_a_customer_with_no_portal_account(self):
        from services.billing import service

        patchers = self._mock_repo()  # default get_customer_contact has no "user_id" key
        try:
            with (
                patch("services.billing.service.publish_event"),
                patch("services.billing.service.enqueue_notifications"),
                patch("services.billing.service.notify_staff") as mock_notify_staff,
            ):
                service.handle_payment_due(TENANT_ID, "container-001", "customer-001", "ACME001")
        finally:
            for p in patchers:
                p.stop()

        mock_notify_staff.assert_not_called()


class TestRejectDisputeAuditLogging:
    """Ground-truth gap found while auditing log coverage: every other CBM
    dispute status transition (acknowledge/escalate/resolve) writes an
    audit_log entry — reject was the one silently missing, so a tenant
    admin's activity view had no record a dispute was ever rejected."""

    def test_reject_dispute_writes_audit_entry(self):
        from services.billing import service

        dispute = {"id": "dispute-1", "billing_id": "billing-1", "status": "submitted"}
        updated = {**dispute, "status": "rejected"}

        with (
            patch.object(service.repo, "get_cbm_dispute_by_id", return_value=dispute),
            patch.object(service.repo, "set_dispute_status", return_value=updated),
            patch("services.billing.service.log_audit") as mock_audit,
        ):
            service.reject_dispute(
                TENANT_ID,
                "dispute-1",
                "Insufficient evidence",
                actor_id="staff-1",
                ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF),
            )

        assert mock_audit.call_args.kwargs["entity_type"] == "cbm_dispute"
        assert mock_audit.call_args.kwargs["action"] == "STATUS_CHANGE"
        assert mock_audit.call_args.kwargs["after_state"]["status"] == "rejected"


class TestFileCbmDisputeNotifiesStaff:
    """Ground-truth follow-up to the payment-claim-rejection notification
    bug — a newly filed CBM dispute previously had no in-app signal for
    staff at all, only reachable by navigating to the disputes list."""

    def test_filing_notifies_nigeria_staff_and_admin(self):
        from services.billing import service

        billing = _billing(customer_id="customer-001", total_cbm=Decimal("10.0"))
        req = type("Req", (), {"customer_measured_cbm": Decimal("9.0"), "reason": "Measured less on arrival"})()

        with (
            patch.object(service.repo, "get_billing_by_id", return_value=billing),
            patch.object(service.repo, "get_customer_by_user_id", return_value={"id": "customer-001"}),
            patch.object(service.repo, "get_active_disputes", return_value=[]),
            patch.object(
                service.repo,
                "create_cbm_dispute",
                return_value={"id": "dispute-1", "billing_id": "billing-1", "status": "open"},
            ),
            patch("services.billing.service.notify_staff") as mock_notify,
        ):
            service.file_cbm_dispute(
                TENANT_ID,
                "billing-1",
                req,
                actor_id="customer-1",
                ctx=_ctx(UserRole.CUSTOMER),
            )

        assert mock_notify.call_count == 2
        roles = {c.kwargs["target_role"] for c in mock_notify.call_args_list}
        assert roles == {"nigeria_office_staff", "tenant_admin"}
        assert all(c.kwargs["event_type"] == "cbm_dispute_filed" for c in mock_notify.call_args_list)
        assert all(c.kwargs["entity_id"] == "dispute-1" for c in mock_notify.call_args_list)


class TestTenantReport:
    """GET /v1/billing/report service delegation (SQL aggregation lives in the repo)."""

    def test_delegates_range_to_repo(self):
        from services.billing import service

        stub = {
            "overview": {"total_revenue_ngn": "54334962.00"},
            "claims": {},
            "top_customers": [],
            "container_billing": [],
            "container_pipeline": [],
        }
        with patch.object(service.repo, "get_tenant_report", return_value=stub) as m:
            result = service.get_tenant_report(TENANT_ID, created_after="2026-01-01", created_before="2026-01-31")
        assert m.call_args[0][0] == TENANT_ID
        assert m.call_args[0][1] == "2026-01-01"
        assert result["overview"]["total_revenue_ngn"] == "54334962.00"
