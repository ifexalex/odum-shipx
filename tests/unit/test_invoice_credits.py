"""An invoice never goes below zero, and a credit is spent only as far as it is needed (audit BE-07).

Before: generation subtracted every credit the customer held, whole. More credit than the invoice came to gave a
negative total and marked all of it used, so the difference was kept for nobody.
"""

from contextlib import ExitStack, contextmanager
from decimal import Decimal
from unittest.mock import patch

import pytest

from services.billing import repository as repo
from services.billing import service
from shared import billing_money

TENANT = "11111111-1111-1111-1111-111111111111"
CUSTOMER = "22222222-2222-2222-2222-222222222222"
CONTAINER = "33333333-3333-3333-3333-333333333333"


def _credit(refund_id: str, requested: str, approved: str | None = None, used: str = "0") -> dict:
    return {
        "id": refund_id,
        "amount_ngn": Decimal(requested),
        "amount_approved_ngn": Decimal(approved) if approved is not None else None,
        "credit_applied_ngn": Decimal(used),
    }


class TestCreditsToApply:
    def test_a_credit_larger_than_what_is_due_is_used_only_as_far_as_needed(self):
        [application] = service._credits_to_apply([_credit("r1", "50000", "50000")], Decimal("30000.00"))
        assert application == repo.CreditApplication("r1", Decimal("0"), Decimal("30000.00"))

    def test_credits_are_used_oldest_first_and_the_rest_are_left_whole(self):
        credits = [_credit("old", "10000", "10000"), _credit("mid", "10000", "10000"), _credit("new", "10000", "10000")]
        applications = service._credits_to_apply(credits, Decimal("15000.00"))
        assert [(a.refund_id, a.amount_ngn) for a in applications] == [("old", Decimal("10000")), ("mid", Decimal("5000.00"))]

    def test_a_credit_is_worth_what_was_approved_not_what_was_asked_for(self):
        # Asked for 50,000, approved 20,000. The old sum took the 50,000.
        [application] = service._credits_to_apply([_credit("r1", "50000", "20000")], Decimal("100000.00"))
        assert application.amount_ngn == Decimal("20000")

    def test_what_earlier_invoices_used_is_not_spent_again(self):
        [application] = service._credits_to_apply([_credit("r1", "50000", "50000", used="30000")], Decimal("100000.00"))
        assert application == repo.CreditApplication("r1", Decimal("30000"), Decimal("20000"))

    def test_a_used_up_credit_is_skipped(self):
        credits = [_credit("spent", "5000", "5000", used="5000"), _credit("r2", "8000", "8000")]
        assert [a.refund_id for a in service._credits_to_apply(credits, Decimal("1000.00"))] == ["r2"]

    def test_an_unapproved_amount_falls_back_to_the_requested_one(self):
        [application] = service._credits_to_apply([_credit("r1", "7000")], Decimal("100000.00"))
        assert application.amount_ngn == Decimal("7000")

    @pytest.mark.parametrize("due", ["0", "-5"])
    def test_nothing_due_uses_no_credit(self, due):
        assert service._credits_to_apply([_credit("r1", "7000", "7000")], Decimal(due)) == []


def _generate(credits: list[dict], carryovers: list[dict] | None = None) -> tuple[dict, list, list]:
    """Runs invoice generation for 2 CBM at $10 and ₦1,000/$ (a ₦20,000 charge). Returns the invoice data, the
    credit applications handed to the repository and the audit calls."""
    captured: dict = {}
    applications: list = []

    def _create_invoice(tid, data, number_prefix, carryover_ids, credit_applications):
        captured.update(data)
        applications.extend(credit_applications)
        return {**data, "id": "billing-001", "invoice_number": f"{number_prefix}-0001"}, True

    cbm_config = {
        "rate_mode": "flat",
        "currency": "usd",
        "carton_rate": Decimal("10"),
        "bag_rate": Decimal("10"),
        "bale_rate": Decimal("10"),
        "effective_from": "",
    }
    with ExitStack() as stack:
        for name, value in {
            "get_live_invoice": None,
            "get_cbm_and_carton_totals": {"total_cbm": Decimal("2"), "total_cartons": 4},
            "get_cbm_by_package_type": {"carton": Decimal("2")},
            "get_outstanding_carryovers": carryovers or [],
            "get_pending_credit_refunds": credits,
            "get_tenant_short": "ACM",
            "get_customer_contact": None,
        }.items():
            stack.enter_context(patch.object(service.repo, name, return_value=value))
        stack.enter_context(patch.object(service.repo, "create_invoice", side_effect=_create_invoice))
        stack.enter_context(patch.object(service, "get_cbm_rate_config", return_value=cbm_config))
        stack.enter_context(patch.object(service, "get_effective_dollar_rate", return_value={"rate": Decimal("1000")}))
        stack.enter_context(patch.object(service, "publish_event"))
        audit = stack.enter_context(patch.object(service, "log_audit"))
        outcome = service.handle_payment_due(TENANT, CONTAINER, CUSTOMER, "ACME001")
    assert outcome.status == "created"
    return captured, applications, audit.call_args_list


