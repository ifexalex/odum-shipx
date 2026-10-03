"""Unit tests for services.payment_release.service — payment status, partial release."""
import json
import urllib.error
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
        "customer_name": "Chinedu Okafor",
        "customer_email": "chinedu@example.com",
        "customer_phone": "08012345678",
        "container_number": "MSKU1234567",
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
            patch.object(service.repo, "get_tenant_short", return_value="ACME"),
            patch.object(service.repo, "get_next_receipt_number", return_value=1),
            patch.object(service.repo, "create_payment_record", return_value={"id": "pay-001", "created_at": None}),
            patch.object(service.repo, "update_billing_payment", return_value=updated),
            patch("services.payment_release.service.publish_event"),
        ):
            result = service.confirm_payment(
                TENANT_ID, "billing-001", self._req("100000"), actor_id="u", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF)
            )
            assert result["new_payment_status"] == "paid"

    def test_partial_payment_sets_partially_paid(self):
        from services.payment_release import service

        billing = _billing(balance_ngn=Decimal("100000"))
        updated = {**billing, "amount_paid_ngn": Decimal("60000"), "balance_ngn": Decimal("40000"), "status": "partially_paid"}

        with (
            patch.object(service.repo, "get_billing_by_id", return_value=billing),
            patch.object(service.repo, "get_tenant_short", return_value="ACME"),
            patch.object(service.repo, "get_next_receipt_number", return_value=1),
            patch.object(service.repo, "create_payment_record", return_value={"id": "pay-001", "created_at": None}),
            patch.object(service.repo, "update_billing_payment", return_value=updated),
            patch("services.payment_release.service.publish_event"),
        ):
            result = service.confirm_payment(
                TENANT_ID, "billing-001", self._req("60000"), actor_id="u", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF)
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
            patch.object(service.repo, "get_tenant_short", return_value="ACME"),
            patch.object(service.repo, "get_next_receipt_number", return_value=1),
            patch.object(service.repo, "create_payment_record", return_value={"id": "pay-001", "created_at": None}),
            patch.object(service.repo, "update_billing_payment", return_value=updated),
            patch.object(service.repo, "create_overpayment_refund_request") as mock_refund,
            patch("services.payment_release.service.publish_event"),
        ):
            service.confirm_payment(
                TENANT_ID, "billing-001", self._req("105000"), actor_id="u", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF)
            )
            mock_refund.assert_called_once()

    def test_payment_within_tolerance_treated_as_paid(self):
        """Payment of 99999.99 on a 100000 bill is within ±0.01 tolerance → paid."""
        from services.payment_release import service

        billing = _billing(balance_ngn=Decimal("100000"))
        updated = {**billing, "balance_ngn": Decimal("0.01"), "status": "paid"}

        with (
            patch.object(service.repo, "get_billing_by_id", return_value=billing),
            patch.object(service.repo, "get_tenant_short", return_value="ACME"),
            patch.object(service.repo, "get_next_receipt_number", return_value=1),
            patch.object(service.repo, "create_payment_record", return_value={"id": "pay-001", "created_at": None}),
            patch.object(service.repo, "update_billing_payment", return_value=updated),
            patch("services.payment_release.service.publish_event"),
        ):
            result = service.confirm_payment(
                TENANT_ID, "billing-001", self._req("99999.99"), actor_id="u", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF)
            )
            assert result["new_payment_status"] == "paid"

    def test_billing_not_found_raises(self):
        from services.payment_release import service

        with patch.object(service.repo, "get_billing_by_id", return_value=None):
            with pytest.raises(ResourceNotFoundError):
                service.confirm_payment(
                    TENANT_ID, "nonexistent", self._req("100000"), actor_id="u", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF)
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
        # Explicitly None (not a truthy MagicMock auto-attribute) so
        # generate_release_note's `if warehouse_id else None` branch behaves
        # like a real request with no warehouse selected.
        req.warehouse_id = None
        req.packages_released = None
        return req

    def test_unpaid_billing_blocks_release(self):
        from services.payment_release import service

        billing = _billing(status="unpaid", balance_ngn=Decimal("100000"))

        with (
            patch.object(service.repo, "get_billing_by_id", return_value=billing),
            patch.object(service.repo, "get_active_release_note_carton_tags", return_value=[]),
        ):
            with pytest.raises(BusinessRuleViolationError):
                service.generate_release_note(TENANT_ID, self._req(), actor_id="u", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF))

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
            patch.object(service.repo, "get_active_release_note_carton_tags", return_value=[]),
            patch.object(service.repo, "get_default_warehouse", return_value=None),
            patch.object(service.repo, "mark_billing_released_with_outstanding"),
            patch.object(service.repo, "create_carryover_entry", return_value={"id": "co-001"}),
            patch.object(service.repo, "get_tenant_short", return_value="ACME"),
            patch.object(service.repo, "get_next_release_note_seq", return_value=1),
            patch.object(service.repo, "create_release_note", return_value=release_note),
            patch("services.payment_release.service.publish_event"),
        ):
            result = service.generate_release_note(
                TENANT_ID, self._req(release_with_outstanding=True), actor_id="u", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF)
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
            patch.object(service.repo, "get_active_release_note_carton_tags", return_value=[]),
            patch.object(service.repo, "get_default_warehouse", return_value=None),
            patch.object(service.repo, "get_tenant_short", return_value="ACME"),
            patch.object(service.repo, "get_next_release_note_seq", return_value=1),
            patch.object(service.repo, "create_release_note", return_value=release_note),
            patch("services.payment_release.service.publish_event"),
        ):
            result = service.generate_release_note(TENANT_ID, self._req(), actor_id="u", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF))
            assert result["id"] == "note-001"

    def test_immediate_response_shows_customer_container_and_warehouse_without_a_second_fetch(self):
        # Ground-truth gap found live: create_release_note's RETURNING row
        # carries no joins, so customer_name/container_number/warehouse_name
        # were null on the immediate POST response even though the caller
        # just selected a warehouse — only a follow-up GET (which does join)
        # showed them. generate_release_note must backfill both from data
        # it already has in hand (billing + the resolved warehouse row).
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
        warehouse_row = {"id": "wh-001", "name": "Lagos Island", "address": "12 Marina Rd", "phone": "0700000000"}
        req = self._req()
        req.warehouse_id = "wh-001"

        with (
            patch.object(service.repo, "get_billing_by_id", return_value=billing),
            patch.object(service.repo, "get_active_release_note_carton_tags", return_value=[]),
            patch.object(service.repo, "get_warehouse_by_id", return_value=warehouse_row),
            patch.object(service.repo, "get_tenant_short", return_value="ACME"),
            patch.object(service.repo, "get_next_release_note_seq", return_value=1),
            patch.object(service.repo, "create_release_note", return_value=release_note),
            patch("services.payment_release.service.publish_event"),
        ):
            result = service.generate_release_note(TENANT_ID, req, actor_id="u", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF))

        assert result["customer_name"] == billing["customer_name"]
        assert result["container_number"] == billing["container_number"]
        assert result["warehouse_name"] == "Lagos Island"
        assert result["warehouse_address"] == "12 Marina Rd"
        assert result["warehouse_phone"] == "0700000000"


class TestGenerateReleaseNoteDuplicateGuard:
    """Ground-truth gap found live: create_release_note is a bare INSERT with
    no uniqueness constraint, so re-submitting the same carton_tags (or an
    over-large packages_released) against a billing that already has an
    active/picked-up release note silently created a second, fully valid
    release note authorising the same cartons for pickup a second time.
    Reproduced live against a real seeded billing before this guard existed:
    the DB write succeeded and a duplicate 'active' note was created over
    already-picked-up cartons."""

    def _req(self, carton_tags=None, packages_released=None, package_unit=None) -> MagicMock:
        req = MagicMock()
        req.billing_id = "billing-001"
        req.carton_tags = carton_tags or []
        req.packages_released = packages_released
        req.package_unit = package_unit
        req.release_with_outstanding = False
        req.approval_notes = None
        req.warehouse_id = None
        return req

    def test_rejects_carton_tags_already_on_an_active_release_note(self):
        from services.payment_release import service

        billing = _billing(status="paid", balance_ngn=Decimal("0"))

        with (
            patch.object(service.repo, "get_billing_by_id", return_value=billing),
            patch.object(
                service.repo,
                "get_active_release_note_carton_tags",
                return_value=["TAG-001"],
            ),
        ):
            with pytest.raises(BusinessRuleViolationError) as exc_info:
                service.generate_release_note(
                    TENANT_ID,
                    self._req(carton_tags=["TAG-001", "TAG-002"]),
                    actor_id="u",
                    ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF),
                )
        assert exc_info.value.rule_id == "BR-RN-DUPLICATE-001"
        assert "TAG-001" in str(exc_info.value)

    def test_allows_carton_tags_with_no_overlap(self):
        from services.payment_release import service

        billing = _billing(status="paid", balance_ngn=Decimal("0"))
        release_note = {
            "id": "note-001",
            "reference_number": "ACME-RN-001",
            "status": "active",
            "carton_tags": ["TAG-002"],
            "total_cartons": 1,
            "is_partial": False,
            "created_at": None,
        }

        with (
            patch.object(service.repo, "get_billing_by_id", return_value=billing),
            patch.object(service.repo, "get_active_release_note_carton_tags", return_value=["TAG-001"]),
            patch.object(service.repo, "get_default_warehouse", return_value=None),
            patch.object(service.repo, "get_tenant_short", return_value="ACME"),
            patch.object(service.repo, "get_next_release_note_seq", return_value=1),
            patch.object(service.repo, "create_release_note", return_value=release_note),
            patch("services.payment_release.service.publish_event"),
        ):
            result = service.generate_release_note(
                TENANT_ID,
                self._req(carton_tags=["TAG-002"]),
                actor_id="u",
                ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF),
            )
        assert result["id"] == "note-001"

    def test_rejects_count_based_release_exceeding_remaining_balance(self):
        from services.payment_release import service

        billing = _billing(status="paid", balance_ngn=Decimal("0"))
        billing["total_cartons"] = 2

        with (
            patch.object(service.repo, "get_billing_by_id", return_value=billing),
            patch.object(service.repo, "get_active_release_note_packages_released", return_value=2),
        ):
            with pytest.raises(BusinessRuleViolationError) as exc_info:
                service.generate_release_note(
                    TENANT_ID,
                    self._req(packages_released=1, package_unit="cartons"),
                    actor_id="u",
                    ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF),
                )
        assert exc_info.value.rule_id == "BR-RN-OVERRELEASE-001"

    def test_allows_count_based_release_within_remaining_balance(self):
        from services.payment_release import service

        billing = _billing(status="paid", balance_ngn=Decimal("0"))
        billing["total_cartons"] = 2
        release_note = {
            "id": "note-001",
            "reference_number": "ACME-RN-001",
            "status": "active",
            "carton_tags": [],
            "total_cartons": 1,
            "is_partial": True,
            "created_at": None,
        }

        with (
            patch.object(service.repo, "get_billing_by_id", return_value=billing),
            patch.object(service.repo, "get_active_release_note_packages_released", return_value=1),
            patch.object(service.repo, "get_default_warehouse", return_value=None),
            patch.object(service.repo, "get_tenant_short", return_value="ACME"),
            patch.object(service.repo, "get_next_release_note_seq", return_value=1),
            patch.object(service.repo, "create_release_note", return_value=release_note),
            patch("services.payment_release.service.publish_event"),
        ):
            result = service.generate_release_note(
                TENANT_ID,
                self._req(packages_released=1, package_unit="cartons"),
                actor_id="u",
                ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF),
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


