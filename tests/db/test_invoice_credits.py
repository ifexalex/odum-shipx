"""Credits and the zero floor on an invoice total, against a real database (audit BE-07, migration 066).

The unit tests pin the arithmetic and the SQL text; these run the statements: a credit used in part stays the
customer's, two invoices cannot spend the same credit, the table refuses a negative total, and a reduction past zero
stops at zero and opens a refund for the rest.

Skipped when no database is reachable.
"""

import uuid
from decimal import Decimal

import psycopg2
import pytest

from tests.db.support import INVOICE_PREFIX, _invoice_data, _make_invoice, _rows

pytestmark = pytest.mark.db


def _make_credit(admin, world, approved: str, requested: str | None = None, customer: int = 0) -> str:
    refund_id = str(uuid.uuid4())
    with admin.cursor() as cur:
        cur.execute(
            "INSERT INTO refund_request (id, tenant_id, customer_id, amount_ngn, amount_approved_ngn, reason, status, "
            "refund_type, customer_choice) VALUES (%s, %s, %s, %s, %s, 'credit', 'applied_as_credit', 'overpayment', "
            "'credit_next_shipment')",
            (refund_id, world["tenant"], world["customers"][customer], requested or approved, approved),
        )
    return refund_id


def _credit_state(admin, refund_id: str) -> tuple[str, Decimal]:
    [(status, applied)] = _rows(admin, "SELECT status, credit_applied_ngn FROM refund_request WHERE id = %s", (refund_id,))
    return status, Decimal(str(applied))


def _invoice(world, container: int, total: str, applications: list):
    from services.billing import repository as repo

    data = {**_invoice_data(world["tenant"], world["customers"][0], world["containers"][container]), "total_ngn": Decimal(total)}
    return repo.create_invoice(world["tenant"], data, INVOICE_PREFIX, [], applications)


class TestCreditsOnRealRows:
    def test_a_credit_used_in_part_stays_open_with_the_rest_and_the_invoice_records_it(self, admin, world):
        from services.billing import repository as repo

        credit = _make_credit(admin, world, "50000")
        invoice, created = _invoice(world, 0, "0", [repo.CreditApplication(credit, Decimal("0"), Decimal("20000"))])

        assert created and Decimal(str(invoice["credits_applied_ngn"])) == Decimal("20000")
        assert _credit_state(admin, credit) == ("applied_as_credit", Decimal("20000"))
        # Still listed as a credit the customer holds, with what is left worked out from the two columns.
        [pending] = repo.get_pending_credit_refunds(world["tenant"], world["customers"][0])
        assert Decimal(str(pending["amount_approved_ngn"])) - Decimal(str(pending["credit_applied_ngn"])) == Decimal("30000")

    def test_the_next_invoice_uses_the_rest_and_completes_the_credit(self, admin, world):
        from services.billing import repository as repo

        credit = _make_credit(admin, world, "50000")
        _invoice(world, 0, "0", [repo.CreditApplication(credit, Decimal("0"), Decimal("20000"))])
        _invoice(world, 1, "70000", [repo.CreditApplication(credit, Decimal("20000"), Decimal("30000"))])

        assert _credit_state(admin, credit) == ("processed", Decimal("50000"))
        assert repo.get_pending_credit_refunds(world["tenant"], world["customers"][0]) == []

    def test_two_invoices_cannot_spend_the_same_part_of_a_credit(self, admin, world):
        from services.billing import repository as repo

        credit = _make_credit(admin, world, "50000")
        stale = repo.CreditApplication(credit, Decimal("0"), Decimal("40000"))
        _invoice(world, 0, "0", [stale])
        with pytest.raises(repo.LedgerConflictError):
            _invoice(world, 1, "0", [stale])  # worked out before the first invoice took its share

        assert _credit_state(admin, credit) == ("applied_as_credit", Decimal("40000"))
        assert _rows(admin, "SELECT COUNT(*) FROM billing WHERE tenant_id = %s", (world["tenant"],))[0][0] == 1

    def test_a_credit_cannot_be_overspent_even_with_the_right_starting_point(self, admin, world):
        from services.billing import repository as repo

        credit = _make_credit(admin, world, "50000")
        with pytest.raises(repo.LedgerConflictError):
            _invoice(world, 0, "0", [repo.CreditApplication(credit, Decimal("0"), Decimal("50000.01"))])
        assert _credit_state(admin, credit) == ("applied_as_credit", Decimal("0"))

    def test_generation_with_more_credit_than_the_charge_issues_a_paid_zero_invoice(self, admin, world):
        """The brief's acceptance case end to end through `_credits_to_apply`."""
        from services.billing import repository as repo
        from services.billing import service

        credit = _make_credit(admin, world, "50000")
        applications = service._credits_to_apply(
            repo.get_pending_credit_refunds(world["tenant"], world["customers"][0]), Decimal("20000.00")
        )
        data = {
            **_invoice_data(world["tenant"], world["customers"][0], world["containers"][0], "20000.00"),
            "total_ngn": Decimal("0.00"),
            "status": "paid",
        }
        invoice, _ = repo.create_invoice(world["tenant"], data, INVOICE_PREFIX, [], applications)

        assert Decimal(str(invoice["total_ngn"])) == 0 and invoice["status"] == "paid"
        assert Decimal(str(invoice["balance_ngn"])) == 0
        assert _credit_state(admin, credit) == ("applied_as_credit", Decimal("20000"))