class TestInvoiceGenerationWithCredits:
    def test_credits_larger_than_the_charge_give_a_zero_invoice_and_keep_the_rest(self):
        # The brief's acceptance case: ₦20,000 charge, ₦50,000 credit.
        invoice, applications, _ = _generate([_credit("r1", "50000", "50000")])

        assert invoice["total_ngn"] == Decimal("0.00")
        assert applications == [repo.CreditApplication("r1", Decimal("0"), Decimal("20000.00"))]
        # ₦30,000 of the credit is not taken: it stays with the customer for the next invoice.
        assert Decimal("50000") - applications[0].amount_ngn == Decimal("30000.00")

    def test_an_invoice_with_nothing_left_to_pay_is_issued_as_paid(self):
        invoice, _, _ = _generate([_credit("r1", "50000", "50000")])
        assert invoice["status"] == "paid"

    def test_an_invoice_with_something_left_to_pay_is_unpaid(self):
        invoice, applications, _ = _generate([_credit("r1", "5000", "5000")])
        assert invoice["status"] == "unpaid" and invoice["total_ngn"] == Decimal("15000.00")
        assert applications == [repo.CreditApplication("r1", Decimal("0"), Decimal("5000"))]

    def test_no_credit_changes_nothing(self):
        invoice, applications, _ = _generate([])
        assert invoice["total_ngn"] == Decimal("20000.00") and invoice["status"] == "unpaid" and applications == []

    def test_a_carryover_is_owed_before_credit_is_counted(self):
        # ₦20,000 charge + ₦10,000 carried debt = ₦30,000 due; a ₦25,000 credit leaves ₦5,000.
        invoice, applications, _ = _generate(
            [_credit("r1", "25000", "25000")], carryovers=[{"id": "c1", "carryover_amount_ngn": Decimal("10000")}]
        )
        assert invoice["total_ngn"] == Decimal("5000.00") and applications[0].amount_ngn == Decimal("25000")

    def test_the_total_is_never_negative_whatever_the_credits(self):
        invoice, _, _ = _generate([_credit("a", "999999", "999999"), _credit("b", "999999", "999999")])
        assert invoice["total_ngn"] >= 0

    def test_the_audit_entry_says_which_credits_were_used_and_by_how_much(self):
        _, _, audit_calls = _generate([_credit("r1", "50000", "50000")])
        after = audit_calls[0].kwargs["after_state"]
        assert after["credits_applied_ngn"] == "20000.00" and after["status"] == "paid"
        assert after["credits_applied"] == [{"refund_id": "r1", "amount_ngn": "20000.00"}]


class _Cursor:
    """Records what `create_invoice` runs and answers each statement with one row."""

    def __init__(self, credit_update_matches: bool = True) -> None:
        self.statements: list[tuple[str, object]] = []
        self._credit_update_matches = credit_update_matches
        self._last = ""

    def execute(self, sql: str, params: object = None) -> None:
        self.statements.append((" ".join(sql.split()), params))
        self._last = sql

    def fetchone(self) -> dict | None:
        if "SELECT * FROM billing" in self._last:
            return None  # no live invoice yet
        if "UPDATE refund_request" in self._last:
            return {"id": "r1"} if self._credit_update_matches else None
        return {"id": "billing-001", "last_value": 1}

    def fetchall(self) -> list:
        return []


