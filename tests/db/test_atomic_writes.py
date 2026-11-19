"""Every multi-step money write is all-or-nothing, and safe when two requests collide.

Real Postgres, run as the application role (row-level security applies), with
separate processes for the concurrent cases. See test_money_integrity.py for the
invoice and payment paths; this file covers the rest of what moves an invoice's
total or opens a refund:

* misc charges (add, delete)
* applying a carryover
* resolving a CBM dispute (re-pricing the invoice)
* storage-fee accrual and waiver
* approving a refund
* resolving a damage claim, and compensating a seized item

For each, the questions are the same: does a failure part-way leave nothing behind,
does a second simultaneous request change nothing, and is the invoice's status
still honest afterwards. The service layer calls here are real; only the
side-effect publishers (audit log, events, notifications) are stubbed.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tests.db.support import (
    RECEIPT_PREFIX,
    TOLERANCE,
    _make_invoice,
    _rows,
    _run_parallel,
    _start_soon,
    _wait_for,
)

pytestmark = pytest.mark.db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pay(world, billing_id: str, amount: str) -> None:
    from services.payment_release import repository as repo

    repo.record_payment(
        world["tenant"],
        billing_id,
        Decimal(amount),
        {"payment_method": "cash", "payment_date": "2026-11-14"},
        tolerance=TOLERANCE,
        receipt_prefix=RECEIPT_PREFIX,
    )


def _billing(admin, billing_id: str) -> dict:
    with admin.cursor() as cur:
        cur.execute(
            "SELECT status, total_ngn, amount_paid_ngn, misc_charges_ngn, subtotal_ngn FROM billing WHERE id = %s", (billing_id,)
        )
        status, total, paid, misc, subtotal = cur.fetchone()
    return {"status": status, "total": total, "paid": paid, "misc": misc, "subtotal": subtotal}


def _refunds(admin, world, like: str | None = None) -> list[tuple]:
    sql = "SELECT amount_ngn, status, reason FROM refund_request WHERE tenant_id = %s"
    params: tuple = (world["tenant"],)
    if like:
        sql += " AND reason LIKE %s"
        params += (like,)
    return _rows(admin, sql + " ORDER BY created_at", params)


@pytest.fixture
def foreign_billing(admin):
    """An invoice that belongs to a different tenant: visible to an INSERT, not to a tenant-scoped UPDATE."""
    tenant, customer, container, billing = (str(uuid.uuid4()) for _ in range(4))
    with admin.cursor() as cur:
        cur.execute(
            "INSERT INTO tenant (id, company_name, primary_contact_email, subscription_tier, slug) "
            "VALUES (%s, 'Foreign Ltd', 'f@example.test', 'starter', %s)",
            (tenant, f"foreign-{tenant[:8]}"),
        )
        cur.execute("INSERT INTO customer (id, tenant_id, name) VALUES (%s, %s, 'F')", (customer, tenant))
        cur.execute("INSERT INTO container (id, tenant_id, container_number) VALUES (%s, %s, 'FOR0001')", (container, tenant))
        cur.execute(
            "INSERT INTO billing (id, tenant_id, customer_id, container_id, invoice_number, cbm_rate_usd, exchange_rate_ngn, "
            "total_ngn, status) VALUES (%s, %s, %s, %s, 'FOR-1', 1, 1, 1000, 'unpaid')",
            (billing, tenant, customer, container),
        )
    yield {"tenant": tenant, "billing": billing, "customer": customer, "container": container}
    with admin.cursor() as cur:
        cur.execute("DELETE FROM misc_charge WHERE billing_id = %s", (billing,))
        cur.execute("DELETE FROM storage_fee_log WHERE tenant_id = %s", (tenant,))
        for table in ("billing", "container", "customer"):
            cur.execute(f"DELETE FROM {table} WHERE tenant_id = %s", (tenant,))  # noqa: S608 - fixed table list
        cur.execute("DELETE FROM tenant WHERE id = %s", (tenant,))


# ---------------------------------------------------------------------------
# Misc charges
# ---------------------------------------------------------------------------


def _worker_delete_charge(args: tuple) -> str:
    tenant_id, charge_id, billing_id, start_at = args
    from services.billing import repository as repo

    _wait_for(start_at)
    try:
        repo.delete_misc_charge_from_billing(tenant_id, charge_id, billing_id, required_status="unpaid")
    except repo.RecordNotFound:
        return "gone"
    except repo.BillingStatusConflict:
        return "conflict"
    return "deleted"


class TestMiscCharges:
    def _charge(self, world, billing_id: str, amount: str = "5000.00") -> dict:
        from services.billing import repository as repo

        charge, _ = repo.add_misc_charge_to_billing(
            world["tenant"],
            {
                "billing_id": billing_id,
                "description": "Customs",
                "amount_ngn": Decimal(amount),
                "amount_usd": None,
                "charge_type": "other",
                "charge_type_id": None,
                "created_by": world["user"],
            },
        )
        return charge

    def test_a_charge_on_a_paid_invoice_makes_it_partially_paid_instead_of_leaving_it_paid_and_owing(self, admin, world):
        billing_id = _make_invoice(admin, world)
        _pay(world, billing_id, "100000.00")
        assert _billing(admin, billing_id)["status"] == "paid"

        self._charge(world, billing_id, "5000.00")

        after = _billing(admin, billing_id)
        assert after["status"] == "partially_paid"
        assert (after["total"], after["misc"]) == (Decimal("105000.00"), Decimal("5000.00"))

    def test_a_charge_that_cannot_reach_its_invoice_is_not_left_behind(self, admin, world, foreign_billing):
        """The invoice is another tenant's, so the total update matches nothing: the charge row must not survive."""
        from services.billing import repository as repo

        with pytest.raises(RuntimeError):
            repo.add_misc_charge_to_billing(
                world["tenant"],
                {
                    "billing_id": foreign_billing["billing"],
                    "description": "Stray",
                    "amount_ngn": Decimal("100"),
                    "amount_usd": None,
                    "charge_type": "other",
                    "charge_type_id": None,
                    "created_by": world["user"],
                },
            )

        assert _rows(admin, "SELECT COUNT(*) FROM misc_charge WHERE billing_id = %s", (foreign_billing["billing"],))[0][0] == 0

    def test_deleting_the_same_charge_twice_at_once_takes_it_off_the_total_once(self, admin, world):
        billing_id = _make_invoice(admin, world)
        charge = self._charge(world, billing_id, "5000.00")
        assert _billing(admin, billing_id)["total"] == Decimal("105000.00")

        start = _start_soon()
        results = _run_parallel(_worker_delete_charge, [(world["tenant"], str(charge["id"]), billing_id, start)] * 2)

        assert sorted(results) == ["deleted", "gone"]
        assert _billing(admin, billing_id)["total"] == Decimal("100000.00"), "the total must drop by 5000 once, not twice"

    def test_a_charge_cannot_be_removed_once_a_payment_has_arrived(self, admin, world):
        from services.billing import repository as repo

        billing_id = _make_invoice(admin, world)
        charge = self._charge(world, billing_id, "5000.00")
        _pay(world, billing_id, "40000.00")

        with pytest.raises(repo.BillingStatusConflict):
            repo.delete_misc_charge_from_billing(world["tenant"], str(charge["id"]), billing_id, required_status="unpaid")

        assert _rows(admin, "SELECT COUNT(*) FROM misc_charge WHERE billing_id = %s", (billing_id,))[0][0] == 1
        assert _billing(admin, billing_id)["total"] == Decimal("105000.00")