class TestTheTotalCannotGoBelowZero:
    def test_the_table_refuses_a_negative_total(self, admin, world):
        invoice_id = _make_invoice(admin, world)
        with pytest.raises(psycopg2.errors.CheckViolation), admin.cursor() as cur:
            cur.execute("UPDATE billing SET total_ngn = -1 WHERE id = %s", (invoice_id,))

    def test_a_reduction_past_zero_stops_at_zero_and_reports_the_total_before(self, admin, world):
        from shared.billing_money import adjust_billing

        invoice_id = _make_invoice(admin, world, total="10000.00")
        updated = adjust_billing(world["tenant"], invoice_id, Decimal("-30000"))

        assert Decimal(str(updated["total_ngn"])) == 0
        assert Decimal(str(updated["total_before_ngn"])) == Decimal("10000")
        assert updated["status"] == "paid"  # nothing owed, nothing paid

    def test_the_part_below_zero_becomes_a_refund_for_the_customer(self, admin, world):
        from shared.billing_money import adjust_billing_and_refund_overpayment
        from shared.db import tenant_transaction

        invoice_id = _make_invoice(admin, world, total="10000.00")
        with tenant_transaction(world["tenant"]):
            _, refunded = adjust_billing_and_refund_overpayment(world["tenant"], invoice_id, Decimal("-30000"), "CBM corrected")

        assert refunded == Decimal("20000")
        [(amount, status)] = _rows(admin, "SELECT amount_ngn, status FROM refund_request WHERE billing_id = %s", (invoice_id,))
        assert Decimal(str(amount)) == Decimal("20000") and status == "pending_review"

    def test_an_ordinary_reduction_and_a_charge_behave_as_before(self, admin, world):
        from shared.billing_money import adjust_billing

        invoice_id = _make_invoice(admin, world, total="10000.00")
        assert Decimal(str(adjust_billing(world["tenant"], invoice_id, Decimal("-3000"))["total_ngn"])) == Decimal("7000")
        charged = adjust_billing(world["tenant"], invoice_id, Decimal("500"), misc_delta=Decimal("500"))
        assert Decimal(str(charged["total_ngn"])) == Decimal("7500") and charged["status"] == "unpaid"

    def test_the_constraint_is_in_place_and_validated_on_a_clean_database(self, admin):
        [(validated,)] = _rows(
            admin, "SELECT convalidated FROM pg_constraint WHERE conname = %s", ("ck_billing_total_not_negative",)
        )
        assert validated is True