def _create_invoice(cursor: _Cursor, applications: list[repo.CreditApplication]) -> tuple[dict, bool]:
    @contextmanager
    def _transaction(_tenant_id):
        yield cursor

    data = {"customer_id": CUSTOMER, "container_id": CONTAINER, "total_ngn": Decimal("0")}
    with (
        patch.object(repo, "tenant_transaction", _transaction),
        patch.object(repo, "next_tenant_counter", return_value=1),
    ):
        return repo.create_invoice(TENANT, data, "ACM-INV-20261117", [], applications)


class TestCreateInvoiceSpendsCredit:
    APPLICATION = repo.CreditApplication("r1", Decimal("30000"), Decimal("20000"))

    def _credit_statement(self, cursor: _Cursor) -> tuple[str, dict]:
        [(sql, params)] = [s for s in cursor.statements if s[0].startswith("UPDATE refund_request")]
        return sql, params

    def test_it_adds_what_the_invoice_used_instead_of_marking_the_credit_spent(self):
        cursor = _Cursor()
        _create_invoice(cursor, [self.APPLICATION])
        sql, params = self._credit_statement(cursor)
        assert "SET credit_applied_ngn = credit_applied_ngn + %(amount)s" in sql
        assert params == {"tenant_id": TENANT, "id": "r1", "amount": Decimal("20000"), "applied_before": Decimal("30000")}

    def test_the_credit_is_processed_only_once_it_is_used_up(self):
        cursor = _Cursor()
        _create_invoice(cursor, [self.APPLICATION])
        sql, _ = self._credit_statement(cursor)
        assert (
            "WHEN credit_applied_ngn + %(amount)s >= COALESCE(amount_approved_ngn, amount_ngn) THEN 'processed' ELSE status"
            in sql
        )

    def test_it_only_writes_if_nobody_else_spent_the_credit_meanwhile(self):
        cursor = _Cursor()
        _create_invoice(cursor, [self.APPLICATION])
        sql, _ = self._credit_statement(cursor)
        assert "tenant_id = %(tenant_id)s" in sql and "status = 'applied_as_credit'" in sql
        assert "credit_applied_ngn = %(applied_before)s" in sql
        assert "credit_applied_ngn + %(amount)s <= COALESCE(amount_approved_ngn, amount_ngn)" in sql
        assert sql.endswith("RETURNING id")

    def test_a_credit_spent_by_another_request_fails_the_whole_invoice(self):
        with pytest.raises(repo.LedgerConflictError):
            _create_invoice(_Cursor(credit_update_matches=False), [self.APPLICATION])

    def test_the_invoice_records_the_credit_it_absorbed(self):
        cursor = _Cursor()
        _create_invoice(cursor, [self.APPLICATION, repo.CreditApplication("r2", Decimal("0"), Decimal("500.50"))])
        [(sql, params)] = [s for s in cursor.statements if s[0].startswith("INSERT INTO billing (")]
        assert "credits_applied_ngn" in sql and params["credits_applied_ngn"] == Decimal("20500.50")

    def test_each_credit_used_is_recorded_against_the_invoice(self):
        """What cancelling the invoice gives back (migration 070)."""
        cursor = _Cursor()
        _create_invoice(cursor, [self.APPLICATION, repo.CreditApplication("r2", Decimal("0"), Decimal("500.50"))])
        recorded = [p for sql, p in cursor.statements if sql.startswith("INSERT INTO billing_credit_application")]
        assert recorded == [
            {"tenant_id": TENANT, "billing_id": "billing-001", "refund_id": "r1", "amount": Decimal("20000")},
            {"tenant_id": TENANT, "billing_id": "billing-001", "refund_id": "r2", "amount": Decimal("500.50")},
        ]

    def test_no_credits_means_no_credit_statement_and_zero_recorded(self):
        cursor = _Cursor()
        _create_invoice(cursor, [])
        assert not [s for s in cursor.statements if s[0].startswith("UPDATE refund_request")]
        [(_, params)] = [s for s in cursor.statements if s[0].startswith("INSERT INTO billing (")]
        assert params["credits_applied_ngn"] == Decimal("0")