# ---------------------------------------------------------------------------
# Carryover
# ---------------------------------------------------------------------------


def _worker_apply_carryover(args: tuple) -> str:
    tenant_id, billing_id, carryover_id, customer_id, start_at = args
    from services.billing import repository as repo

    _wait_for(start_at)
    try:
        repo.apply_carryover_to_billing(tenant_id, billing_id, carryover_id, customer_id)
    except repo.RecordNotFound:
        return "refused"
    return "applied"


class TestCarryover:
    def _carryover(self, admin, world, customer_index: int = 0, amount: str = "5000.00") -> str:
        carryover_id, source = str(uuid.uuid4()), str(uuid.uuid4())
        with admin.cursor() as cur:
            cur.execute(
                "INSERT INTO billing (id, tenant_id, customer_id, container_id, invoice_number, cbm_rate_usd, exchange_rate_ngn, "
                "total_ngn, amount_paid_ngn, status) VALUES (%s, %s, %s, %s, %s, 1, 1, 1000, 1000, 'paid')",
                (source, world["tenant"], world["customers"][customer_index], world["containers"][5], f"SRC-{source[:6]}"),
            )
            cur.execute(
                "INSERT INTO carryover_ledger (id, tenant_id, customer_id, source_billing_id, carryover_amount_ngn, status) "
                "VALUES (%s, %s, %s, %s, %s, 'outstanding')",
                (carryover_id, world["tenant"], world["customers"][customer_index], source, amount),
            )
        return carryover_id

    def test_a_paid_invoice_that_takes_on_a_carryover_becomes_partially_paid(self, admin, world):
        from services.billing import repository as repo

        billing_id = _make_invoice(admin, world)
        _pay(world, billing_id, "100000.00")
        carryover_id = self._carryover(admin, world)

        updated, amount = repo.apply_carryover_to_billing(world["tenant"], billing_id, carryover_id, world["customers"][0])

        assert amount == Decimal("5000.00")
        after = _billing(admin, billing_id)
        assert (after["status"], after["total"]) == ("partially_paid", Decimal("105000.00"))
        assert updated["status"] == "partially_paid"
        assert _rows(admin, "SELECT status, target_billing_id::text FROM carryover_ledger WHERE id = %s", (carryover_id,))[0] == (
            "applied",
            billing_id,
        )

    def test_two_simultaneous_applications_of_one_carryover_apply_it_once(self, admin, world):
        billing_id = _make_invoice(admin, world)
        carryover_id = self._carryover(admin, world)
        start = _start_soon()

        results = _run_parallel(
            _worker_apply_carryover, [(world["tenant"], billing_id, carryover_id, world["customers"][0], start)] * 2
        )

        assert sorted(results) == ["applied", "refused"]
        assert _billing(admin, billing_id)["total"] == Decimal("105000.00"), "the carried debt must be added once"

    def test_a_carryover_belonging_to_another_customer_is_refused(self, admin, world):
        from services.billing import repository as repo

        billing_id = _make_invoice(admin, world, index=0)
        carryover_id = self._carryover(admin, world, customer_index=1)

        with pytest.raises(repo.RecordNotFound):
            repo.apply_carryover_to_billing(world["tenant"], billing_id, carryover_id, world["customers"][0])

        assert _billing(admin, billing_id)["total"] == Decimal("100000.00")