class TestCancelGivesBackWhatTheInvoiceTook:
    """Migration 070: cancelling an invoice returns the credit it used and reopens the balances it carried over."""

    def test_the_credit_comes_back_and_the_next_invoice_can_use_it(self, admin, world):
        from services.billing import repository as repo

        credit = _make_credit(admin, world, "20000")
        invoice, _ = _invoice(world, 0, "5000", [repo.CreditApplication(credit, Decimal("0"), Decimal("20000"))])
        assert _credit_state(admin, credit) == ("processed", Decimal("20000"))
        [application] = repo.get_credit_applications(world["tenant"], str(invoice["id"]))
        assert Decimal(str(application["amount_ngn"])) == Decimal("20000")

        cancelled = repo.cancel_billing(world["tenant"], str(invoice["id"]), world["user"], "Wrong container")

        assert cancelled is not None and cancelled.row["status"] == "cancelled"
        assert cancelled.credits_restored == [(credit, Decimal("20000.00"))]
        assert _credit_state(admin, credit) == ("applied_as_credit", Decimal("0"))
        assert repo.get_credit_applications(world["tenant"], str(invoice["id"])) == []
        [(reversed_at,)] = _rows(
            admin, "SELECT reversed_at FROM billing_credit_application WHERE billing_id = %s", (str(invoice["id"]),)
        )
        assert reversed_at is not None

        # The container can be invoiced again (the cancelled invoice is not live), and the credit is spendable.
        again, created = _invoice(world, 0, "5000", [repo.CreditApplication(credit, Decimal("0"), Decimal("20000"))])
        assert created and again["id"] != invoice["id"]
        assert _credit_state(admin, credit) == ("processed", Decimal("20000"))

    def test_a_credit_used_in_part_gets_back_only_what_this_invoice_took(self, admin, world):
        from services.billing import repository as repo

        credit = _make_credit(admin, world, "50000")
        first, _ = _invoice(world, 0, "100", [repo.CreditApplication(credit, Decimal("0"), Decimal("20000"))])
        _invoice(world, 1, "100", [repo.CreditApplication(credit, Decimal("20000"), Decimal("30000"))])
        assert _credit_state(admin, credit) == ("processed", Decimal("50000"))

        repo.cancel_billing(world["tenant"], str(first["id"]), world["user"], "Duplicate")

        assert _credit_state(admin, credit) == ("applied_as_credit", Decimal("30000"))

    def test_a_carried_over_balance_is_outstanding_again(self, admin, world):
        from services.billing import repository as repo

        source, _ = _invoice(world, 1, "8000", [])
        carryover = str(uuid.uuid4())
        with admin.cursor() as cur:
            cur.execute(
                "INSERT INTO carryover_ledger (id, tenant_id, customer_id, source_billing_id, carryover_amount_ngn) "
                "VALUES (%s, %s, %s, %s, 8000)",
                (carryover, world["tenant"], world["customers"][0], str(source["id"])),
            )
        data = {**_invoice_data(world["tenant"], world["customers"][0], world["containers"][0]), "total_ngn": Decimal("108000")}
        target, _ = repo.create_invoice(world["tenant"], data, INVOICE_PREFIX, [carryover], [])
        assert _rows(admin, "SELECT status FROM carryover_ledger WHERE id = %s", (carryover,)) == [("applied",)]

        cancelled = repo.cancel_billing(world["tenant"], str(target["id"]), world["user"], "Wrong rate")

        assert cancelled.carryovers_reopened == [carryover]
        [(status, target_id, applied_at)] = _rows(
            admin, "SELECT status, target_billing_id, applied_at FROM carryover_ledger WHERE id = %s", (carryover,)
        )
        assert (status, target_id, applied_at) == ("outstanding", None, None)

    def test_a_paid_invoice_is_not_cancelled_and_nothing_is_given_back(self, admin, world):
        from services.billing import repository as repo

        credit = _make_credit(admin, world, "20000")
        invoice, _ = _invoice(world, 0, "5000", [repo.CreditApplication(credit, Decimal("0"), Decimal("20000"))])
        with admin.cursor() as cur:
            cur.execute(
                "UPDATE billing SET status = 'paid', amount_paid_ngn = 5000 WHERE id = %s",
                (str(invoice["id"]),),
            )

        assert repo.cancel_billing(world["tenant"], str(invoice["id"]), world["user"], "x") is None
        assert _credit_state(admin, credit) == ("processed", Decimal("20000"))
        assert len(repo.get_credit_applications(world["tenant"], str(invoice["id"]))) == 1

    def test_another_tenant_cannot_see_the_applications(self, admin, world):
        from services.billing import repository as repo

        credit = _make_credit(admin, world, "20000")
        invoice, _ = _invoice(world, 0, "5000", [repo.CreditApplication(credit, Decimal("0"), Decimal("1000"))])
        assert repo.get_credit_applications(str(uuid.uuid4()), str(invoice["id"])) == []