# ---------------------------------------------------------------------------
# Idempotency on payment confirmation
# ---------------------------------------------------------------------------


class TestPaymentConfirmIdempotency:
    def _event(self, idempotency_key: str | None = None) -> dict:
        headers = {}
        if idempotency_key is not None:
            headers["idempotency-key"] = idempotency_key

        return {
            "requestContext": {
                "requestId": "req-idem-001",
                "http": {"method": "POST", "path": "/v1/payments/billing-001/confirm"},
                "authorizer": {
                    "claims": {
                        "sub": "user-1",
                        "custom:tenant_id": TENANT_ID,
                        "cognito:groups": f"{TENANT_ID}:nigeria_office_staff",
                    }
                },
                "identity": {"sourceIp": "127.0.0.1"},
            },
            "headers": headers,
            "body": '{"amount_ngn": 100000, "payment_method": "bank_transfer", "payment_reference": "REF-001", "payment_date": "2026-02-01"}',
            "queryStringParameters": {},
            "pathParameters": {},
        }

    def _ctx(self) -> TenantContext:
        return TenantContext(tenant_id=TENANT_ID, user_id="user-1", role=UserRole.NIGERIA_OFFICE_STAFF)

    def test_cached_key_returns_cached_response_without_calling_service(self):
        from services.payment_release import handler

        cached_response = {"statusCode": 201, "body": '{"payment_id":"pay-cached"}'}

        with (
            patch("services.payment_release.handler.get_tenant_context", return_value=self._ctx()),
            patch("services.payment_release.handler.check_idempotency", return_value=cached_response) as mock_check,
            patch("services.payment_release.handler.service") as mock_service,
            patch("services.payment_release.handler.store_idempotency"),
            patch("services.payment_release.handler.record_usage"),
        ):
            result = handler.lambda_handler(self._event("idem-key-001"), None)

        mock_check.assert_called_once_with("idem-key-001", TENANT_ID)
        mock_service.confirm_payment.assert_not_called()
        assert result == cached_response

    def test_new_key_calls_service_then_stores(self):
        from services.payment_release import handler

        service_result = {
            "payment_id": "pay-001",
            "billing_id": "billing-001",
            "amount_ngn": Decimal("100000"),
            "new_payment_status": "paid",
            "outstanding_ngn": Decimal("0"),
            "release_note_available": True,
            "confirmed_at": None,
        }

        with (
            patch("services.payment_release.handler.get_tenant_context", return_value=self._ctx()),
            patch("services.payment_release.handler.check_idempotency", return_value=None),
            patch("services.payment_release.handler.service") as mock_service,
            patch("services.payment_release.handler.store_idempotency") as mock_store,
            patch("services.payment_release.handler.record_usage"),
        ):
            mock_service.confirm_payment.return_value = service_result
            handler.lambda_handler(self._event("idem-key-002"), None)

        mock_service.confirm_payment.assert_called_once()
        mock_store.assert_called_once()
        stored_key_arg = mock_store.call_args[0][0]
        assert stored_key_arg == "idem-key-002"

    def test_missing_key_calls_service_without_storing(self):
        from services.payment_release import handler

        service_result = {
            "payment_id": "pay-001",
            "billing_id": "billing-001",
            "amount_ngn": Decimal("100000"),
            "new_payment_status": "paid",
            "outstanding_ngn": Decimal("0"),
            "release_note_available": True,
            "confirmed_at": None,
        }

        with (
            patch("services.payment_release.handler.get_tenant_context", return_value=self._ctx()),
            patch("services.payment_release.handler.check_idempotency", return_value=None),
            patch("services.payment_release.handler.service") as mock_service,
            patch("services.payment_release.handler.store_idempotency") as mock_store,
            patch("services.payment_release.handler.record_usage"),
        ):
            mock_service.confirm_payment.return_value = service_result
            handler.lambda_handler(self._event(idempotency_key=None), None)

        mock_service.confirm_payment.assert_called_once()
        mock_store.assert_not_called()


# ---------------------------------------------------------------------------
# Webhook payment processing (service layer)
# ---------------------------------------------------------------------------


class TestWebhookPayment:
    def _billing(self, **kw) -> dict:
        return _billing(**kw)

    def test_first_delivery_processes_and_publishes(self):
        from services.payment_release import service

        billing = self._billing(status="unpaid", balance_ngn=Decimal("100000"))
        payment_row = {"id": "pay-webhook-001", "created_at": None}
        updated = {**billing, "amount_paid_ngn": Decimal("100000"), "balance_ngn": Decimal("0"), "status": "paid"}

        with (
            patch.object(service.repo, "get_billing_by_id", return_value=billing),
            patch("services.payment_release.webhook.validate_billing_for_webhook"),
            patch.object(service.repo, "create_webhook_payment_record", return_value=payment_row),
            patch.object(service.repo, "update_billing_payment", return_value=updated),
            patch("services.payment_release.service.publish_event") as mock_publish,
        ):
            result = service.process_webhook_payment(
                tenant_id=TENANT_ID,
                billing_id="billing-001",
                amount_ngn=Decimal("100000"),
                payment_method="paystack",
                payment_reference="REF-WH-001",
                gateway_transaction_id="gw-tx-001",
            )

        assert result is not None
        assert result["new_payment_status"] == "paid"
        mock_publish.assert_called_once()

    def test_duplicate_delivery_returns_none(self):
        """create_webhook_payment_record returning None signals a duplicate — service returns None."""
        from services.payment_release import service

        billing = self._billing(status="unpaid", balance_ngn=Decimal("100000"))

        with (
            patch.object(service.repo, "get_billing_by_id", return_value=billing),
            patch("services.payment_release.webhook.validate_billing_for_webhook"),
            patch.object(service.repo, "create_webhook_payment_record", return_value=None),
            patch.object(service.repo, "update_billing_payment") as mock_update,
            patch("services.payment_release.service.publish_event") as mock_publish,
        ):
            result = service.process_webhook_payment(
                tenant_id=TENANT_ID,
                billing_id="billing-001",
                amount_ngn=Decimal("100000"),
                payment_method="paystack",
                payment_reference="REF-WH-001",
                gateway_transaction_id="gw-tx-001",
            )

        assert result is None
        mock_update.assert_not_called()
        mock_publish.assert_not_called()

    def test_cancelled_billing_raises(self):
        from services.payment_release import service

        billing = self._billing(status="cancelled")

        with patch.object(service.repo, "get_billing_by_id", return_value=billing):
            with pytest.raises(BusinessRuleViolationError):
                service.process_webhook_payment(
                    tenant_id=TENANT_ID,
                    billing_id="billing-001",
                    amount_ngn=Decimal("50000"),
                    payment_method="flutterwave",
                    payment_reference="REF-WH-002",
                    gateway_transaction_id="gw-tx-002",
                )


# ---------------------------------------------------------------------------
# B12 — POST /v1/payments/{billing-id}/initialize (customer Paystack checkout)
# ---------------------------------------------------------------------------


class TestInitializeOnlinePayment:
    def _billing(self, **kw) -> dict:
        base = {
            "id": "billing-001",
            "tenant_id": TENANT_ID,
            "customer_id": "customer-001",
            "customer_email": "ngozi@example.com",
            "status": "unpaid",
            "total_ngn": Decimal("100000"),
            "amount_paid_ngn": Decimal("0"),
            "balance_ngn": Decimal("50656.00"),
        }
        base.update(kw)
        return base

    def _ctx(self):
        return TenantContext(tenant_id=TENANT_ID, user_id="cust-user-1", role=UserRole.CUSTOMER)

    def _run(
        self,
        billing=None,
        customer=None,
        callback="https://app.example.com/cb",
        init_result=None,
        paystack_secret="sk_test_tenant_own_key",
    ):
        from services.payment_release import service

        with (
            patch.object(service.repo, "get_billing_by_id", return_value=billing or self._billing()),
            patch.object(
                service.repo,
                "get_customer_by_user_id",
                return_value=customer if customer is not None else {"id": "customer-001"},
            ),
            patch.object(service.repo, "get_tenant_paystack_secret", return_value=paystack_secret),
            patch(
                "services.payment_release.paystack.initialize_transaction",
                return_value=init_result
                or {
                    "authorization_url": "https://checkout.paystack.com/x",
                    "reference": "r",
                    "access_code": "a",
                    "amount_ngn": "50656.00",
                },
            ) as mock_init,
        ):
            result = service.initialize_online_payment(TENANT_ID, "billing-001", self._ctx(), callback)
            return result, mock_init

    def test_initializes_with_outstanding_balance_and_customer_email(self):
        result, mock_init = self._run()
        assert result["authorization_url"].startswith("https://checkout.paystack.com/")
        kwargs = mock_init.call_args.kwargs
        assert kwargs["email"] == "ngozi@example.com"
        assert kwargs["amount_ngn"] == Decimal("50656.00")
        assert kwargs["billing_id"] == "billing-001"
        # Multi-tenant Paystack (2026-07-19) — the resolved tenant's own key
        # is passed through, never read from an env var inside paystack.py.
        assert kwargs["secret_key"] == "sk_test_tenant_own_key"

    def test_rejects_when_tenant_has_no_paystack_configured(self):
        """Ground-truth multi-tenant fix: no platform-wide fallback key —
        a tenant who hasn't connected their own Paystack account gets a
        clear error, not a silent charge to someone else's account."""
        from shared.exceptions import BusinessRuleViolationError

        with pytest.raises(BusinessRuleViolationError) as exc_info:
            self._run(paystack_secret=None)
        assert exc_info.value.rule_id == "PAYMENT_GATEWAY_NOT_CONFIGURED"

    def test_rejects_when_caller_is_not_the_billing_owner(self):
        from shared.exceptions import InsufficientPermissionsError

        with pytest.raises(InsufficientPermissionsError):
            self._run(customer={"id": "customer-somebody-else"})

    def test_rejects_when_nothing_outstanding(self):
        from shared.exceptions import BusinessRuleViolationError

        with pytest.raises(BusinessRuleViolationError):
            self._run(billing=self._billing(balance_ngn=Decimal("0")))

    def test_rejects_cancelled_billing(self):
        from shared.exceptions import BusinessRuleViolationError

        with pytest.raises(BusinessRuleViolationError):
            self._run(billing=self._billing(status="cancelled"))

    def test_rejects_missing_customer_email(self):
        from shared.exceptions import BusinessRuleViolationError

        with pytest.raises(BusinessRuleViolationError):
            self._run(billing=self._billing(customer_email=None))

    def test_rejects_non_http_callback(self):
        from shared.exceptions import BusinessRuleViolationError

        with pytest.raises(BusinessRuleViolationError):
            self._run(callback="javascript:alert(1)")

    def test_reference_format_is_retry_safe(self):
        from services.payment_release import paystack

        ref = paystack.build_reference("billing-001")
        assert ref.startswith("billing-001.")
        assert ref != paystack.build_reference("billing-001")  # unique per attempt