# ---------------------------------------------------------------------------
# CBM dispute resolution
# ---------------------------------------------------------------------------


class TestDisputeResolution:
    def _dispute(self, admin, world, billing_id: str, status: str = "investigating") -> str:
        dispute_id = str(uuid.uuid4())
        with admin.cursor() as cur:
            cur.execute(
                "INSERT INTO cbm_dispute (id, tenant_id, billing_id, customer_id, disputed_cbm, status) VALUES (%s, %s, %s, %s, 1.5, %s)",
                (dispute_id, world["tenant"], billing_id, world["customers"][0], status),
            )
        return dispute_id

    def _resolve(self, world, dispute_id: str, billing_id: str):
        from services.billing import repository as repo

        return repo.resolve_dispute_with_adjustment(
            world["tenant"],
            dispute_id,
            billing_id,
            ["acknowledged", "investigating", "escalated_china"],
            Decimal("0.500"),
            Decimal("53.33"),
            Decimal("80000.00"),
            {
                "agreed_cbm": Decimal("0.500"),
                "resolution_notes": "re-measured",
                "resolved_by": world["user"],
                "resolved_at": datetime.now(UTC),
            },
        )

    def test_a_lower_corrected_cbm_reprices_the_invoice_and_refunds_what_was_overpaid_once(self, admin, world):
        billing_id = _make_invoice(admin, world, total="100000.00")
        _pay(world, billing_id, "100000.00")
        dispute_id = self._dispute(admin, world, billing_id)

        dispute, updated, overpayment = self._resolve(world, dispute_id, billing_id)

        assert dispute["status"] == "resolved_adjusted"
        assert overpayment == Decimal("20000.00")
        after = _billing(admin, billing_id)
        assert (after["status"], after["total"], after["subtotal"]) == ("overpaid", Decimal("80000.00"), Decimal("80000.00"))
        assert [r[0] for r in _refunds(admin, world)] == [Decimal("20000.00")]

    def test_resolving_the_same_dispute_again_reprices_and_refunds_nothing_more(self, admin, world):
        from services.billing import repository as repo

        billing_id = _make_invoice(admin, world, total="100000.00")
        _pay(world, billing_id, "100000.00")
        dispute_id = self._dispute(admin, world, billing_id)
        self._resolve(world, dispute_id, billing_id)

        with pytest.raises(repo.RecordNotFound):
            self._resolve(world, dispute_id, billing_id)

        assert _billing(admin, billing_id)["total"] == Decimal("80000.00")
        assert len(_refunds(admin, world)) == 1

    def test_a_payment_made_before_the_resolution_is_kept_not_overwritten(self, admin, world):
        """The total moves by the difference against the live subtotal, so a charge added meanwhile survives."""
        from services.billing import repository as repo

        billing_id = _make_invoice(admin, world, total="100000.00")
        repo.add_misc_charge_to_billing(
            world["tenant"],
            {
                "billing_id": billing_id,
                "description": "Late charge",
                "amount_ngn": Decimal("3000"),
                "amount_usd": None,
                "charge_type": "other",
                "charge_type_id": None,
                "created_by": world["user"],
            },
        )
        dispute_id = self._dispute(admin, world, billing_id)

        self._resolve(world, dispute_id, billing_id)

        assert _billing(admin, billing_id)["total"] == Decimal("83000.00"), "80,000 re-priced subtotal + the 3,000 charge"