class TestAdjustBillingStopsAtZero:
    def _sql(self) -> str:
        with patch.object(billing_money, "execute_write_with_tenant", return_value={"id": "b"}) as write:
            billing_money.adjust_billing(TENANT, "b", Decimal("-5"))
        return " ".join(write.call_args.args[1].split())

    def test_the_total_is_floored_at_zero(self):
        assert "SET total_ngn = GREATEST(b.total_ngn + %(total_delta)s, 0)" in self._sql()

    def test_the_status_is_worked_out_from_the_floored_total(self):
        sql = self._sql()
        assert "ABS(GREATEST(b.total_ngn + %(total_delta)s, 0) - b.amount_paid_ngn) <= %(tol)s THEN 'paid'" in sql
        assert "GREATEST(b.total_ngn + %(total_delta)s, 0) - b.amount_paid_ngn < -%(tol)s THEN 'overpaid'" in sql

    def test_it_returns_the_total_from_before_the_change_and_stays_tenant_scoped(self):
        sql = self._sql()
        assert "RETURNING b.*, before.total_ngn AS total_before_ngn" in sql
        assert sql.count("tenant_id = %(tenant_id)s") == 2  # the locking read and the update


class TestOverpaymentPastZero:
    """A reduction that would take the total below zero: the part below zero was paid by credit and is owed back."""

    @staticmethod
    def _after(total: str, paid: str, before: str) -> dict:
        return {"total_ngn": Decimal(total), "amount_paid_ngn": Decimal(paid), "total_before_ngn": Decimal(before)}

    def test_the_part_below_zero_is_owed_to_the_customer(self):
        # ₦10,000 left after credit, nothing paid in cash, charge reduced by ₦30,000: the invoice stops at 0 and
        # ₦20,000 is owed back.
        assert billing_money.new_overpayment(self._after("0", "0", "10000"), Decimal("-30000")) == Decimal("20000")

    def test_cash_paid_and_the_part_below_zero_are_both_owed(self):
        assert billing_money.new_overpayment(self._after("0", "4000", "10000"), Decimal("-30000")) == Decimal("24000")

    def test_a_reduction_that_stays_above_zero_is_unchanged(self):
        assert billing_money.new_overpayment(self._after("7000", "0", "10000"), Decimal("-3000")) == Decimal("0")
        assert billing_money.new_overpayment(self._after("7000", "9000", "10000"), Decimal("-3000")) == Decimal("2000")

    def test_an_earlier_overpayment_is_not_refunded_twice(self):
        # Already ₦5,000 overpaid before the change; only the new ₦3,000 counts.
        assert billing_money.new_overpayment(self._after("7000", "15000", "10000"), Decimal("-3000")) == Decimal("3000")

    def test_a_row_without_the_before_total_is_read_as_before(self):
        row = {"total_ngn": Decimal("7000"), "amount_paid_ngn": Decimal("9000")}
        assert billing_money.new_overpayment(row, Decimal("-3000")) == Decimal("2000")

    def test_a_charge_never_counts_as_an_overpayment(self):
        assert billing_money.new_overpayment(self._after("15000", "0", "10000"), Decimal("5000")) == Decimal("0")


class TestInvoiceShowsTheCredit:
    def test_the_credit_absorbed_is_the_invoice_adjustment(self):
        row = {
            "id": "b1",
            "customer_id": CUSTOMER,
            "container_id": CONTAINER,
            "total_cbm": Decimal("2"),
            "cbm_rate_usd": Decimal("10"),
            "exchange_rate_ngn": Decimal("1000"),
            "subtotal_usd": Decimal("20"),
            "subtotal_ngn": Decimal("20000"),
            "total_ngn": Decimal("5000"),
            "amount_paid_ngn": Decimal("0"),
            "balance_ngn": Decimal("5000"),
            "status": "unpaid",
            "credits_applied_ngn": Decimal("15000.00"),
        }
        with ExitStack() as stack:
            for name in ("get_misc_charges", "get_payment_records", "get_applied_carryovers", "get_active_disputes"):
                stack.enter_context(patch.object(service.repo, name, return_value=[]))
            stack.enter_context(patch.object(service.repo, "get_storage_fee_total", return_value=Decimal("0")))
            enriched = service._enrich_billing(TENANT, row)
        assert enriched["adjustments_ngn"] == Decimal("-15000.00")
        # subtotal + adjustments = total: the parts add up.
        assert enriched["subtotal_ngn"] + enriched["adjustments_ngn"] == enriched["total_due_ngn"]