class TestVerifyTransaction:
    """paystack.verify_transaction — the raw HTTP call to Paystack's
    GET /transaction/verify/:reference, mocked at urllib.request.urlopen
    exactly like shared/fx_rate.py's fetch_bybit_ngn_rate tests."""

    def _urlopen_returning(self, body: bytes) -> MagicMock:
        resp = MagicMock()
        resp.read.return_value = body
        resp.__enter__.return_value = resp
        resp.__exit__.return_value = False
        return resp

    def test_returns_the_data_object_on_success(self):
        from services.payment_release import paystack

        body = json.dumps({"status": True, "data": {"status": "success", "amount": 10000000, "id": "gw-tx-1"}}).encode()
        with patch("urllib.request.urlopen", return_value=self._urlopen_returning(body)) as mock_urlopen:
            data = paystack.verify_transaction("sk_test_x", "billing-001.abc")

        assert data == {"status": "success", "amount": 10000000, "id": "gw-tx-1"}
        request = mock_urlopen.call_args[0][0]
        assert request.full_url == "https://api.paystack.co/transaction/verify/billing-001.abc"
        assert request.get_header("Authorization") == "Bearer sk_test_x"

    def test_url_encodes_the_reference(self):
        from services.payment_release import paystack

        body = json.dumps({"status": True, "data": {"status": "success"}}).encode()
        with patch("urllib.request.urlopen", return_value=self._urlopen_returning(body)) as mock_urlopen:
            paystack.verify_transaction("sk_test_x", "billing-001.abc/def")

        request = mock_urlopen.call_args[0][0]
        assert request.full_url == "https://api.paystack.co/transaction/verify/billing-001.abc%2Fdef"

    def test_http_error_raises_external_service_error(self):
        from services.payment_release import paystack
        from shared.exceptions import ExternalServiceError

        err = urllib.error.HTTPError(url="", code=404, msg="Not Found", hdrs=None, fp=None)
        err.read = lambda: b"not found"
        with patch("urllib.request.urlopen", side_effect=err):
            with pytest.raises(ExternalServiceError):
                paystack.verify_transaction("sk_test_x", "billing-001.abc")

    def test_network_unreachable_raises_external_service_error(self):
        from services.payment_release import paystack
        from shared.exceptions import ExternalServiceError

        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timed out")):
            with pytest.raises(ExternalServiceError):
                paystack.verify_transaction("sk_test_x", "billing-001.abc")

    def test_status_false_raises_external_service_error(self):
        from services.payment_release import paystack
        from shared.exceptions import ExternalServiceError

        body = json.dumps({"status": False, "message": "Transaction reference not found"}).encode()
        with patch("urllib.request.urlopen", return_value=self._urlopen_returning(body)):
            with pytest.raises(ExternalServiceError):
                paystack.verify_transaction("sk_test_x", "unknown-ref")


# ---------------------------------------------------------------------------
# Ground-truth gap: webhook alone never reconciled an online payment when
# Paystack can't reach the callback (always true in local dev; possible in
# prod too) — POST /v1/payments/{billing-id}/verify closes the loop directly.
# ---------------------------------------------------------------------------


class TestConfirmOnlinePayment:
    def _billing(self, **kw) -> dict:
        base = {
            "id": "billing-001",
            "tenant_id": TENANT_ID,
            "customer_id": "customer-001",
            "status": "unpaid",
            "total_ngn": Decimal("100000"),
            "amount_paid_ngn": Decimal("0"),
            "balance_ngn": Decimal("100000"),
        }
        base.update(kw)
        return base

    def _ctx(self):
        return TenantContext(tenant_id=TENANT_ID, user_id="cust-user-1", role=UserRole.CUSTOMER)

    def test_verified_success_reconciles_via_the_shared_webhook_path(self):
        from services.payment_release import service

        billing = self._billing()
        reference = "billing-001.abc123"
        confirm_result = {
            "payment_id": "pay-001",
            "billing_id": "billing-001",
            "amount_ngn": Decimal("100000"),
            "new_payment_status": "paid",
            "outstanding_ngn": Decimal("0"),
            "release_note_available": True,
        }

        with (
            patch.object(service.repo, "get_billing_by_id", return_value=billing),
            patch.object(service.repo, "get_customer_by_user_id", return_value={"id": "customer-001"}),
            patch.object(service.repo, "get_tenant_paystack_secret", return_value="sk_test_x"),
            patch(
                "services.payment_release.paystack.verify_transaction",
                return_value={"status": "success", "amount": 10000000, "id": "gw-tx-999", "reference": reference},
            ) as mock_verify,
            patch.object(service, "process_webhook_payment", return_value=confirm_result) as mock_confirm,
        ):
            result = service.confirm_online_payment(TENANT_ID, "billing-001", reference, self._ctx())

        mock_verify.assert_called_once_with("sk_test_x", reference)
        mock_confirm.assert_called_once()
        kwargs = mock_confirm.call_args.kwargs
        assert kwargs["amount_ngn"] == Decimal("100000")  # 10,000,000 kobo -> NGN
        assert kwargs["gateway_transaction_id"] == "gw-tx-999"
        assert kwargs["payment_method"] == "paystack"
        assert result["gateway_status"] == "success"
        assert result["new_payment_status"] == "paid"

    def test_already_reconciled_by_a_webhook_is_not_an_error(self):
        """process_webhook_payment returns None on a duplicate — the webhook
        (or an earlier call to this same endpoint) already got there first.
        Must still report success, re-reading current billing state."""
        from services.payment_release import service

        billing = self._billing()
        current = self._billing(status="paid", amount_paid_ngn=Decimal("100000"), balance_ngn=Decimal("0"))

        with (
            patch.object(service.repo, "get_billing_by_id", side_effect=[billing, current]),
            patch.object(service.repo, "get_customer_by_user_id", return_value={"id": "customer-001"}),
            patch.object(service.repo, "get_tenant_paystack_secret", return_value="sk_test_x"),
            patch(
                "services.payment_release.paystack.verify_transaction",
                return_value={"status": "success", "amount": 10000000, "id": "gw-tx-999"},
            ),
            patch.object(service, "process_webhook_payment", return_value=None),
        ):
            result = service.confirm_online_payment(TENANT_ID, "billing-001", "billing-001.abc123", self._ctx())

        assert result["gateway_status"] == "success"
        assert result["new_payment_status"] == "paid"
        assert result["outstanding_ngn"] == Decimal("0")

    def test_not_yet_successful_on_paystacks_side_is_reported_not_raised(self):
        from services.payment_release import service

        billing = self._billing()

        with (
            patch.object(service.repo, "get_billing_by_id", return_value=billing),
            patch.object(service.repo, "get_customer_by_user_id", return_value={"id": "customer-001"}),
            patch.object(service.repo, "get_tenant_paystack_secret", return_value="sk_test_x"),
            patch("services.payment_release.paystack.verify_transaction", return_value={"status": "abandoned"}),
            patch.object(service, "process_webhook_payment") as mock_confirm,
        ):
            result = service.confirm_online_payment(TENANT_ID, "billing-001", "billing-001.abc123", self._ctx())

        mock_confirm.assert_not_called()
        assert result["gateway_status"] == "abandoned"
        assert result["new_payment_status"] == "unpaid"

    def test_rejects_a_reference_that_belongs_to_a_different_billing(self):
        from services.payment_release import service

        billing = self._billing()
        with (
            patch.object(service.repo, "get_billing_by_id", return_value=billing),
            patch.object(service.repo, "get_customer_by_user_id", return_value={"id": "customer-001"}),
        ):
            with pytest.raises(BusinessRuleViolationError) as exc_info:
                service.confirm_online_payment(TENANT_ID, "billing-001", "some-other-billing.abc123", self._ctx())
        assert exc_info.value.rule_id == "BR-PAY-VERIFY-001"

    def test_rejects_when_caller_is_not_the_billing_owner(self):
        from services.payment_release import service
        from shared.exceptions import InsufficientPermissionsError

        billing = self._billing()
        with (
            patch.object(service.repo, "get_billing_by_id", return_value=billing),
            patch.object(service.repo, "get_customer_by_user_id", return_value={"id": "somebody-else"}),
        ):
            with pytest.raises(InsufficientPermissionsError):
                service.confirm_online_payment(TENANT_ID, "billing-001", "billing-001.abc123", self._ctx())

    def test_rejects_when_tenant_has_no_paystack_configured(self):
        from services.payment_release import service

        billing = self._billing()
        with (
            patch.object(service.repo, "get_billing_by_id", return_value=billing),
            patch.object(service.repo, "get_customer_by_user_id", return_value={"id": "customer-001"}),
            patch.object(service.repo, "get_tenant_paystack_secret", return_value=None),
        ):
            with pytest.raises(BusinessRuleViolationError) as exc_info:
                service.confirm_online_payment(TENANT_ID, "billing-001", "billing-001.abc123", self._ctx())
        assert exc_info.value.rule_id == "PAYMENT_GATEWAY_NOT_CONFIGURED"


# ---------------------------------------------------------------------------
# Release-note list wire shape + reference lookup (P2-2 audit fixes)
# ---------------------------------------------------------------------------