# ---------------------------------------------------------------------------
# Storage fees
# ---------------------------------------------------------------------------


def _note(world, billing_id: str, days_ago: int = 20) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "billing_id": billing_id,
        "customer_id": world["customers"][0],
        "container_id": world["containers"][0],
        "total_cartons": 10,
        "created_at": datetime.now(UTC) - timedelta(days=days_ago),
    }


def _accrue(world, note: dict, on: date | None = None) -> bool:
    from services.scheduled.storage_fee import _accrue_for_note

    with patch("services.scheduled.storage_fee.publish_event"):
        return _accrue_for_note(world["tenant"], note, 14, Decimal("500"), on or date.today())


class TestStorageFees:
    def test_a_fee_on_a_paid_invoice_is_charged_and_the_invoice_reopens(self, admin, world):
        billing_id = _make_invoice(admin, world)
        _pay(world, billing_id, "100000.00")

        assert _accrue(world, _note(world, billing_id)) is True

        after = _billing(admin, billing_id)
        assert after["status"] == "partially_paid"
        assert after["total"] == Decimal("105000.00"), "one day's fee: 10 unreleased cartons x N500"

    def test_accruing_the_same_day_twice_charges_once(self, admin, world):
        billing_id = _make_invoice(admin, world)
        note = _note(world, billing_id)

        first = _accrue(world, note)
        second = _accrue(world, note)

        assert (first, second) == (True, False)
        assert _rows(admin, "SELECT COUNT(*) FROM storage_fee_log WHERE billing_id = %s", (billing_id,))[0][0] == 1
        assert _billing(admin, billing_id)["total"] == Decimal("105000.00")

    def test_a_fee_that_cannot_reach_its_invoice_leaves_no_log_row_to_block_the_retry(self, admin, world, foreign_billing):
        note = _note(world, foreign_billing["billing"])
        note["customer_id"], note["container_id"] = world["customers"][0], world["containers"][0]

        with pytest.raises(RuntimeError):
            _accrue(world, note)

        assert (
            _rows(admin, "SELECT COUNT(*) FROM storage_fee_log WHERE billing_id = %s", (foreign_billing["billing"],))[0][0] == 0
        )

    def test_the_invoice_shows_the_storage_fees_it_has_been_charged(self, admin, world):
        """The detail view read storage fees from misc_charge rows the job never creates, so it was always 0."""
        from services.billing import repository as repo
        from services.billing import service

        billing_id = _make_invoice(admin, world)
        _accrue(world, _note(world, billing_id))

        row = repo.get_billing_by_id(world["tenant"], billing_id)
        detail = service._enrich_billing(world["tenant"], dict(row))

        assert detail["storage_fees_ngn"] == Decimal("5000.00")

    def test_waiving_takes_the_fees_off_and_restores_the_status(self, admin, world):
        from services.billing import repository as repo

        billing_id = _make_invoice(admin, world)
        _pay(world, billing_id, "100000.00")
        note = _note(world, billing_id)
        _accrue(world, note, date.today() - timedelta(days=1))
        _accrue(world, note)
        assert _billing(admin, billing_id)["total"] == Decimal("110000.00"), "two days of N5,000"

        updated, waived = repo.waive_storage_fees_for_billing(world["tenant"], billing_id, "goodwill")

        assert waived == Decimal("10000.00")
        after = _billing(admin, billing_id)
        assert (after["status"], after["total"]) == ("paid", Decimal("100000.00"))
        assert repo.get_storage_fee_total(world["tenant"], billing_id) == Decimal("0")
        assert repo.get_storage_fees_for_billing(world["tenant"], billing_id) == []
        assert (
            _rows(admin, "SELECT COUNT(*) FROM storage_fee_log WHERE billing_id = %s AND waived_at IS NOT NULL", (billing_id,))[
                0
            ][0]
            == 2
        ), "waived fees stay in the log as history"

    def test_waiving_again_finds_nothing_to_waive(self, admin, world):
        from services.billing import repository as repo

        billing_id = _make_invoice(admin, world)
        _accrue(world, _note(world, billing_id))
        repo.waive_storage_fees_for_billing(world["tenant"], billing_id, "goodwill")

        _, waived = repo.waive_storage_fees_for_billing(world["tenant"], billing_id, "again")

        assert waived == Decimal("0")
        assert _billing(admin, billing_id)["total"] == Decimal("100000.00")

    def test_waiving_a_fee_the_customer_already_paid_opens_a_refund(self, admin, world):
        from services.billing import repository as repo

        billing_id = _make_invoice(admin, world)
        _accrue(world, _note(world, billing_id))
        _pay(world, billing_id, "105000.00")
        assert _billing(admin, billing_id)["status"] == "paid"

        updated, waived = repo.waive_storage_fees_for_billing(world["tenant"], billing_id, "goodwill")

        assert updated["status"] == "overpaid"
        assert [r[0] for r in _refunds(admin, world)] == [waived]

    def test_fees_accrued_after_a_waiver_are_charged_again(self, admin, world):
        from services.billing import repository as repo

        billing_id = _make_invoice(admin, world)
        note = _note(world, billing_id)
        _accrue(world, note, date.today() - timedelta(days=1))
        repo.waive_storage_fees_for_billing(world["tenant"], billing_id, "goodwill")

        assert _accrue(world, note) is True

        assert repo.get_storage_fee_total(world["tenant"], billing_id) > 0


