"""Invoice and payment integrity, exercised against a real database under concurrency.

Why these are not mocked
------------------------
The defects these cover only exist when two requests overlap or when a later
statement fails after an earlier one succeeded:

* two invoices created together received the same number, and the loser was
  silently never billed;
* two payments recorded together could leave a fully paid invoice marked
  ``partially_paid``;
* a payment record could be written without the matching invoice update.

A mock returns whatever the test tells it to, so none of that is visible there.
Each test below runs the real repository functions, as the real application role
(subject to row-level security), and the concurrent ones run in separate
processes because `shared.db` keeps one connection per process.

Skipped when no database is reachable, like the RLS tests; CI always has one.
"""

import os
import uuid
from decimal import Decimal

import pytest

from tests.db.support import (  # noqa: E402
    INVOICE_PREFIX,
    RECEIPT_PREFIX,
    TOLERANCE,
    _invoice_data,
    _make_invoice,
    _rows,
    _run_parallel,
    _start_soon,
    _worker_create_invoice,
    _worker_record_payment,
)

pytestmark = pytest.mark.db

# ---------------------------------------------------------------------------
# Invoice numbers and duplicate protection
# ---------------------------------------------------------------------------


class TestInvoiceCreation:
    def test_parallel_invoices_all_get_distinct_numbers(self, admin, world):
        start = _start_soon()
        jobs = [(world["tenant"], world["customers"][i], world["containers"][i], start) for i in range(12)]

        results = _run_parallel(_worker_create_invoice, jobs)

        assert all(created for _, _, created in results), "every customer must be billed"
        numbers = sorted(number for _, number, _ in results)
        assert len(set(numbers)) == 12, f"duplicate invoice numbers issued: {numbers}"
        assert numbers == [f"{INVOICE_PREFIX}-{n:04d}" for n in range(1, 13)], "numbers should be contiguous with no gaps"

    def test_creating_twice_returns_the_same_invoice(self, admin, world):
        from services.billing import repository as repo

        data = _invoice_data(world["tenant"], world["customers"][0], world["containers"][0])
        first, created_first = repo.create_invoice(world["tenant"], data, INVOICE_PREFIX, [], [])
        second, created_second = repo.create_invoice(world["tenant"], data, INVOICE_PREFIX, [], [])

        assert created_first is True
        assert created_second is False
        assert first["id"] == second["id"]
        assert _rows(admin, "SELECT COUNT(*) FROM billing WHERE tenant_id = %s", (world["tenant"],))[0][0] == 1
        # The no-op consumed no number, so the next invoice is 0002, not 0003.
        nxt, _ = repo.create_invoice(
            world["tenant"], _invoice_data(world["tenant"], world["customers"][1], world["containers"][1]), INVOICE_PREFIX, [], []
        )
        assert nxt["invoice_number"] == f"{INVOICE_PREFIX}-0002"

    def test_parallel_requests_for_one_customer_create_exactly_one_invoice(self, admin, world):
        start = _start_soon()
        jobs = [(world["tenant"], world["customers"][0], world["containers"][0], start)] * 6

        results = _run_parallel(_worker_create_invoice, jobs)

        assert sum(1 for _, _, created in results if created) == 1
        assert len({invoice_id for invoice_id, _, _ in results}) == 1
        assert _rows(admin, "SELECT COUNT(*) FROM billing WHERE tenant_id = %s", (world["tenant"],))[0][0] == 1
        counter = _rows(
            admin, "SELECT last_value FROM tenant_counter WHERE tenant_id = %s AND name = 'invoice'", (world["tenant"],)
        )
        assert counter[0][0] == 1, "losing the race must roll the number back, not leave a gap"

    def test_a_cancelled_invoice_can_be_reissued(self, admin, world):
        from services.billing import repository as repo

        first_id = _make_invoice(admin, world)
        with admin.cursor() as cur:
            cur.execute("UPDATE billing SET status = 'cancelled' WHERE id = %s", (first_id,))

        reissued, created = repo.create_invoice(
            world["tenant"], _invoice_data(world["tenant"], world["customers"][0], world["containers"][0]), INVOICE_PREFIX, [], []
        )

        assert created is True
        assert str(reissued["id"]) != first_id

    def test_a_carryover_cannot_be_applied_to_two_invoices(self, admin, world):
        from services.billing import repository as repo

        carryover_id, source_billing = str(uuid.uuid4()), str(uuid.uuid4())
        with admin.cursor() as cur:
            # The earlier invoice the carryover came from, inserted directly so it
            # does not consume a number from the counter under test.
            cur.execute(
                "INSERT INTO billing (id, tenant_id, customer_id, container_id, invoice_number, cbm_rate_usd, exchange_rate_ngn, "
                "total_ngn, amount_paid_ngn, status) VALUES (%s, %s, %s, %s, 'SRC-1', 1, 1, 1000, 1000, 'paid')",
                (source_billing, world["tenant"], world["customers"][0], world["containers"][2]),
            )
            cur.execute(
                "INSERT INTO carryover_ledger (id, tenant_id, customer_id, source_billing_id, carryover_amount_ngn, status) "
                "VALUES (%s, %s, %s, %s, 5000, 'outstanding')",
                (carryover_id, world["tenant"], world["customers"][0], source_billing),
            )

        repo.create_invoice(
            world["tenant"],
            _invoice_data(world["tenant"], world["customers"][0], world["containers"][0]),
            INVOICE_PREFIX,
            [carryover_id],
            [],
        )
        with pytest.raises(repo.LedgerConflictError):
            repo.create_invoice(
                world["tenant"],
                _invoice_data(world["tenant"], world["customers"][0], world["containers"][1]),
                INVOICE_PREFIX,
                [carryover_id],
                [],
            )

        # The source invoice plus the one that absorbed the carryover; the failed attempt left nothing.
        assert _rows(admin, "SELECT COUNT(*) FROM billing WHERE tenant_id = %s", (world["tenant"],))[0][0] == 2
        counter = _rows(
            admin, "SELECT last_value FROM tenant_counter WHERE tenant_id = %s AND name = 'invoice'", (world["tenant"],)
        )
        assert counter[0][0] == 1, "the failed attempt must not consume an invoice number"


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------


