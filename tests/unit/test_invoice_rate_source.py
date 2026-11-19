"""An invoice records where its exchange rate came from, and refuses a made-up one (audit BE-11)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest

TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
FLAT_USD = {
    "currency": "usd",
    "rate_mode": "flat",
    "carton_rate": Decimal("200"),
    "bag_rate": Decimal("200"),
    "bale_rate": Decimal("200"),
}


def _rate(source: str, fetched_at: str | None) -> dict:
    return {"rate": Decimal("1600"), "rate_source": source, "fetched_at": fetched_at, "source": "bybit_p2p"}


def _ago(minutes: int) -> str:
    return (datetime.now(UTC) - timedelta(minutes=minutes)).isoformat()


def _invoice(rate: dict):
    """Run handle_payment_due with everything but the rate stubbed. Returns (outcome, invoice row, staff notices)."""
    from services.billing import service

    captured: dict = {}

    def create_invoice(tid, data, number_prefix, carryover_ids, credit_applications):
        captured.update(data)
        return {**data, "id": "b1", "invoice_number": "ACM-INV-1"}, True

    repo_stubs = {
        "get_live_invoice": lambda *a: None,
        "get_cbm_and_carton_totals": lambda *a: {"total_cbm": Decimal("2"), "total_cartons": 4},
        "get_cbm_by_package_type": lambda *a: {"carton": Decimal("2")},
        "get_outstanding_carryovers": lambda *a: [],
        "get_pending_credit_refunds": lambda *a: [],
        "get_tenant_short": lambda tid: "ACM",
        "create_invoice": create_invoice,
        "get_customer_contact": lambda tid, cid: None,
    }
    patchers = [patch.object(service.repo, name, side_effect=fn) for name, fn in repo_stubs.items()]
    for p in patchers:
        p.start()
    try:
        with (
            patch.object(service, "get_effective_dollar_rate", return_value=rate),
            patch.object(service, "get_cbm_rate_config", return_value=FLAT_USD),
            patch.object(service, "publish_event"),
            patch.object(service, "log_audit"),
            patch.object(service, "notify_staff") as notices,
        ):
            outcome = service.handle_payment_due(TENANT, "k1", "cu1", "ACME001")
    finally:
        for p in patchers:
            p.stop()
    return outcome, captured, notices


class TestTheInvoiceRecordsTheRate:
    def test_a_live_rate_is_recorded_and_raises_nothing(self):
        fetched = _ago(3)
        outcome, row, notices = _invoice(_rate("live", fetched))
        assert outcome.status == "created"
        assert row["exchange_rate_source"] == "live" and row["exchange_rate_fetched_at"] == fetched
        notices.assert_not_called()

    def test_a_recent_last_known_rate_is_recorded_without_a_notice(self):
        outcome, row, notices = _invoice(_rate("last_known", _ago(30)))
        assert outcome.status == "created" and row["exchange_rate_source"] == "last_known"
        notices.assert_not_called()

    def test_an_old_last_known_rate_tells_tenant_admins(self):
        outcome, row, notices = _invoice(_rate("last_known", _ago(26 * 60)))
        assert outcome.status == "created" and row["exchange_rate_source"] == "last_known"
        notices.assert_called_once()
        kwargs = notices.call_args.kwargs
        assert kwargs["event_type"] == "invoice_old_exchange_rate" and kwargs["target_role"] == "tenant_admin"
        assert kwargs["entity_type"] == "billing" and kwargs["entity_id"] == "b1"
        assert "26 hours ago" in kwargs["body"]

    def test_the_age_limit_is_configurable(self, monkeypatch):
        monkeypatch.setenv("FX_RATE_MAX_AGE_MINUTES", "15")
        _, _, notices = _invoice(_rate("last_known", _ago(30)))
        notices.assert_called_once()

    @pytest.mark.parametrize("bad", ["0", "-5", "soon"])
    def test_a_nonsense_limit_does_not_break_invoicing(self, monkeypatch, bad):
        monkeypatch.setenv("FX_RATE_MAX_AGE_MINUTES", bad)
        outcome, _, _ = _invoice(_rate("last_known", _ago(30)))
        assert outcome.status == "created"

    def test_a_failed_notice_does_not_fail_the_invoice(self):
        from services.billing import service

        with patch.object(service, "notify_staff", side_effect=RuntimeError("down")):
            service._warn_if_rate_was_old(TENANT, "b1", "INV-1", "last_known", _ago(10_000))  # does not raise


class TestTheHardCodedRateIsRefused:
    def test_no_invoice_is_written(self):
        outcome, row, _ = _invoice(_rate("hardcoded", None))
        assert outcome.status == "skipped" and outcome.reason == "RATE_UNAVAILABLE"
        assert row == {}

    def test_the_container_run_reports_it_and_tells_staff(self):
        from services.billing import service

        skipped = service.InvoiceOutcome(status="skipped", reason="RATE_UNAVAILABLE", detail="x")
        with (
            patch.object(service, "handle_payment_due", return_value=skipped),
            patch.object(service, "notify_staff") as notices,
        ):
            rows = service.generate_container_invoices(TENANT, "k1", "ACME001", [{"id": "cu1", "name": "A"}])
        assert rows[0]["reason"] == "RATE_UNAVAILABLE"
        assert {c.kwargs["target_role"] for c in notices.call_args_list} == {"tenant_admin", "nigeria_office_staff"}
        assert "RATE_UNAVAILABLE" in notices.call_args.kwargs["body"]


class TestStaffSeeIt:
    ROW = {
        "id": "b1",
        "customer_id": "cu1",
        "exchange_rate_ngn": Decimal("1600"),
        "exchange_rate_source": "last_known",
        "exchange_rate_fetched_at": datetime(2026, 11, 16, 8, 0, tzinfo=UTC),
    }

    def _read(self, role):
        from services.billing import service
        from shared.tenant_context import TenantContext

        ctx = TenantContext(tenant_id=TENANT, user_id="u1", role=role)
        with (
            patch.object(service.repo, "get_billing_by_id", return_value=dict(self.ROW)),
            patch.object(service.repo, "get_customer_by_user_id", return_value={"id": "cu1"}),
            patch.object(service, "_enrich_billing", side_effect=lambda tid, row: {"id": row["id"]}),
        ):
            return service.get_billing(TENANT, "b1", ctx)

    def test_on_the_staff_invoice(self):
        from shared.tenant_context import UserRole

        body = self._read(UserRole.NIGERIA_OFFICE_STAFF)
        assert body["exchange_rate_source"] == "last_known"
        assert body["exchange_rate_fetched_at"] == "2026-11-16T08:00:00+00:00"

    def test_not_on_the_customer_invoice(self):
        from shared.tenant_context import UserRole

        body = self._read(UserRole.CUSTOMER)
        assert "exchange_rate_source" not in body and "exchange_rate_fetched_at" not in body


class TestRateAge:
    def test_age_in_minutes(self):
        from shared.fx_rate import rate_age_minutes

        now = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)
        assert rate_age_minutes("2026-11-17T10:00:00+00:00", now) == 120
        assert rate_age_minutes("2026-11-17T10:00:00", now) == 120  # naive means UTC
        assert rate_age_minutes(None, now) is None
        assert rate_age_minutes("yesterday", now) is None