# ---------------------------------------------------------------------------
# Refund approval
# ---------------------------------------------------------------------------


def _worker_approve_refund(args: tuple) -> str:
    tenant_id, refund_id, billing_id, start_at = args
    from services.refunds import repository as repo

    _wait_for(start_at)
    row = repo.approve_refund_and_adjust_billing(
        tenant_id,
        refund_id,
        "processed",
        {"amount_approved_ngn": Decimal("20000"), "approval_level": "manager", "approved_by": None},
        billing_id,
        Decimal("20000"),
    )
    return "approved" if row else "lost"


class TestRefundApproval:
    def _refund(self, admin, world, billing_id: str) -> str:
        refund_id = str(uuid.uuid4())
        with admin.cursor() as cur:
            cur.execute(
                "INSERT INTO refund_request (id, tenant_id, customer_id, billing_id, amount_ngn, reason, refund_type, status, "
                "customer_choice) VALUES (%s, %s, %s, %s, 20000, 'damage', 'damage_or_loss', 'pending_approval', 'immediate_refund')",
                (refund_id, world["tenant"], world["customers"][0], billing_id),
            )
        return refund_id

    def test_two_simultaneous_approvals_reduce_the_invoice_once(self, admin, world):
        billing_id = _make_invoice(admin, world, total="100000.00")
        refund_id = self._refund(admin, world, billing_id)
        start = _start_soon()

        results = _run_parallel(_worker_approve_refund, [(world["tenant"], refund_id, billing_id, start)] * 2)

        assert sorted(results) == ["approved", "lost"]
        assert _billing(admin, billing_id)["total"] == Decimal("80000.00"), "reduced by 20,000 once, not twice"
        assert _rows(admin, "SELECT status FROM refund_request WHERE id = %s", (refund_id,))[0][0] == "processed"

    def test_a_reduction_below_what_was_paid_marks_the_invoice_overpaid_and_refunds_the_excess(self, admin, world):
        from services.refunds import repository as repo

        billing_id = _make_invoice(admin, world, total="100000.00")
        _pay(world, billing_id, "100000.00")
        refund_id = self._refund(admin, world, billing_id)

        row = repo.approve_refund_and_adjust_billing(
            world["tenant"], refund_id, "processed", {"amount_approved_ngn": Decimal("20000")}, billing_id, Decimal("20000")
        )

        assert row["status"] == "processed"
        assert _billing(admin, billing_id)["status"] == "overpaid"
        follow_up = _refunds(admin, world, "Overpayment after refund adjustment%")
        assert [r[0] for r in follow_up] == [Decimal("20000.00")]

    def test_an_approval_whose_invoice_update_fails_leaves_the_refund_pending(self, admin, world, foreign_billing):
        from services.refunds import repository as repo

        refund_id = self._refund(admin, world, None)

        with pytest.raises(RuntimeError):
            repo.approve_refund_and_adjust_billing(
                world["tenant"],
                refund_id,
                "processed",
                {"amount_approved_ngn": Decimal("20000")},
                foreign_billing["billing"],
                Decimal("20000"),
            )

        assert _rows(admin, "SELECT status FROM refund_request WHERE id = %s", (refund_id,))[0][0] == "pending_approval"