class TestListReleaseNotes:
    def _row(self, **kw) -> dict:
        base = {
            "id": "rn-1",
            "reference_number": "RN-20260716-001",
            "customer_name": "Ngozi Okonkwo",
            "container_number": "MSCU1234567",
            "total_cartons": 4,
            "is_partial": False,
            "carton_tags": ["SHX-1"],
            "status": "active",
            "payment_status": "paid",
            "billing_total_cartons": 4,
            "created_at": "2026-07-16T08:00:00Z",
            "updated_at": "2026-07-16T08:00:00Z",
            "valid_until": None,
            "parent_release_note_id": None,
        }
        base.update(kw)
        return base

    def test_list_rows_use_detail_wire_shape(self):
        """Raw DB columns must be mapped: carton_count / authorized_at / is_partial_release."""
        from services.payment_release import service

        with patch.object(service.repo, "list_release_notes", return_value=([self._row()], None, False)):
            page, _, _ = service.list_release_notes(TENANT_ID, {}, 50, None, _ctx(UserRole.NIGERIA_OFFICE_STAFF))

        note = page[0]
        assert note["carton_count"] == 4
        assert note["authorized_at"] == "2026-07-16T08:00:00Z"
        assert note["is_partial_release"] is False
        assert note["payment_status"] == "paid"
        assert note["total_cartons_for_customer"] == 4
        # Raw column names must not leak
        assert "total_cartons" not in note
        assert "is_partial" not in note

    def test_reference_filter_passed_to_repo(self):
        from services.payment_release import service

        with patch.object(service.repo, "list_release_notes", return_value=([], None, False)) as mock_list:
            service.list_release_notes(
                TENANT_ID,
                {"reference": "RN-20260716-001"},
                50,
                None,
                _ctx(UserRole.NIGERIA_OFFICE_STAFF),
            )

        assert mock_list.call_args[0][1] == {"reference": "RN-20260716-001"}


# ---------------------------------------------------------------------------
# Payment claims — customer-submitted "I've made this payment" + evidence
# ---------------------------------------------------------------------------


def _claim(**kw) -> dict:
    base = {
        "id": "claim-001",
        "tenant_id": TENANT_ID,
        "billing_id": "billing-001",
        "customer_id": "customer-001",
        "amount_ngn": Decimal("50000.00"),
        "evidence_file_key": f"{TENANT_ID}/payment-claims/billing-001/receipt.jpg",
        "evidence_file_name": "receipt.jpg",
        "status": "pending",
    }
    base.update(kw)
    return base


class TestSubmitPaymentClaim:
    def _req(self) -> MagicMock:
        req = MagicMock()
        req.amount_ngn = Decimal("50000.00")
        req.evidence_file_key = f"{TENANT_ID}/payment-claims/billing-001/receipt.jpg"
        req.evidence_file_name = "receipt.jpg"
        req.customer_note = "Sent via bank app"
        return req

    def test_customer_submits_claim_against_own_billing(self):
        from services.payment_release import service

        billing = _billing(status="unpaid")
        customer = {"id": "customer-001"}

        with (
            patch.object(service.repo, "get_billing_by_id", return_value=billing),
            patch.object(service.repo, "get_customer_by_user_id", return_value=customer),
            patch.object(service.repo, "create_payment_claim", return_value=_claim()) as mock_create,
            patch("services.payment_release.service.publish_event"),
        ):
            result = service.submit_payment_claim(
                TENANT_ID, "billing-001", self._req(), actor_id="user-1", ctx=_ctx(UserRole.CUSTOMER)
            )

        assert result["status"] == "pending"
        mock_create.assert_called_once()

    def test_submitting_notifies_staff(self):
        """Ground-truth follow-up to the payment-claim-rejection notification
        bug: staff previously had no way to even know a claim was pending
        review, in-app, beyond navigating to the list. New payment claims
        now feed the TopBar bell for nigeria_office_staff and tenant_admin."""
        from services.payment_release import service

        billing = _billing(status="unpaid")
        customer = {"id": "customer-001"}

        with (
            patch.object(service.repo, "get_billing_by_id", return_value=billing),
            patch.object(service.repo, "get_customer_by_user_id", return_value=customer),
            patch.object(service.repo, "create_payment_claim", return_value=_claim()),
            patch("services.payment_release.service.publish_event"),
            patch("services.payment_release.service.notify_staff") as mock_notify,
        ):
            service.submit_payment_claim(TENANT_ID, "billing-001", self._req(), actor_id="user-1", ctx=_ctx(UserRole.CUSTOMER))

        assert mock_notify.call_count == 2
        roles = {c.kwargs["target_role"] for c in mock_notify.call_args_list}
        assert roles == {"nigeria_office_staff", "tenant_admin"}
        assert all(c.kwargs["event_type"] == "payment_claim_submitted" for c in mock_notify.call_args_list)

    def test_notification_identifies_the_customer_and_payment_source(self):
        """Direct user report: they submitted a payment but "on the staff's
        notification, it did not tell the staff the customer who submitted
        the payment" — staff had to open the claim just to see whose payment
        it was. The title now names the customer; the body carries the
        amount, invoice, container, and phone so staff can record the
        payment without opening anything first."""
        from services.payment_release import service

        billing = _billing(
            status="unpaid",
            customer_name="Chinedu Okafor",
            customer_phone="08012345678",
            container_number="MSKU1234567",
            invoice_number="INV-2026-00123",
        )
        customer = {"id": "customer-001"}

        with (
            patch.object(service.repo, "get_billing_by_id", return_value=billing),
            patch.object(service.repo, "get_customer_by_user_id", return_value=customer),
            patch.object(service.repo, "create_payment_claim", return_value=_claim(amount_ngn=Decimal("50000.00"))),
            patch("services.payment_release.service.publish_event"),
            patch("services.payment_release.service.notify_staff") as mock_notify,
        ):
            service.submit_payment_claim(TENANT_ID, "billing-001", self._req(), actor_id="user-1", ctx=_ctx(UserRole.CUSTOMER))

        for call in mock_notify.call_args_list:
            assert call.kwargs["title"] == "New payment claim — Chinedu Okafor"
            body = call.kwargs["body"]
            assert "NGN 50000.00" in body
            assert "Invoice INV-2026-00123" in body
            assert "Container MSKU1234567" in body
            assert "08012345678" in body

    def test_notification_omits_missing_container_and_phone(self):
        """A billing record with no linked container (e.g. an air-freight or
        misc-charge invoice) or a customer with no phone on file must not
        render a literal "None" into the notification body."""
        from services.payment_release import service

        billing = _billing(
            status="unpaid",
            customer_name="Ada Nwosu",
            customer_phone=None,
            container_number=None,
        )
        customer = {"id": "customer-001"}

        with (
            patch.object(service.repo, "get_billing_by_id", return_value=billing),
            patch.object(service.repo, "get_customer_by_user_id", return_value=customer),
            patch.object(service.repo, "create_payment_claim", return_value=_claim()),
            patch("services.payment_release.service.publish_event"),
            patch("services.payment_release.service.notify_staff") as mock_notify,
        ):
            service.submit_payment_claim(TENANT_ID, "billing-001", self._req(), actor_id="user-1", ctx=_ctx(UserRole.CUSTOMER))

        for call in mock_notify.call_args_list:
            assert "None" not in call.kwargs["body"]
            assert "Container" not in call.kwargs["body"]

    def test_notification_falls_back_when_customer_name_is_missing(self):
        """A billing record whose customer join comes back empty (deleted/
        anonymised customer) must still produce a sane title, not "New
        payment claim — None"."""
        from services.payment_release import service

        billing = _billing(status="unpaid", customer_name=None)
        customer = {"id": "customer-001"}

        with (
            patch.object(service.repo, "get_billing_by_id", return_value=billing),
            patch.object(service.repo, "get_customer_by_user_id", return_value=customer),
            patch.object(service.repo, "create_payment_claim", return_value=_claim()),
            patch("services.payment_release.service.publish_event"),
            patch("services.payment_release.service.notify_staff") as mock_notify,
        ):
            service.submit_payment_claim(TENANT_ID, "billing-001", self._req(), actor_id="user-1", ctx=_ctx(UserRole.CUSTOMER))

        for call in mock_notify.call_args_list:
            assert call.kwargs["title"] == "New payment claim — A customer"

    def test_customer_cannot_submit_against_another_customers_billing(self):
        """Without this check, a customer could claim payment against any
        billing record in the tenant by guessing/enumerating billing ids."""
        from services.payment_release import service

        billing = _billing(customer_id="someone-elses-customer-id")
        with (
            patch.object(service.repo, "get_billing_by_id", return_value=billing),
            patch.object(service.repo, "get_customer_by_user_id", return_value={"id": "customer-001"}),
            patch.object(service.repo, "create_payment_claim") as mock_create,
        ):
            with pytest.raises(ResourceNotFoundError):
                service.submit_payment_claim(
                    TENANT_ID, "billing-001", self._req(), actor_id="user-1", ctx=_ctx(UserRole.CUSTOMER)
                )
        mock_create.assert_not_called()

    def test_cannot_submit_against_a_fully_paid_billing(self):
        from services.payment_release import service

        billing = _billing(status="paid")
        with (
            patch.object(service.repo, "get_billing_by_id", return_value=billing),
            patch.object(service.repo, "get_customer_by_user_id", return_value={"id": "customer-001"}),
            patch.object(service.repo, "create_payment_claim") as mock_create,
        ):
            with pytest.raises(BusinessRuleViolationError):
                service.submit_payment_claim(
                    TENANT_ID, "billing-001", self._req(), actor_id="user-1", ctx=_ctx(UserRole.CUSTOMER)
                )
        mock_create.assert_not_called()

    def test_second_pending_claim_rejected_as_business_rule_not_500(self):
        """create_payment_claim returns None when
        idx_payment_claim_one_pending_per_billing already has a row — must
        surface as a clear 422, not a raw unique-violation crash."""
        from services.payment_release import service

        billing = _billing(status="unpaid")
        with (
            patch.object(service.repo, "get_billing_by_id", return_value=billing),
            patch.object(service.repo, "get_customer_by_user_id", return_value={"id": "customer-001"}),
            patch.object(service.repo, "create_payment_claim", return_value=None),
        ):
            with pytest.raises(BusinessRuleViolationError):
                service.submit_payment_claim(
                    TENANT_ID, "billing-001", self._req(), actor_id="user-1", ctx=_ctx(UserRole.CUSTOMER)
                )


class TestListPaymentClaims:
    def test_customer_can_list_own_billing_claims(self):
        from services.payment_release import service

        billing = _billing()
        with (
            patch.object(service.repo, "get_billing_by_id", return_value=billing),
            patch.object(service.repo, "get_customer_by_user_id", return_value={"id": "customer-001"}),
            patch.object(service.repo, "list_payment_claims_for_billing", return_value=[_claim()]),
        ):
            result = service.list_payment_claims(TENANT_ID, "billing-001", _ctx(UserRole.CUSTOMER))
        assert len(result) == 1

    def test_customer_cannot_list_another_customers_claims(self):
        from services.payment_release import service

        billing = _billing(customer_id="someone-elses-customer-id")
        with (
            patch.object(service.repo, "get_billing_by_id", return_value=billing),
            patch.object(service.repo, "get_customer_by_user_id", return_value={"id": "customer-001"}),
        ):
            with pytest.raises(ResourceNotFoundError):
                service.list_payment_claims(TENANT_ID, "billing-001", _ctx(UserRole.CUSTOMER))

    def test_staff_can_list_any_billing_claims(self):
        from services.payment_release import service

        billing = _billing(customer_id="some-customer-id")
        with (
            patch.object(service.repo, "get_billing_by_id", return_value=billing),
            patch.object(service.repo, "list_payment_claims_for_billing", return_value=[_claim()]),
        ):
            result = service.list_payment_claims(TENANT_ID, "billing-001", _ctx(UserRole.NIGERIA_OFFICE_STAFF))
        assert len(result) == 1