class _CancelCursor:
    """Answers `cancel_billing`'s statements: the invoice, the applications it reverses, the reopened carryovers."""

    def __init__(self, *, invoice: dict | None, applications: list[dict], carryovers: list[dict], credit_ok: bool = True):
        self.statements: list[tuple[str, object]] = []
        self._invoice, self._applications, self._carryovers, self._credit_ok = invoice, applications, carryovers, credit_ok
        self._last = ""

    def execute(self, sql: str, params: object = None) -> None:
        self.statements.append((" ".join(sql.split()), params))
        self._last = " ".join(sql.split())

    def fetchone(self) -> dict | None:
        if self._last.startswith("UPDATE billing SET"):
            return self._invoice
        if self._last.startswith("UPDATE refund_request"):
            return {"id": "r"} if self._credit_ok else None
        raise AssertionError(f"unexpected fetchone after {self._last[:40]}")

    def fetchall(self) -> list:
        if self._last.startswith("UPDATE billing_credit_application"):
            return self._applications
        if self._last.startswith("UPDATE carryover_ledger"):
            return self._carryovers
        raise AssertionError(f"unexpected fetchall after {self._last[:40]}")


def _cancel(cursor: _CancelCursor) -> repo.CancelledInvoice | None:
    @contextmanager
    def _transaction(_tenant_id):
        yield cursor

    with patch.object(repo, "tenant_transaction", _transaction):
        return repo.cancel_billing(TENANT, "billing-001", "u1", "Wrong container")


class TestCancelGivesBackWhatTheInvoiceTook:
    INVOICE = {"id": "billing-001", "status": "cancelled"}

    def test_each_credit_goes_back_and_a_used_up_credit_is_usable_again(self):
        cursor = _CancelCursor(
            invoice=self.INVOICE,
            applications=[{"refund_request_id": "r1", "amount_ngn": Decimal("20000")}],
            carryovers=[],
        )
        result = _cancel(cursor)
        assert result.credits_restored == [("r1", Decimal("20000"))]
        [(sql, params)] = [s for s in cursor.statements if s[0].startswith("UPDATE refund_request")]
        assert "SET credit_applied_ngn = credit_applied_ngn - %(amount)s" in sql
        assert "WHEN status = 'processed' THEN 'applied_as_credit'" in sql
        assert "credit_applied_ngn >= %(amount)s" in sql and sql.endswith("RETURNING id")
        assert params == {"tenant_id": TENANT, "id": "r1", "amount": Decimal("20000")}

    def test_carried_over_balances_are_outstanding_again(self):
        cursor = _CancelCursor(invoice=self.INVOICE, applications=[], carryovers=[{"id": "c1"}, {"id": "c2"}])
        result = _cancel(cursor)
        assert result.carryovers_reopened == ["c1", "c2"]
        [(sql, params)] = [s for s in cursor.statements if s[0].startswith("UPDATE carryover_ledger")]
        assert "SET status = 'outstanding', target_billing_id = NULL, applied_at = NULL" in sql
        assert "status = 'applied'" in sql and params == (TENANT, "billing-001")

    def test_an_invoice_that_is_no_longer_unpaid_changes_nothing(self):
        cursor = _CancelCursor(
            invoice=None, applications=[{"refund_request_id": "r1", "amount_ngn": Decimal("1")}], carryovers=[]
        )
        assert _cancel(cursor) is None
        assert [s for s, _ in cursor.statements if not s.startswith("UPDATE billing SET")] == []

    def test_a_credit_that_cannot_be_given_back_rolls_everything_back(self):
        cursor = _CancelCursor(
            invoice=self.INVOICE,
            applications=[{"refund_request_id": "r1", "amount_ngn": Decimal("20000")}],
            carryovers=[],
            credit_ok=False,
        )
        with pytest.raises(repo.LedgerConflictError):
            _cancel(cursor)