# ---------------------------------------------------------------------------
# Claims and compensation
# ---------------------------------------------------------------------------


def _claims_patches():
    """Stub the side-effect publishers and the live rate lookup; everything else is real."""
    return (
        patch("services.claims.service.log_audit"),
        patch("services.claims.service.publish_event"),
        patch("services.claims.service._notify_customer_claim_update"),
        patch("services.claims.service.get_effective_dollar_rate", return_value={"rate": Decimal("1500")}),
    )


def _staff(world):
    from shared.tenant_context import TenantContext, UserRole

    return TenantContext(tenant_id=world["tenant"], user_id=world["user"], role=UserRole.NIGERIA_OFFICE_STAFF)


def _worker_resolve_claim(args: tuple) -> str:
    from contextlib import ExitStack

    from services.claims import service
    from shared.exceptions import IllegalTransitionError
    from shared.tenant_context import TenantContext, UserRole

    tenant_id, claim_id, user_id, start_at = args
    ctx = TenantContext(tenant_id=tenant_id, user_id=user_id, role=UserRole.NIGERIA_OFFICE_STAFF)
    req = SimpleNamespace(
        resolution_type=SimpleNamespace(value="refund"),
        settlement_amount_usd=None,
        amount_ngn=Decimal("1000"),
        reason="water damage",
        discount_percentage=None,
    )
    with ExitStack() as stack:
        for p in _claims_patches():
            stack.enter_context(p)
        _wait_for(start_at)
        try:
            service.resolve_claim(tenant_id, claim_id, req, actor_id=user_id, ctx=ctx)
        except IllegalTransitionError:
            return "refused"
    return "resolved"


def _worker_compensate_seized(args: tuple) -> str:
    from contextlib import ExitStack

    from services.claims import service
    from shared.tenant_context import TenantContext, UserRole

    tenant_id, item_id, user_id, start_at = args
    ctx = TenantContext(tenant_id=tenant_id, user_id=user_id, role=UserRole.NIGERIA_OFFICE_STAFF)
    with ExitStack() as stack:
        for p in _claims_patches():
            stack.enter_context(p)
        _wait_for(start_at)
        service.update_seized_item(
            tenant_id, item_id, "permanently_lost", "gone", actor_id=user_id, ctx=ctx, refund_amount_ngn=Decimal("5000")
        )
    return "done"


def _worker_compensate_missing(args: tuple) -> str:
    from contextlib import ExitStack

    from services.claims import service
    from shared.tenant_context import TenantContext, UserRole

    tenant_id, item_id, user_id, start_at = args
    ctx = TenantContext(tenant_id=tenant_id, user_id=user_id, role=UserRole.NIGERIA_OFFICE_STAFF)
    with ExitStack() as stack:
        for p in _claims_patches():
            stack.enter_context(p)
        _wait_for(start_at)
        service.update_missing_item(
            tenant_id, item_id, "confirmed_lost", "gone", actor_id=user_id, ctx=ctx, refund_amount_ngn=Decimal("7500")
        )
    return "done"