class TestPayments:
    def test_two_payments_that_together_settle_the_invoice_end_paid(self, admin, world):
        billing_id = _make_invoice(admin, world, total="100000.00")
        start = _start_soon()
        jobs = [(world["tenant"], billing_id, "50000.00", start)] * 2

        results = _run_parallel(_worker_record_payment, jobs)

        row = _rows(admin, "SELECT status, amount_paid_ngn FROM billing WHERE id = %s", (billing_id,))[0]
        assert row[0] == "paid", "a fully paid invoice must not be left partially_paid"
        assert row[1] == Decimal("100000.00")
        assert len({receipt for receipt, _ in results}) == 2, "each payment needs its own receipt number"

    def test_overpayment_refunds_only_the_excess_once(self, admin, world):
        billing_id = _make_invoice(admin, world, total="100000.00")
        start = _start_soon()
        jobs = [(world["tenant"], billing_id, "60000.00", start)] * 2

        _run_parallel(_worker_record_payment, jobs)

        status = _rows(admin, "SELECT status FROM billing WHERE id = %s", (billing_id,))[0][0]
        refunds = _rows(admin, "SELECT amount_ngn FROM refund_request WHERE billing_id = %s", (billing_id,))
        assert status == "overpaid"
        assert [r[0] for r in refunds] == [Decimal("20000.00")]

    def test_a_payment_within_a_kobo_of_the_total_is_paid(self, admin, world):
        from services.payment_release import repository as repo

        billing_id = _make_invoice(admin, world, total="100000.00")
        recorded = repo.record_payment(
            world["tenant"],
            billing_id,
            Decimal("99999.99"),
            {"payment_method": "cash", "payment_date": "2026-11-14"},
            tolerance=TOLERANCE,
            receipt_prefix=RECEIPT_PREFIX,
        )

        assert recorded.billing["status"] == "paid"
        assert recorded.overpayment_ngn == Decimal("0")

    def test_a_partial_payment_is_partially_paid(self, admin, world):
        from services.payment_release import repository as repo

        billing_id = _make_invoice(admin, world, total="100000.00")
        recorded = repo.record_payment(
            world["tenant"],
            billing_id,
            Decimal("40000.00"),
            {"payment_method": "cash", "payment_date": "2026-11-14"},
            tolerance=TOLERANCE,
            receipt_prefix=RECEIPT_PREFIX,
        )

        assert recorded.billing["status"] == "partially_paid"
        assert recorded.billing["balance_ngn"] == Decimal("60000.00")

    def test_a_failed_invoice_update_leaves_no_payment_and_no_receipt_number(self, admin, world):
        """The invoice belongs to another tenant, so the UPDATE matches no row.

        The payment record is inserted first; if it were committed independently
        the books would hold a payment against nothing. Everything, including the
        receipt number, must roll back.
        """
        from services.payment_release import repository as repo

        other_tenant = str(uuid.uuid4())
        other_customer, other_container, other_billing = (str(uuid.uuid4()) for _ in range(3))
        with admin.cursor() as cur:
            cur.execute(
                "INSERT INTO tenant (id, company_name, primary_contact_email, subscription_tier, slug) "
                "VALUES (%s, 'Other Ltd', 'other@example.test', 'starter', %s)",
                (other_tenant, f"other-{other_tenant[:8]}"),
            )
            cur.execute("INSERT INTO customer (id, tenant_id, name) VALUES (%s, %s, 'Other')", (other_customer, other_tenant))
            cur.execute(
                "INSERT INTO container (id, tenant_id, container_number) VALUES (%s, %s, 'OTH0001')",
                (other_container, other_tenant),
            )
            cur.execute(
                "INSERT INTO billing (id, tenant_id, customer_id, container_id, invoice_number, cbm_rate_usd, exchange_rate_ngn, "
                "total_ngn, status) VALUES (%s, %s, %s, %s, 'OTH-1', 1, 1, 1000, 'unpaid')",
                (other_billing, other_tenant, other_customer, other_container),
            )
        try:
            with pytest.raises(Exception):  # noqa: B017 - RLS or the guard; either way it must not commit
                repo.record_payment(
                    world["tenant"],
                    other_billing,
                    Decimal("500.00"),
                    {"payment_method": "cash", "payment_date": "2026-11-14"},
                    tolerance=TOLERANCE,
                    receipt_prefix=RECEIPT_PREFIX,
                )

            assert _rows(admin, "SELECT COUNT(*) FROM payment_record WHERE billing_id = %s", (other_billing,))[0][0] == 0
            assert (
                _rows(admin, "SELECT COUNT(*) FROM tenant_counter WHERE tenant_id = %s AND name = 'receipt'", (world["tenant"],))[
                    0
                ][0]
                == 0
            )
        finally:
            with admin.cursor() as cur:
                for table in ("payment_record", "billing", "container", "customer", "tenant_counter"):
                    cur.execute(f"DELETE FROM {table} WHERE tenant_id = %s", (other_tenant,))  # noqa: S608 - fixed table list
                cur.execute("DELETE FROM tenant WHERE id = %s", (other_tenant,))

    def test_a_repeated_gateway_delivery_is_ignored(self, admin, world):
        from services.payment_release import repository as repo

        billing_id = _make_invoice(admin, world, total="100000.00")
        kwargs = {
            "tolerance": TOLERANCE,
            "gateway_transaction_id": "gw-12345",
        }
        payment = {"payment_method": "paystack", "reference_number": "REF", "payment_date": "2026-11-14"}

        first = repo.record_payment(world["tenant"], billing_id, Decimal("100000.00"), payment, **kwargs)
        second = repo.record_payment(world["tenant"], billing_id, Decimal("100000.00"), payment, **kwargs)

        assert first is not None and first.billing["status"] == "paid"
        assert second is None
        paid = _rows(admin, "SELECT amount_paid_ngn FROM billing WHERE id = %s", (billing_id,))[0][0]
        assert paid == Decimal("100000.00"), "the duplicate delivery must not be counted again"
        assert first.payment["receipt_number"] is None, "gateway payments carry no receipt number"