class TestConfirmPaymentClaim:
    def test_confirming_creates_the_real_payment_record(self):
        """Confirming a claim must go through confirm_payment() — the actual
        source of truth for billing totals — not mutate billing directly."""
        from services.payment_release import service

        claim = _claim()
        billing = _billing(total_ngn=Decimal("50000"), balance_ngn=Decimal("50000"))
        updated_billing = {**billing, "amount_paid_ngn": Decimal("50000"), "balance_ngn": Decimal("0"), "status": "paid"}

        with (
            patch.object(service.repo, "get_payment_claim_by_id", return_value=claim),
            patch.object(service.repo, "get_billing_by_id", return_value=billing),
            patch.object(service.repo, "get_tenant_short", return_value="ACME"),
            patch.object(service.repo, "get_next_receipt_number", return_value=1),
            patch.object(service.repo, "create_payment_record", return_value={"id": "pay-001", "created_at": None}),
            patch.object(service.repo, "update_billing_payment", return_value=updated_billing),
            patch.object(
                service.repo, "update_payment_claim_status", return_value={**claim, "status": "confirmed"}
            ) as mock_update,
            patch("services.payment_release.service.publish_event"),
        ):
            result = service.confirm_payment_claim(
                TENANT_ID, "claim-001", actor_id="staff-1", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF)
            )

        assert result["new_payment_status"] == "paid"
        # The claim is linked back to the payment record it created.
        assert mock_update.call_args.kwargs["payment_record_id"] == "pay-001"

    def test_confirming_notifies_the_customer(self):
        """Ground-truth gap found live, reported by the user: a staff account
        rejected a claim and "no notification was showing" — reject/confirm
        fired an unrouted EventBridge event only, never enqueue_notifications,
        so the customer was never actually told either way."""
        from services.payment_release import service

        claim = _claim()
        billing = _billing(total_ngn=Decimal("50000"), balance_ngn=Decimal("50000"))
        updated_billing = {**billing, "amount_paid_ngn": Decimal("50000"), "balance_ngn": Decimal("0"), "status": "paid"}
        contact = {
            "id": "customer-001",
            "name": "Ngozi",
            "phone": "+2348012345678",
            "email": "n@x.com",
            "whatsapp": None,
            "locale": "en",
        }

        with (
            patch.object(service.repo, "get_payment_claim_by_id", return_value=claim),
            patch.object(service.repo, "get_billing_by_id", return_value=billing),
            patch.object(service.repo, "get_tenant_short", return_value="ACME"),
            patch.object(service.repo, "get_next_receipt_number", return_value=1),
            patch.object(service.repo, "create_payment_record", return_value={"id": "pay-001", "created_at": None}),
            patch.object(service.repo, "update_billing_payment", return_value=updated_billing),
            patch.object(service.repo, "update_payment_claim_status", return_value={**claim, "status": "confirmed"}),
            patch.object(service.repo, "get_customer_contact", return_value=contact) as mock_contact,
            patch("services.payment_release.service.publish_event"),
            patch("services.payment_release.service.enqueue_notifications") as mock_notify,
        ):
            service.confirm_payment_claim(TENANT_ID, "claim-001", actor_id="staff-1", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF))

        mock_contact.assert_called_once_with(TENANT_ID, "customer-001")
        mock_notify.assert_called_once()
        assert mock_notify.call_args.kwargs["event_type"] == "payment_claim_confirmed"
        assert mock_notify.call_args.kwargs["recipient"]["phone"] == "+2348012345678"
        assert mock_notify.call_args.kwargs["customer_id"] == "customer-001"

    def test_confirming_also_notifies_the_customer_in_app_when_they_have_a_portal_account(self):
        """Ground-truth follow-up, reported live by the user: they rejected a
        real payment claim and "did not see the notification when I logged
        in as [the customer]" — SMS/WhatsApp/email can each fail for reasons
        entirely outside this app, and the customer portal itself showed
        nothing at all until they happened to open that one billing page."""
        from services.payment_release import service

        claim = _claim()
        billing = _billing(total_ngn=Decimal("50000"), balance_ngn=Decimal("50000"))
        updated_billing = {**billing, "amount_paid_ngn": Decimal("50000"), "balance_ngn": Decimal("0"), "status": "paid"}
        contact = {
            "id": "customer-001",
            "user_id": "portal-user-001",
            "name": "Ngozi",
            "phone": "+2348012345678",
            "email": "n@x.com",
            "whatsapp": None,
            "locale": "en",
        }

        with (
            patch.object(service.repo, "get_payment_claim_by_id", return_value=claim),
            patch.object(service.repo, "get_billing_by_id", return_value=billing),
            patch.object(service.repo, "get_tenant_short", return_value="ACME"),
            patch.object(service.repo, "get_next_receipt_number", return_value=1),
            patch.object(service.repo, "create_payment_record", return_value={"id": "pay-001", "created_at": None}),
            patch.object(service.repo, "update_billing_payment", return_value=updated_billing),
            patch.object(service.repo, "update_payment_claim_status", return_value={**claim, "status": "confirmed"}),
            patch.object(service.repo, "get_customer_contact", return_value=contact),
            patch("services.payment_release.service.publish_event"),
            patch("services.payment_release.service.enqueue_notifications"),
            patch("services.payment_release.service.notify_staff") as mock_notify_staff,
        ):
            service.confirm_payment_claim(TENANT_ID, "claim-001", actor_id="staff-1", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF))

        mock_notify_staff.assert_called_once()
        assert mock_notify_staff.call_args.kwargs["target_user_id"] == "portal-user-001"
        assert mock_notify_staff.call_args.kwargs["event_type"] == "payment_claim_confirmed"
        assert (
            "target_role" not in mock_notify_staff.call_args.kwargs
            or mock_notify_staff.call_args.kwargs.get("target_role") is None
        )

    def test_rejecting_also_notifies_the_customer_in_app_with_the_reason(self):
        from services.payment_release import service

        claim = _claim()
        rejected = {**claim, "status": "rejected", "rejection_reason": "we did not receive your payment"}
        req = MagicMock()
        req.reason = "we did not receive your payment"
        contact = {
            "id": "customer-001",
            "user_id": "portal-user-001",
            "name": "Ngozi",
            "phone": "+2348012345678",
            "email": "n@x.com",
            "whatsapp": None,
            "locale": "en",
        }

        with (
            patch.object(service.repo, "get_payment_claim_by_id", return_value=claim),
            patch.object(service.repo, "update_payment_claim_status", return_value=rejected),
            patch.object(service.repo, "get_customer_contact", return_value=contact),
            patch("services.payment_release.service.publish_event"),
            patch("services.payment_release.service.enqueue_notifications"),
            patch("services.payment_release.service.notify_staff") as mock_notify_staff,
        ):
            service.reject_payment_claim(TENANT_ID, "claim-001", req, actor_id="staff-1", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF))

        mock_notify_staff.assert_called_once()
        assert mock_notify_staff.call_args.kwargs["target_user_id"] == "portal-user-001"
        assert "we did not receive your payment" in mock_notify_staff.call_args.kwargs["body"]

    def test_no_in_app_notification_for_a_customer_with_no_portal_account(self):
        from services.payment_release import service

        claim = _claim()
        rejected = {**claim, "status": "rejected"}
        req = MagicMock()
        req.reason = "no evidence"
        contact = {
            "id": "customer-001",
            "user_id": None,
            "name": "Ngozi",
            "phone": "+2348012345678",
            "email": "n@x.com",
            "whatsapp": None,
            "locale": "en",
        }

        with (
            patch.object(service.repo, "get_payment_claim_by_id", return_value=claim),
            patch.object(service.repo, "update_payment_claim_status", return_value=rejected),
            patch.object(service.repo, "get_customer_contact", return_value=contact),
            patch("services.payment_release.service.publish_event"),
            patch("services.payment_release.service.enqueue_notifications"),
            patch("services.payment_release.service.notify_staff") as mock_notify_staff,
        ):
            service.reject_payment_claim(TENANT_ID, "claim-001", req, actor_id="staff-1", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF))

        mock_notify_staff.assert_not_called()

    def test_a_notification_failure_does_not_fail_the_confirm(self):
        from services.payment_release import service

        claim = _claim()
        billing = _billing(total_ngn=Decimal("50000"), balance_ngn=Decimal("50000"))
        updated_billing = {**billing, "amount_paid_ngn": Decimal("50000"), "balance_ngn": Decimal("0"), "status": "paid"}

        with (
            patch.object(service.repo, "get_payment_claim_by_id", return_value=claim),
            patch.object(service.repo, "get_billing_by_id", return_value=billing),
            patch.object(service.repo, "get_tenant_short", return_value="ACME"),
            patch.object(service.repo, "get_next_receipt_number", return_value=1),
            patch.object(service.repo, "create_payment_record", return_value={"id": "pay-001", "created_at": None}),
            patch.object(service.repo, "update_billing_payment", return_value=updated_billing),
            patch.object(service.repo, "update_payment_claim_status", return_value={**claim, "status": "confirmed"}),
            patch.object(service.repo, "get_customer_contact", side_effect=RuntimeError("db down")),
            patch("services.payment_release.service.publish_event"),
        ):
            result = service.confirm_payment_claim(
                TENANT_ID, "claim-001", actor_id="staff-1", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF)
            )

        assert result["new_payment_status"] == "paid"

    def test_cannot_confirm_an_already_reviewed_claim(self):
        from services.payment_release import service

        with patch.object(service.repo, "get_payment_claim_by_id", return_value=_claim(status="confirmed")):
            with pytest.raises(BusinessRuleViolationError):
                service.confirm_payment_claim(TENANT_ID, "claim-001", actor_id="staff-1", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF))

    def test_unknown_claim_404s(self):
        from services.payment_release import service

        with patch.object(service.repo, "get_payment_claim_by_id", return_value=None):
            with pytest.raises(ResourceNotFoundError):
                service.confirm_payment_claim(TENANT_ID, "claim-001", actor_id="staff-1", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF))