class TestClaims:
    def _claim(self, admin, world, status: str = "pending_resolution") -> str:
        claim_id = str(uuid.uuid4())
        with admin.cursor() as cur:
            cur.execute(
                "INSERT INTO damage_claim (id, tenant_id, customer_id, container_id, description, reference, status) "
                "VALUES (%s, %s, %s, %s, 'wet', %s, %s)",
                (claim_id, world["tenant"], world["customers"][0], world["containers"][0], f"CLM-{claim_id[:8]}", status),
            )
        return claim_id

    def _missing(self, admin, world) -> str:
        manifest_id, item_id = str(uuid.uuid4()), str(uuid.uuid4())
        with admin.cursor() as cur:
            cur.execute(
                "INSERT INTO manifest (id, tenant_id, container_id) VALUES (%s, %s, %s)",
                (manifest_id, world["tenant"], world["containers"][0]),
            )
            cur.execute(
                "INSERT INTO missing_item (id, tenant_id, manifest_id, customer_id, description, status) "
                "VALUES (%s, %s, %s, %s, 'lost carton', 'investigating')",
                (item_id, world["tenant"], manifest_id, world["customers"][0]),
            )
        return item_id

    def _seized(self, admin, world) -> str:
        item_id = str(uuid.uuid4())
        with admin.cursor() as cur:
            cur.execute(
                "INSERT INTO seized_item (id, tenant_id, container_id, customer_id, description, seizure_date, recovery_status) "
                "VALUES (%s, %s, %s, %s, 'goods', '2026-11-01', 'seized')",
                (item_id, world["tenant"], world["containers"][0], world["customers"][0]),
            )
        return item_id

    def test_two_staff_resolving_one_claim_at_once_open_one_refund(self, admin, world):
        claim_id = self._claim(admin, world)
        start = _start_soon()

        results = _run_parallel(_worker_resolve_claim, [(world["tenant"], claim_id, world["user"], start)] * 2)

        assert sorted(results) == ["refused", "resolved"]
        assert len(_refunds(admin, world)) == 1, "a second resolution must not open a second refund"
        assert _rows(admin, "SELECT COUNT(*) FROM claim_resolution WHERE damage_claim_id = %s", (claim_id,))[0][0] == 1
        assert _rows(admin, "SELECT status FROM damage_claim WHERE id = %s", (claim_id,))[0][0] == "resolved"

    def test_a_resolution_that_fails_part_way_leaves_the_claim_open_and_no_refund(self, admin, world):
        from contextlib import ExitStack

        from services.claims import service

        claim_id = self._claim(admin, world)
        req = SimpleNamespace(
            resolution_type=SimpleNamespace(value="refund"),
            settlement_amount_usd=None,
            amount_ngn=Decimal("1000"),
            reason="water damage",
            discount_percentage=None,
        )
        with ExitStack() as stack:
            for p in _claims_patches():
                stack.enter_context(p)
            stack.enter_context(patch.object(service.repo, "create_claim_resolution", side_effect=RuntimeError("boom")))
            with pytest.raises(RuntimeError):
                service.resolve_claim(world["tenant"], claim_id, req, actor_id=world["user"], ctx=_staff(world))

        assert _rows(admin, "SELECT status FROM damage_claim WHERE id = %s", (claim_id,))[0][0] == "pending_resolution"
        assert _refunds(admin, world) == [], "the refund opened before the failure must roll back with it"

    def test_compensating_a_seized_item_records_the_refund_with_a_type_the_database_accepts(self, admin, world):
        """This used to fail with a CHECK violation, after the item's status had already been saved."""
        from contextlib import ExitStack

        from services.claims import service

        item_id = self._seized(admin, world)
        with ExitStack() as stack:
            for p in _claims_patches():
                stack.enter_context(p)
            result = service.update_seized_item(
                world["tenant"],
                item_id,
                "permanently_lost",
                "found",
                actor_id=world["user"],
                ctx=_staff(world),
                refund_amount_ngn=Decimal("5000"),
            )

        refunds = _rows(admin, "SELECT amount_ngn, status FROM refund_request WHERE tenant_id = %s", (world["tenant"],))
        assert refunds == [(Decimal("5000.00"), "pending_review")]
        assert _rows(admin, "SELECT recovery_status FROM seized_item WHERE id = %s", (item_id,))[0][0] == "permanently_lost"
        assert result["refund_request_id"]

    def test_confirming_a_missing_item_lost_opens_a_compensation_refund(self, admin, world):
        """Compensation used to wait for a status the database does not allow, so it could never happen."""
        from contextlib import ExitStack

        from services.claims import service

        item_id = self._missing(admin, world)
        with ExitStack() as stack:
            for p in _claims_patches():
                stack.enter_context(p)
            result = service.update_missing_item(
                world["tenant"],
                item_id,
                "confirmed_lost",
                "carton not found",
                actor_id=world["user"],
                ctx=_staff(world),
                refund_amount_ngn=Decimal("7500"),
            )

        refunds = _rows(
            admin, "SELECT amount_ngn, status, refund_type FROM refund_request WHERE tenant_id = %s", (world["tenant"],)
        )
        assert refunds == [(Decimal("7500.00"), "pending_review", "missing_item")]
        status, linked = _rows(admin, "SELECT status, refund_request_id FROM missing_item WHERE id = %s", (item_id,))[0]
        assert status == "confirmed_lost"
        assert str(linked) == result["refund_request_id"]

    def test_a_missing_item_that_is_only_resolved_opens_no_refund(self, admin, world):
        from contextlib import ExitStack

        from services.claims import service

        item_id = self._missing(admin, world)
        with ExitStack() as stack:
            for p in _claims_patches():
                stack.enter_context(p)
            service.update_missing_item(
                world["tenant"],
                item_id,
                "found_and_shipping",
                None,
                actor_id=world["user"],
                ctx=_staff(world),
                refund_amount_ngn=Decimal("7500"),
            )

        assert _refunds(admin, world) == []

    def test_two_simultaneous_loss_confirmations_open_one_refund(self, admin, world):
        item_id = self._missing(admin, world)
        start = _start_soon()

        _run_parallel(_worker_compensate_missing, [(world["tenant"], item_id, world["user"], start)] * 2)

        assert len(_refunds(admin, world)) == 1

    def test_two_simultaneous_compensations_of_one_item_open_one_refund(self, admin, world):
        item_id = self._seized(admin, world)
        start = _start_soon()

        _run_parallel(_worker_compensate_seized, [(world["tenant"], item_id, world["user"], start)] * 2)

        assert len(_rows(admin, "SELECT 1 FROM refund_request WHERE tenant_id = %s", (world["tenant"],))) == 1