class TestMigrationSeed:
    def test_the_counter_table_is_tenant_isolated(self, admin, world):
        """Another tenant's scope cannot read or advance this tenant's counter."""
        from shared.db import execute_with_tenant, next_tenant_counter, tenant_transaction

        with tenant_transaction(world["tenant"]) as cur:
            assert next_tenant_counter(cur, world["tenant"], "invoice") == 1

        stranger = str(uuid.uuid4())
        assert execute_with_tenant(stranger, "SELECT * FROM tenant_counter WHERE tenant_id = %s", (world["tenant"],)) == []
        assert os.environ.get("DATABASE_USER")  # the app role, not the owner, ran the above


# ---------------------------------------------------------------------------
# The service on top of the repositories: container-wide invoicing against real rows
# ---------------------------------------------------------------------------


class TestContainerInvoicingEndToEnd:
    """`generate_billing` through the real queries; only the rate lookups are stubbed.

    The rates come from tenant config and a live market-rate fetch, neither of which
    belongs in a database test. Everything else, including the new
    `get_container_for_billing` / `get_billable_customers_for_container` SQL, is real.
    """

    def _approved_packing_list(self, admin, world, index: int, cbm: str = "2.000") -> None:
        pl_id = str(uuid.uuid4())
        with admin.cursor() as cur:
            cur.execute(
                "INSERT INTO packing_list (id, tenant_id, container_id, customer_id, reference, status) "
                "VALUES (%s, %s, %s, %s, %s, 'approved')",
                (pl_id, world["tenant"], world["containers"][index], world["customers"][index], f"PL-{index}-{pl_id[:6]}"),
            )
            cur.execute(
                "INSERT INTO packing_list_item (packing_list_id, description, carton_tag, tracking_code, cbm) "
                "VALUES (%s, 'Goods', %s, %s, %s)",
                (pl_id, f"TAG-{index}-{pl_id[:6]}", f"TRK-{index}-{pl_id[:6]}", cbm),
            )

    def _set_status(self, admin, world, index: int, status: str) -> None:
        with admin.cursor() as cur:
            cur.execute("UPDATE container SET status = %s WHERE id = %s", (status, world["containers"][index]))

    def _generate(self, world, customer_id: str | None, rates: bool = True):
        from unittest.mock import patch

        from services.billing import service
        from services.billing.models import GenerateBillingRequest
        from shared.tenant_context import TenantContext, UserRole

        config = {
            "currency": "usd",
            "rate_mode": "flat",
            "carton_rate": Decimal("45") if rates else Decimal("0"),
            "bag_rate": Decimal("45") if rates else Decimal("0"),
            "bale_rate": Decimal("45") if rates else Decimal("0"),
            "effective_from": "",
        }
        ctx = TenantContext(tenant_id=world["tenant"], user_id=str(uuid.uuid4()), role=UserRole.NIGERIA_OFFICE_STAFF)
        req = GenerateBillingRequest(container_id=world["containers"][0], customer_id=customer_id)
        with (
            patch.object(service, "get_cbm_rate_config", return_value=config),
            patch.object(service, "get_effective_dollar_rate", return_value={"rate": Decimal("1500")}),
            patch.object(service, "publish_event"),
            patch.object(service, "log_audit"),
            patch.object(service, "_notify_customer_payment_due"),
            patch.object(service, "notify_staff") as notify,
        ):
            return service.generate_billing(world["tenant"], req, actor_id="u", ctx=ctx), notify

    def test_a_cleared_container_is_invoiced_once_and_again_is_a_no_op(self, admin, world):
        self._approved_packing_list(admin, world, 0, cbm="2.000")
        self._set_status(admin, world, 0, "cleared")

        first, _ = self._generate(world, customer_id=None)
        second, _ = self._generate(world, customer_id=None)

        assert [r["status"] for r in first["results"]] == ["created"]
        assert first["results"][0]["invoice_number"].endswith("-0001")
        assert [r["status"] for r in second["results"]] == ["existing"]
        assert _rows(admin, "SELECT COUNT(*) FROM billing WHERE tenant_id = %s", (world["tenant"],))[0][0] == 1
        # 2.000 CBM x $45 x N1,500
        assert _rows(admin, "SELECT total_ngn FROM billing WHERE tenant_id = %s", (world["tenant"],))[0][0] == Decimal(
            "135000.00"
        )

    def test_a_container_that_has_not_cleared_is_refused(self, admin, world):
        from shared.exceptions import BusinessRuleViolationError

        self._approved_packing_list(admin, world, 0)
        self._set_status(admin, world, 0, "in_transit")

        with pytest.raises(BusinessRuleViolationError) as exc:
            self._generate(world, customer_id=None)

        assert exc.value.rule_id == "CONTAINER_NOT_CLEARED"
        assert _rows(admin, "SELECT COUNT(*) FROM billing WHERE tenant_id = %s", (world["tenant"],))[0][0] == 0

    def test_missing_rates_are_reported_and_staff_are_told(self, admin, world):
        self._approved_packing_list(admin, world, 0)
        self._set_status(admin, world, 0, "cleared")

        result, notify = self._generate(world, customer_id=None, rates=False)

        assert [r["status"] for r in result["results"]] == ["skipped"]
        assert result["results"][0]["reason"] == "RATE_CONFIG_MISSING"
        assert notify.call_count == 2, "tenant admins and Nigeria staff are both told"
        assert _rows(admin, "SELECT COUNT(*) FROM billing WHERE tenant_id = %s", (world["tenant"],))[0][0] == 0

    def test_a_customer_with_no_approved_packing_list_is_refused(self, admin, world):
        from shared.exceptions import BusinessRuleViolationError

        self._approved_packing_list(admin, world, 0)
        self._set_status(admin, world, 0, "cleared")

        with pytest.raises(BusinessRuleViolationError) as exc:
            self._generate(world, customer_id=world["customers"][5])

        assert exc.value.rule_id == "CUSTOMER_NOT_ON_CONTAINER"