class TestRejectPaymentClaim:
    def test_rejecting_records_the_reason(self):
        from services.payment_release import service

        claim = _claim()
        rejected = {**claim, "status": "rejected", "rejection_reason": "Amount doesn't match"}
        req = MagicMock()
        req.reason = "Amount doesn't match"

        with (
            patch.object(service.repo, "get_payment_claim_by_id", return_value=claim),
            patch.object(service.repo, "update_payment_claim_status", return_value=rejected) as mock_update,
            patch("services.payment_release.service.publish_event"),
        ):
            result = service.reject_payment_claim(
                TENANT_ID, "claim-001", req, actor_id="staff-1", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF)
            )

        assert result["status"] == "rejected"
        assert mock_update.call_args.kwargs["rejection_reason"] == "Amount doesn't match"

    def test_rejecting_notifies_the_customer_with_the_reason(self):
        """Ground-truth gap found live, reported by the user: a staff account
        rejected a claim and "no notification was showing" — reject fired an
        unrouted EventBridge event only, never enqueue_notifications."""
        from services.payment_release import service

        claim = _claim()
        rejected = {**claim, "status": "rejected", "rejection_reason": "Amount doesn't match"}
        req = MagicMock()
        req.reason = "Amount doesn't match"
        contact = {
            "id": "customer-001",
            "name": "Ngozi",
            "phone": "+2348012345678",
            "email": "n@x.com",
            "whatsapp": None,
            "locale": "en",
        }

        with (
            patch.object(service.repo, "get_payment_claim_by_id", return_value=claim),
            patch.object(service.repo, "update_payment_claim_status", return_value=rejected),
            patch.object(service.repo, "get_customer_contact", return_value=contact) as mock_contact,
            patch("services.payment_release.service.publish_event"),
            patch("services.payment_release.service.enqueue_notifications") as mock_notify,
        ):
            service.reject_payment_claim(TENANT_ID, "claim-001", req, actor_id="staff-1", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF))

        mock_contact.assert_called_once_with(TENANT_ID, "customer-001")
        mock_notify.assert_called_once()
        assert mock_notify.call_args.kwargs["event_type"] == "payment_claim_rejected"
        assert mock_notify.call_args.kwargs["template_data"]["reason"] == "Amount doesn't match"

    def test_a_notification_failure_does_not_fail_the_reject(self):
        from services.payment_release import service

        claim = _claim()
        rejected = {**claim, "status": "rejected", "rejection_reason": "too late"}
        req = MagicMock()
        req.reason = "too late"

        with (
            patch.object(service.repo, "get_payment_claim_by_id", return_value=claim),
            patch.object(service.repo, "update_payment_claim_status", return_value=rejected),
            patch.object(service.repo, "get_customer_contact", side_effect=RuntimeError("db down")),
            patch("services.payment_release.service.publish_event"),
        ):
            result = service.reject_payment_claim(
                TENANT_ID, "claim-001", req, actor_id="staff-1", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF)
            )

        assert result["status"] == "rejected"

    def test_no_notification_when_customer_contact_is_missing(self):
        from services.payment_release import service

        claim = _claim()
        rejected = {**claim, "status": "rejected", "rejection_reason": "too late"}
        req = MagicMock()
        req.reason = "too late"

        with (
            patch.object(service.repo, "get_payment_claim_by_id", return_value=claim),
            patch.object(service.repo, "update_payment_claim_status", return_value=rejected),
            patch.object(service.repo, "get_customer_contact", return_value=None),
            patch("services.payment_release.service.publish_event"),
            patch("services.payment_release.service.enqueue_notifications") as mock_notify,
        ):
            service.reject_payment_claim(TENANT_ID, "claim-001", req, actor_id="staff-1", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF))

        mock_notify.assert_not_called()

    def test_cannot_reject_an_already_reviewed_claim(self):
        from services.payment_release import service

        req = MagicMock()
        req.reason = "too late"
        with patch.object(service.repo, "get_payment_claim_by_id", return_value=_claim(status="rejected")):
            with pytest.raises(BusinessRuleViolationError):
                service.reject_payment_claim(
                    TENANT_ID, "claim-001", req, actor_id="staff-1", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF)
                )


class TestGetPaymentClaimEvidenceUrl:
    """Staff (and the submitting customer) need to actually see the receipt
    before confirming a claim — not just its filename."""

    def test_staff_can_view_evidence_for_any_claim(self):
        from services.payment_release import service

        with (
            patch.object(service.repo, "get_payment_claim_by_id", return_value=_claim()),
            patch.object(service.repo, "get_billing_by_id", return_value=_billing()),
            patch.object(
                service._s3_client, "generate_presigned_url", return_value="https://s3.example.com/signed"
            ) as mock_presign,
        ):
            result = service.get_payment_claim_evidence_url(TENANT_ID, "claim-001", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF))

        assert result["url"] == "https://s3.example.com/signed"
        assert mock_presign.call_args.kwargs["Params"]["Key"] == _claim()["evidence_file_key"]

    def test_customer_can_view_own_claim_evidence(self):
        from services.payment_release import service

        billing = _billing(customer_id="customer-001")
        with (
            patch.object(service.repo, "get_payment_claim_by_id", return_value=_claim()),
            patch.object(service.repo, "get_billing_by_id", return_value=billing),
            patch.object(service.repo, "get_customer_by_user_id", return_value={"id": "customer-001"}),
            patch.object(service._s3_client, "generate_presigned_url", return_value="https://s3.example.com/signed"),
        ):
            result = service.get_payment_claim_evidence_url(TENANT_ID, "claim-001", ctx=_ctx(UserRole.CUSTOMER))

        assert result["url"]

    def test_customer_cannot_view_another_customers_claim_evidence(self):
        from services.payment_release import service

        billing = _billing(customer_id="someone-elses-customer-id")
        with (
            patch.object(service.repo, "get_payment_claim_by_id", return_value=_claim()),
            patch.object(service.repo, "get_billing_by_id", return_value=billing),
            patch.object(service.repo, "get_customer_by_user_id", return_value={"id": "customer-001"}),
        ):
            with pytest.raises(ResourceNotFoundError):
                service.get_payment_claim_evidence_url(TENANT_ID, "claim-001", ctx=_ctx(UserRole.CUSTOMER))

    def test_unknown_claim_404s(self):
        from services.payment_release import service

        with patch.object(service.repo, "get_payment_claim_by_id", return_value=None):
            with pytest.raises(ResourceNotFoundError):
                service.get_payment_claim_evidence_url(TENANT_ID, "claim-001", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF))


# ---------------------------------------------------------------------------
# Release note field completeness — audited against a real paper "Goods
# Release Note" (Dollarman-style) reference the user shared.
# ---------------------------------------------------------------------------


def _release_note(**kw) -> dict:
    """A full row shape as returned by repo.get_release_note_by_id — every
    migration-041 column plus its joined aliases."""
    base = {
        "id": "note-001",
        "reference_number": "ACME-RN-20260913-0001",
        "customer_id": "customer-001",
        "billing_id": "billing-001",
        "container_id": "container-001",
        "customer_name": "Chinedu Okafor",
        "container_number": "MSKU1234567",
        "status": "active",
        "carton_tags": ["TAG-001", "TAG-002"],
        "total_cartons": 2,
        "is_partial": False,
        "created_at": None,
        "updated_at": None,
        "valid_until": None,
        "parent_release_note_id": None,
        "warehouse_id": "wh-001",
        "warehouse_name": "Lagos Island",
        "warehouse_address": "3rd Floor, Capital Plaza",
        "warehouse_phone": "07066171191",
        "is_on_credit": False,
        "credit_granted_by": None,
        "credit_granted_by_name": None,
        "receipt_number": None,
        "packages_released": None,
        "package_unit": None,
        "packages_balance": 8,
        "physical_document_number": "08280",
        "packing_list_invoice_numbers": ["#53534"],
        "billing_amount_paid_ngn": Decimal("1590600.00"),
        "billing_balance_ngn": Decimal("0.00"),
        "billing_total_ngn": Decimal("1590600.00"),
        "debt_due_date": None,
        "payment_status": "paid",
        "billing_total_cartons": 10,
    }
    base.update(kw)
    return base


class TestFmtReleaseNoteFieldCompleteness:
    """Ground-truth gap found live, from a real paper form the user shared:
    "check if there are other thing we need to do." physical_document_number,
    packing_list_invoice_numbers, the billing amounts, and the debt due date
    were all already fetched by the repository layer but silently dropped
    before _fmt_release_note's dict ever left this module."""

    def test_get_surfaces_every_migration_041_field(self):
        from services.payment_release import service

        note = _release_note(is_on_credit=True, credit_granted_by_name="Mr Hassel", debt_due_date="2026-09-30")
        with patch.object(service.repo, "get_release_note_by_id", return_value=note):
            result = service.get_release_note(TENANT_ID, "note-001", _ctx(UserRole.NIGERIA_OFFICE_STAFF))

        assert result["physical_document_number"] == "08280"
        assert result["packing_list_invoice_numbers"] == ["#53534"]
        assert result["amount_paid_ngn"] == "1590600.00"
        assert result["balance_ngn"] == "0.00"
        assert result["total_ngn"] == "1590600.00"
        assert result["debt_due_date"] == "2026-09-30"
        assert result["warehouse_name"] == "Lagos Island"
        assert result["warehouse_phone"] == "07066171191"
        assert result["is_on_credit"] is True
        assert result["credit_granted_by_name"] == "Mr Hassel"

    def test_generate_response_shows_the_due_date_immediately_without_a_refetch(self):
        """The POST /v1/release-notes response is built from the just-inserted
        row (no billing_ prefix, no join) — due_date must still show up since
        the caller supplied it in the same request."""
        from datetime import date

        from services.payment_release import service

        billing = _billing(status="unpaid", balance_ngn=Decimal("10000"))
        release_note = {
            "id": "note-001",
            "reference_number": "ACME-RN-001",
            "status": "active",
            "carton_tags": ["TAG-001", "TAG-002"],
            "total_cartons": 2,
            "is_partial": False,
            "created_at": None,
        }
        req = MagicMock()
        req.billing_id = "billing-001"
        req.carton_tags = ["TAG-001", "TAG-002"]
        req.packages_released = None
        req.release_with_outstanding = True
        req.approval_notes = "Approved by manager"
        req.due_date = date(2026, 9, 30)
        req.warehouse_id = None
        req.physical_document_number = "08280"
        req.credit_granted_by_name = "Mr Hassel"
        req.packing_list_invoice_numbers = ["#53534"]

        with (
            patch.object(service.repo, "get_billing_by_id", return_value=billing),
            patch.object(service.repo, "get_active_release_note_carton_tags", return_value=[]),
            patch.object(service.repo, "get_default_warehouse", return_value=None),
            patch.object(service.repo, "mark_billing_released_with_outstanding"),
            patch.object(service.repo, "create_carryover_entry", return_value={"id": "co-001"}),
            patch.object(service.repo, "get_tenant_short", return_value="ACME"),
            patch.object(service.repo, "get_next_release_note_seq", return_value=1),
            patch.object(service.repo, "create_release_note", return_value=release_note),
            patch("services.payment_release.service.publish_event"),
        ):
            result = service.generate_release_note(TENANT_ID, req, actor_id="u", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF))

        assert result["debt_due_date"] == "2026-09-30"