# ---------------------------------------------------------------------------
# The unbilled queue
# ---------------------------------------------------------------------------


class TestUnbilledQueue:
    def _approved(self, admin, world, index: int, cbm: str = "2.000") -> None:
        pl_id = str(uuid.uuid4())
        with admin.cursor() as cur:
            cur.execute(
                "INSERT INTO packing_list (id, tenant_id, container_id, customer_id, reference, status) "
                "VALUES (%s, %s, %s, %s, %s, 'approved')",
                (pl_id, world["tenant"], world["containers"][index], world["customers"][index], f"PL-{pl_id[:6]}"),
            )
            cur.execute(
                "INSERT INTO packing_list_item (packing_list_id, description, carton_tag, tracking_code, cbm) VALUES (%s, 'g', %s, %s, %s)",
                (pl_id, f"TAG-{pl_id[:6]}", f"TRK-{pl_id[:6]}", cbm),
            )

    def _status(self, admin, world, index: int, status: str) -> None:
        with admin.cursor() as cur:
            cur.execute("UPDATE container SET status = %s WHERE id = %s", (status, world["containers"][index]))

    def test_lists_only_customers_who_should_have_an_invoice_and_do_not(self, admin, world):
        from services.billing import repository as repo

        for i in range(4):
            self._approved(admin, world, i, cbm="0.000" if i == 3 else "2.000")
        self._status(admin, world, 0, "cleared")  # unbilled -> listed
        self._status(admin, world, 1, "cleared")  # billed below -> not listed
        self._status(admin, world, 2, "in_transit")  # not cleared yet -> not listed
        self._status(admin, world, 3, "cleared")  # nothing to bill -> not listed
        _make_invoice(admin, world, index=1)

        rows = repo.list_unbilled_customers(world["tenant"])

        assert [(r["customer_id"], r["container_status"]) for r in rows] == [(world["customers"][0], "cleared")]

    def test_a_cancelled_invoice_puts_the_customer_back_in_the_queue(self, admin, world):
        from services.billing import repository as repo

        self._approved(admin, world, 0)
        self._status(admin, world, 0, "cleared")
        billing_id = _make_invoice(admin, world, index=0)
        assert repo.list_unbilled_customers(world["tenant"]) == []

        with admin.cursor() as cur:
            cur.execute("UPDATE billing SET status = 'cancelled' WHERE id = %s", (billing_id,))

        assert len(repo.list_unbilled_customers(world["tenant"])) == 1