class TestSplitReleaseNote:
    def _req(self, tags=None) -> MagicMock:
        req = MagicMock()
        req.carton_tags = tags or ["TAG-002"]
        req.notes = None
        return req

    def test_carries_forward_warehouse_and_credit_terms_from_the_parent(self):
        """Ground-truth bug fix: create_split_release_note's INSERT used to
        name only the migration-003 columns, so a split child always lost
        its warehouse and any credit-release context the parent had."""
        from services.payment_release import service

        parent = _release_note(
            warehouse_id="wh-001",
            packing_list_invoice_numbers=["#53534"],
            is_on_credit=True,
            credit_granted_by="admin-1",
            credit_granted_by_name="Mr Hassel",
        )
        with (
            patch.object(service.repo, "get_release_note_by_id", return_value=parent),
            patch.object(service.repo, "get_picked_carton_tags", return_value=[]),
            patch.object(service.repo, "get_billing_by_id", return_value=_billing()),
            patch.object(service.repo, "get_tenant_short", return_value="ACME"),
            patch.object(service.repo, "get_next_release_note_seq", return_value=2),
            patch.object(
                service.repo,
                "create_split_release_note",
                return_value={**parent, "id": "note-002", "carton_tags": ["TAG-002"], "total_cartons": 1},
            ) as mock_create,
            patch("services.payment_release.service.publish_event"),
            patch("services.payment_release.service.log_audit"),
        ):
            service.split_release_note(TENANT_ID, "note-001", self._req(), actor_id="u", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF))

        call_kwargs = mock_create.call_args.args[1]
        assert call_kwargs["warehouse_id"] == "wh-001"
        assert call_kwargs["packing_list_invoice_numbers"] == ["#53534"]
        assert call_kwargs["is_on_credit"] is True
        assert call_kwargs["credit_granted_by_name"] == "Mr Hassel"

    def test_rejects_tags_not_on_the_parent(self):
        from services.payment_release import service

        parent = _release_note(carton_tags=["TAG-001", "TAG-002"])
        with patch.object(service.repo, "get_release_note_by_id", return_value=parent):
            with pytest.raises(BusinessRuleViolationError):
                service.split_release_note(
                    TENANT_ID,
                    "note-001",
                    self._req(tags=["TAG-999"]),
                    actor_id="u",
                    ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF),
                )

    def test_rejects_tags_already_picked_up(self):
        from services.payment_release import service

        parent = _release_note(carton_tags=["TAG-001", "TAG-002"])
        with (
            patch.object(service.repo, "get_release_note_by_id", return_value=parent),
            patch.object(service.repo, "get_picked_carton_tags", return_value=["TAG-002"]),
        ):
            with pytest.raises(BusinessRuleViolationError):
                service.split_release_note(
                    TENANT_ID,
                    "note-001",
                    self._req(tags=["TAG-002"]),
                    actor_id="u",
                    ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF),
                )


class TestReissueReleaseNote:
    def test_reissue_is_a_full_clone_of_the_expired_parent(self):
        """Ground-truth bug fix: reissue is meant to be the *same* release —
        same warehouse, same credit terms, same physical document — just a
        fresh 14-day window. It silently lost every migration-041 field."""
        from services.payment_release import service

        parent = _release_note(
            status="expired",
            warehouse_id="wh-001",
            is_on_credit=True,
            credit_granted_by="admin-1",
            credit_granted_by_name="Mr Hassel",
            packages_released=5,
            package_unit="CTNS",
            packages_balance=3,
            physical_document_number="08280",
            packing_list_invoice_numbers=["#53534"],
        )
        with (
            patch.object(service.repo, "get_release_note_by_id", return_value=parent),
            patch.object(service.repo, "get_billing_by_id", return_value=_billing()),
            patch.object(service.repo, "get_tenant_short", return_value="ACME"),
            patch.object(service.repo, "get_next_release_note_seq", return_value=3),
            patch.object(
                service.repo,
                "create_split_release_note",
                return_value={**parent, "id": "note-003", "status": "active"},
            ) as mock_create,
            patch("services.payment_release.service.publish_event"),
            patch("services.payment_release.service.log_audit"),
        ):
            service.reissue_release_note(TENANT_ID, "note-001", actor_id="u", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF))

        call_kwargs = mock_create.call_args.args[1]
        assert call_kwargs["warehouse_id"] == "wh-001"
        assert call_kwargs["is_on_credit"] is True
        assert call_kwargs["credit_granted_by_name"] == "Mr Hassel"
        assert call_kwargs["packages_released"] == 5
        assert call_kwargs["package_unit"] == "CTNS"
        assert call_kwargs["packages_balance"] == 3
        assert call_kwargs["physical_document_number"] == "08280"
        assert call_kwargs["packing_list_invoice_numbers"] == ["#53534"]

    def test_only_expired_notes_can_be_reissued(self):
        from services.payment_release import service
        from shared.exceptions import BusinessRuleViolationError as BRV

        parent = _release_note(status="active")
        with patch.object(service.repo, "get_release_note_by_id", return_value=parent):
            with pytest.raises(BRV):
                service.reissue_release_note(TENANT_ID, "note-001", actor_id="u", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF))


class TestRecordPickupOfficerNames:
    """Ground-truth gap found live, from the paper form: two more named
    sign-off lines (Customer Service Officer, Accounting Officer) exist
    alongside the warehouse attendant — RecordPickupRequest already captured
    both ids, but get_tenant_user_name (whose own docstring already says
    "officer names") was only ever called for the attendant."""

    def _req(self, **overrides) -> MagicMock:
        req = MagicMock()
        req.is_delegate = False
        req.collected_by_name = "Baba Sunny"
        req.delegate_name = None
        req.delegate_phone = None
        req.delegate_id_type = None
        req.delegate_id_number = None
        req.cartons_released = 2
        req.carton_tags_picked = []
        req.warehouse_id = "wh-001"
        req.customer_service_officer_id = "cso-1"
        req.accounting_officer_id = "acct-1"
        req.warehouse_attendant_id = "att-1"
        req.notes = None
        for k, v in overrides.items():
            setattr(req, k, v)
        return req

    def test_resolves_customer_service_officer_and_accounting_officer_names(self):
        from services.payment_release import service

        note = _release_note(status="active", total_cartons=2)
        with (
            patch.object(service.repo, "get_release_note_by_id", return_value=note),
            patch.object(
                service.repo,
                "create_pickup_record",
                return_value={"id": "pu-1", "pickup_date": "2026-09-13", "collected_by_name": "Baba Sunny", "created_at": None},
            ),
            patch.object(service.repo, "sum_cartons_picked_for_release_note", return_value=2),
            patch.object(service.repo, "update_release_note_status"),
            patch.object(service.repo, "sum_cartons_released_for_customer", return_value=2),
            patch.object(service.repo, "sum_total_cartons_from_billing", return_value=2),
            patch.object(service.repo, "sum_cartons_released_for_container", return_value=2),
            patch.object(service.repo, "update_container_status"),
            patch.object(service.repo, "update_shipment_tracking_for_customer"),
            patch.object(
                service.repo,
                "get_tenant_user_name",
                side_effect=lambda tenant_id, user_id: {"att-1": "John Warehouse", "cso-1": "Mr Njubusi", "acct-1": "Evelyn"}.get(
                    user_id
                ),
            ),
            patch("services.payment_release.service.log_audit"),
        ):
            result = service.record_pickup(
                TENANT_ID, "note-001", self._req(), actor_id="u", ctx=_ctx(UserRole.WAREHOUSE_ATTENDANT)
            )

        assert result["attendant_name"] == "John Warehouse"
        assert result["customer_service_officer_name"] == "Mr Njubusi"
        assert result["accounting_officer_name"] == "Evelyn"

    def test_officer_names_are_none_when_not_supplied(self):
        from services.payment_release import service

        note = _release_note(status="active", total_cartons=2)
        with (
            patch.object(service.repo, "get_release_note_by_id", return_value=note),
            patch.object(
                service.repo,
                "create_pickup_record",
                return_value={"id": "pu-1", "pickup_date": "2026-09-13", "collected_by_name": "Baba Sunny", "created_at": None},
            ),
            patch.object(service.repo, "sum_cartons_picked_for_release_note", return_value=2),
            patch.object(service.repo, "update_release_note_status"),
            patch.object(service.repo, "sum_cartons_released_for_customer", return_value=2),
            patch.object(service.repo, "sum_total_cartons_from_billing", return_value=2),
            patch.object(service.repo, "sum_cartons_released_for_container", return_value=2),
            patch.object(service.repo, "update_container_status"),
            patch.object(service.repo, "update_shipment_tracking_for_customer"),
            patch.object(service.repo, "get_tenant_user_name", return_value="John Warehouse"),
            patch("services.payment_release.service.log_audit"),
        ):
            result = service.record_pickup(
                TENANT_ID,
                "note-001",
                self._req(customer_service_officer_id=None, accounting_officer_id=None),
                actor_id="u",
                ctx=_ctx(UserRole.WAREHOUSE_ATTENDANT),
            )

        assert result["customer_service_officer_name"] is None
        assert result["accounting_officer_name"] is None


class TestWarehouses:
    """New GET/POST /v1/warehouses — a multi-branch tenant (the paper form
    this feature was audited against lists ~9 offices for one company) had
    no way to register more than the single default migration 041 backfills."""

    def test_list_warehouses_returns_repo_rows(self):
        from services.payment_release import service

        rows = [{"id": "wh-001", "name": "Lagos Island", "is_default": True}]
        with patch.object(service.repo, "list_warehouses", return_value=rows) as mock_list:
            result = service.list_warehouses(TENANT_ID)

        assert result == rows
        mock_list.assert_called_once_with(TENANT_ID)

    def test_create_warehouse_audits_and_returns_the_new_row(self):
        from services.payment_release import service

        req = MagicMock()
        req.name = "Onitsha Office"
        req.address = "27 Sokoto Road"
        req.city = "Onitsha"
        req.state = "Anambra"
        req.phone = "07066171191"

        with (
            patch.object(service.repo, "list_warehouses", return_value=[{"id": "wh-001"}]),
            patch.object(service.repo, "create_warehouse", return_value={"id": "wh-002", "name": "Onitsha Office"}),
            patch("services.payment_release.service.log_audit") as mock_audit,
        ):
            result = service.create_warehouse(TENANT_ID, req, actor_id="admin-1", actor_role="tenant_admin")

        assert result["name"] == "Onitsha Office"
        mock_audit.assert_called_once()
        assert mock_audit.call_args.kwargs["entity_type"] == "warehouse"

    def test_the_first_warehouse_a_tenant_creates_becomes_the_default(self):
        """Ground-truth gap found live: a real tenant's warehouse list came
        back completely empty (onboarded after migration 041's one-time
        backfill), and get_default_warehouse() has no other way to ever
        return a row unless something explicitly sets is_default."""
        from services.payment_release import service

        req = MagicMock()
        req.name = "Main Warehouse"
        req.address = None
        req.city = None
        req.state = None
        req.phone = None

        with (
            patch.object(service.repo, "list_warehouses", return_value=[]),
            patch.object(service.repo, "create_warehouse", return_value={"id": "wh-001"}) as mock_create,
            patch("services.payment_release.service.log_audit"),
        ):
            service.create_warehouse(TENANT_ID, req, actor_id="admin-1", actor_role="tenant_admin")

        assert mock_create.call_args.args[1]["is_default"] is True

    def test_a_subsequent_warehouse_is_not_auto_defaulted(self):
        from services.payment_release import service

        req = MagicMock()
        req.name = "Onitsha Office"
        req.address = None
        req.city = None
        req.state = None
        req.phone = None

        with (
            patch.object(service.repo, "list_warehouses", return_value=[{"id": "wh-001", "is_default": True}]),
            patch.object(service.repo, "create_warehouse", return_value={"id": "wh-002"}) as mock_create,
            patch("services.payment_release.service.log_audit"),
        ):
            service.create_warehouse(TENANT_ID, req, actor_id="admin-1", actor_role="tenant_admin")

        assert mock_create.call_args.args[1]["is_default"] is False

    def test_set_default_warehouse_audits_and_returns_the_updated_row(self):
        from services.payment_release import service

        with (
            patch.object(service.repo, "get_warehouse_by_id", return_value={"id": "wh-002", "is_default": False}),
            patch.object(service.repo, "set_default_warehouse", return_value={"id": "wh-002", "is_default": True}),
            patch("services.payment_release.service.log_audit") as mock_audit,
        ):
            result = service.set_default_warehouse(TENANT_ID, "wh-002", actor_id="admin-1", actor_role="tenant_admin")

        assert result["is_default"] is True
        assert mock_audit.call_args.kwargs["action"] == "UPDATE"

    def test_set_default_warehouse_404s_for_an_unknown_id(self):
        from services.payment_release import service

        with patch.object(service.repo, "get_warehouse_by_id", return_value=None):
            with pytest.raises(ResourceNotFoundError):
                service.set_default_warehouse(TENANT_ID, "missing", actor_id="admin-1", actor_role="tenant_admin")

    def test_warehouse_list_route_forbidden_for_customer(self):
        from services.payment_release import handler

        event = {
            "requestContext": {
                "requestId": "req-wh-001",
                "http": {"method": "GET", "path": "/v1/warehouses"},
                "authorizer": {"claims": {"sub": "u1", "custom:tenant_id": TENANT_ID}},
                "identity": {"sourceIp": "127.0.0.1"},
            },
            "headers": {},
            "body": None,
            "queryStringParameters": {},
            "pathParameters": {},
        }
        ctx = _ctx(UserRole.CUSTOMER)
        with patch("services.payment_release.handler.get_tenant_context", return_value=ctx):
            resp = handler.lambda_handler(event, None)

        assert resp["statusCode"] == 403

    def test_warehouse_create_route_forbidden_for_nigeria_office_staff(self):
        from services.payment_release import handler

        event = {
            "requestContext": {
                "requestId": "req-wh-002",
                "http": {"method": "POST", "path": "/v1/warehouses"},
                "authorizer": {"claims": {"sub": "u1", "custom:tenant_id": TENANT_ID}},
                "identity": {"sourceIp": "127.0.0.1"},
            },
            "headers": {},
            "body": '{"name": "Onitsha Office"}',
            "queryStringParameters": {},
            "pathParameters": {},
        }
        ctx = _ctx(UserRole.NIGERIA_OFFICE_STAFF)
        with patch("services.payment_release.handler.get_tenant_context", return_value=ctx):
            resp = handler.lambda_handler(event, None)

        assert resp["statusCode"] == 403

    def test_warehouse_create_route_succeeds_for_tenant_admin(self):
        from services.payment_release import handler, service

        event = {
            "requestContext": {
                "requestId": "req-wh-003",
                "http": {"method": "POST", "path": "/v1/warehouses"},
                "authorizer": {"claims": {"sub": "admin-1", "custom:tenant_id": TENANT_ID}},
                "identity": {"sourceIp": "127.0.0.1"},
            },
            "headers": {},
            "body": '{"name": "Onitsha Office", "address": "27 Sokoto Road"}',
            "queryStringParameters": {},
            "pathParameters": {},
        }
        ctx = _ctx(UserRole.TENANT_ADMIN)
        with (
            patch("services.payment_release.handler.get_tenant_context", return_value=ctx),
            patch.object(service, "create_warehouse", return_value={"id": "wh-002", "name": "Onitsha Office"}) as mock_create,
        ):
            resp = handler.lambda_handler(event, None)

        assert resp["statusCode"] == 201
        # _ctx() always builds user_id="user-1" regardless of role — the
        # event's own "sub" claim is irrelevant since get_tenant_context is
        # mocked to return this fixture directly.
        assert mock_create.call_args.kwargs["actor_id"] == "user-1"

    def test_set_default_route_forbidden_for_nigeria_office_staff(self):
        from services.payment_release import handler

        event = {
            "requestContext": {
                "requestId": "req-wh-004",
                "http": {"method": "PATCH", "path": "/v1/warehouses/wh-002/set-default"},
                "authorizer": {"claims": {"sub": "u1", "custom:tenant_id": TENANT_ID}},
                "identity": {"sourceIp": "127.0.0.1"},
            },
            "headers": {},
            "body": "{}",
            "queryStringParameters": {},
            "pathParameters": {},
        }
        ctx = _ctx(UserRole.NIGERIA_OFFICE_STAFF)
        with patch("services.payment_release.handler.get_tenant_context", return_value=ctx):
            resp = handler.lambda_handler(event, None)

        assert resp["statusCode"] == 403

    def test_set_default_route_succeeds_for_tenant_admin(self):
        from services.payment_release import handler, service

        event = {
            "requestContext": {
                "requestId": "req-wh-005",
                "http": {"method": "PATCH", "path": "/v1/warehouses/wh-002/set-default"},
                "authorizer": {"claims": {"sub": "admin-1", "custom:tenant_id": TENANT_ID}},
                "identity": {"sourceIp": "127.0.0.1"},
            },
            "headers": {},
            "body": "{}",
            "queryStringParameters": {},
            "pathParameters": {},
        }
        ctx = _ctx(UserRole.TENANT_ADMIN)
        with (
            patch("services.payment_release.handler.get_tenant_context", return_value=ctx),
            patch.object(service, "set_default_warehouse", return_value={"id": "wh-002", "is_default": True}) as mock_set,
        ):
            resp = handler.lambda_handler(event, None)

        assert resp["statusCode"] == 200
        mock_set.assert_called_once_with(TENANT_ID, "wh-002", actor_id="user-1", actor_role="tenant_admin")


class TestWarehouseUpdateAndDeactivate:
    """Service-level behaviour for the admin warehouse edit/remove operations
    added alongside the arrival-warehouse feature."""

    def test_update_patches_only_sent_fields(self):
        from services.payment_release import service
        from services.payment_release.models import UpdateWarehouseRequest

        existing = {"id": "wh-1", "name": "Lagos", "is_default": False, "is_active": True}
        req = UpdateWarehouseRequest(phone="08099999999")  # name/city/etc omitted
        with (
            patch.object(service.repo, "get_warehouse_by_id", return_value=existing),
            patch.object(service.repo, "update_warehouse", return_value={**existing, "phone": "08099999999"}) as mock_upd,
            patch("services.payment_release.service.log_audit"),
        ):
            service.update_warehouse(TENANT_ID, "wh-1", req, actor_id="u", actor_role="tenant_admin")

        # exclude_unset → only `phone` reaches the repo, nothing nulled.
        assert mock_upd.call_args.args[2] == {"phone": "08099999999"}

    def test_update_unknown_warehouse_raises(self):
        from services.payment_release import service
        from services.payment_release.models import UpdateWarehouseRequest
        from shared.exceptions import ResourceNotFoundError

        with patch.object(service.repo, "get_warehouse_by_id", return_value=None):
            with pytest.raises(ResourceNotFoundError):
                service.update_warehouse(
                    TENANT_ID, "missing", UpdateWarehouseRequest(name="X"), actor_id="u", actor_role="tenant_admin"
                )

    def test_deactivate_default_is_refused(self):
        from services.payment_release import service
        from shared.exceptions import BusinessRuleViolationError

        with patch.object(
            service.repo, "get_warehouse_by_id", return_value={"id": "wh-1", "is_default": True, "is_active": True}
        ):
            with pytest.raises(BusinessRuleViolationError):
                service.deactivate_warehouse(TENANT_ID, "wh-1", actor_id="u", actor_role="tenant_admin")

    def test_deactivate_last_active_is_refused(self):
        from services.payment_release import service
        from shared.exceptions import BusinessRuleViolationError

        with (
            patch.object(
                service.repo, "get_warehouse_by_id", return_value={"id": "wh-1", "is_default": False, "is_active": True}
            ),
            patch.object(service.repo, "count_active_warehouses", return_value=1),
        ):
            with pytest.raises(BusinessRuleViolationError):
                service.deactivate_warehouse(TENANT_ID, "wh-1", actor_id="u", actor_role="tenant_admin")

    def test_deactivate_non_default_succeeds(self):
        from services.payment_release import service

        existing = {"id": "wh-2", "is_default": False, "is_active": True}
        with (
            patch.object(service.repo, "get_warehouse_by_id", return_value=existing),
            patch.object(service.repo, "count_active_warehouses", return_value=3),
            patch.object(service.repo, "update_warehouse", return_value={**existing, "is_active": False}) as mock_upd,
            patch("services.payment_release.service.log_audit"),
        ):
            result = service.deactivate_warehouse(TENANT_ID, "wh-2", actor_id="u", actor_role="tenant_admin")

        assert mock_upd.call_args.args[2] == {"is_active": False}
        assert result["is_active"] is False
