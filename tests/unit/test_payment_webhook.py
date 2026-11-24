"""Unit tests for services.payment_release.webhook — signature verification and payload extraction."""

import hashlib
import hmac
from decimal import Decimal
from unittest.mock import patch

import pytest


class TestVerifyPaystackSignature:
    """Multi-tenant Paystack (2026-07-19): the secret is always the resolved
    tenant's own key, passed explicitly — there is no env-var fallback."""

    def test_valid_signature_returns_true(self):
        from services.payment_release import webhook

        raw_body = b'{"event":"charge.success"}'
        expected = hmac.new(b"test-secret", raw_body, hashlib.sha512).hexdigest()
        assert webhook.verify_paystack_signature(raw_body, expected, "test-secret") is True

    def test_tampered_body_returns_false(self):
        from services.payment_release import webhook

        raw_body = b'{"event":"charge.success"}'
        sig = hmac.new(b"test-secret", raw_body, hashlib.sha512).hexdigest()
        assert webhook.verify_paystack_signature(b'{"event":"charge.success","tampered":true}', sig, "test-secret") is False

    def test_wrong_tenants_key_returns_false(self):
        """The exact scenario the reorder is meant to prevent: a signature
        valid under tenant B's key must not verify against tenant A's."""
        from services.payment_release import webhook

        raw_body = b'{"event":"charge.success"}'
        sig_signed_with_b = hmac.new(b"tenant-b-secret", raw_body, hashlib.sha512).hexdigest()
        assert webhook.verify_paystack_signature(raw_body, sig_signed_with_b, "tenant-a-secret") is False

    def test_empty_secret_returns_false(self):
        from services.payment_release import webhook

        assert webhook.verify_paystack_signature(b"body", "any-sig", "") is False


class TestVerifyFlutterwaveSignature:
    def test_matching_secret_returns_true(self, monkeypatch):
        monkeypatch.setenv("FLUTTERWAVE_WEBHOOK_SECRET", "fw-secret-abc")
        from services.payment_release import webhook

        assert webhook.verify_flutterwave_signature("fw-secret-abc") is True

    def test_wrong_secret_returns_false(self, monkeypatch):
        monkeypatch.setenv("FLUTTERWAVE_WEBHOOK_SECRET", "fw-secret-abc")
        from services.payment_release import webhook

        assert webhook.verify_flutterwave_signature("wrong-secret") is False

    def test_missing_env_var_returns_false(self, monkeypatch):
        monkeypatch.delenv("FLUTTERWAVE_WEBHOOK_SECRET", raising=False)
        from services.payment_release import webhook

        assert webhook.verify_flutterwave_signature("any-hash") is False


class TestExtractPaystackPayment:
    def _payload(self, event: str = "charge.success", status: str = "success", amount_kobo: int = 5000000) -> dict:
        return {
            "event": event,
            "data": {
                "status": status,
                "reference": "billing-uuid-001",
                "amount": amount_kobo,
                "currency": "NGN",
                "id": "paystack-tx-99",
            },
        }

    def test_successful_charge_returns_dict_with_ngn_amount(self):
        from services.payment_release import webhook

        result = webhook.extract_paystack_payment(self._payload(amount_kobo=5000000))

        assert result is not None
        assert result["amount_ngn"] == Decimal("50000.00")
        assert result["billing_id"] == "billing-uuid-001"
        assert result["payment_method"] == "paystack"
        assert result["gateway_transaction_id"] == "paystack-tx-99"

    def test_non_success_event_type_returns_none(self):
        from services.payment_release import webhook

        result = webhook.extract_paystack_payment(self._payload(event="charge.failed"))
        assert result is None

    def test_non_success_status_returns_none(self):
        from services.payment_release import webhook

        result = webhook.extract_paystack_payment(self._payload(status="failed"))
        assert result is None


class TestExtractFlutterwavePayment:
    def _payload(
        self, event: str = "charge.completed", status: str = "successful", amount: int = 50000, currency: str = "NGN"
    ) -> dict:
        return {
            "event": event,
            "data": {
                "status": status,
                "tx_ref": "billing-uuid-002",
                "amount": amount,
                "currency": currency,
                "id": 12345,
            },
        }

    def test_successful_ngn_charge_returns_dict(self):
        from services.payment_release import webhook

        result = webhook.extract_flutterwave_payment(self._payload(amount=75000))

        assert result is not None
        assert result["amount_ngn"] == Decimal("75000")
        assert result["billing_id"] == "billing-uuid-002"
        assert result["payment_method"] == "flutterwave"
        assert result["gateway_transaction_id"] == "12345"

    def test_non_ngn_currency_returns_none(self):
        from services.payment_release import webhook

        result = webhook.extract_flutterwave_payment(self._payload(currency="USD"))
        assert result is None

    def test_non_successful_status_returns_none(self):
        from services.payment_release import webhook

        result = webhook.extract_flutterwave_payment(self._payload(status="failed"))
        assert result is None

    def test_non_payment_event_type_returns_none(self):
        from services.payment_release import webhook

        result = webhook.extract_flutterwave_payment(self._payload(event="transfer.completed"))
        assert result is None


# ---------------------------------------------------------------------------
# B12 — retry-safe reference format "{billing_id}.{nonce}" (paystack.py issues
# them; the webhook must recover the billing id from either format)
# ---------------------------------------------------------------------------


class TestPaystackReferenceParsing:
    def _payload(self, reference: str) -> dict:
        return {
            "event": "charge.success",
            "data": {"status": "success", "reference": reference, "amount": 100000, "currency": "NGN", "id": 12345},
        }

    def test_suffixed_reference_recovers_billing_id(self):
        from services.payment_release import webhook

        result = webhook.extract_paystack_payment(self._payload("billing-uuid-001.a1b2c3d4e5"))
        assert result is not None
        assert result["billing_id"] == "billing-uuid-001"

    def test_bare_reference_still_parses(self):
        from services.payment_release import webhook

        result = webhook.extract_paystack_payment(self._payload("billing-uuid-001"))
        assert result is not None
        assert result["billing_id"] == "billing-uuid-001"


# ---------------------------------------------------------------------------
# Audit BE-08 — a Paystack charge is applied only if it is a positive naira amount
# ---------------------------------------------------------------------------


class TestPaystackChargeAmount:
    """`amount` is in the smallest unit of `currency`. It was read as kobo whatever the currency said."""

    @staticmethod
    def _amount(**data) -> Decimal | None:
        from services.payment_release import paystack

        return paystack.charge_amount_ngn({"id": 1, **data})

    def test_kobo_become_naira(self):
        assert self._amount(amount=5000000, currency="NGN") == Decimal("50000")

    @pytest.mark.parametrize("currency", ["USD", "GHS", "ZAR", "KES", "", None, "NGNX", 566])
    def test_any_other_currency_or_none_at_all_is_refused(self, currency):
        assert self._amount(amount=5000000, currency=currency) is None

    def test_a_missing_currency_field_is_refused(self):
        assert self._amount(amount=5000000) is None

    @pytest.mark.parametrize("currency", ["ngn", " NGN "])
    def test_the_currency_code_is_matched_whatever_its_case_or_padding(self, currency):
        assert self._amount(amount=100, currency=currency) == Decimal("1")

    @pytest.mark.parametrize("amount", [0, -100, "-0.01", None, "abc", "", "NaN", "Infinity", True, [100]])
    def test_an_amount_that_is_not_a_positive_number_is_refused(self, amount):
        assert self._amount(amount=amount, currency="NGN") is None

    def test_a_refused_charge_is_logged_without_echoing_the_payload(self, caplog):
        with caplog.at_level("WARNING"):
            self._amount(amount=100, currency="USD-" + "x" * 500, id="tx-" + "y" * 500)
        [record] = caplog.records
        assert "is not NGN" in record.getMessage() and len(record.getMessage()) < 160


class TestExtractPaystackPaymentCurrency:
    @staticmethod
    def _payload(**data) -> dict:
        return {"event": "charge.success", "data": {"status": "success", "reference": "billing-uuid-001", "id": 7, **data}}

    def test_a_usd_charge_is_not_a_payment(self):
        from services.payment_release import webhook

        assert webhook.extract_paystack_payment(self._payload(amount=10000, currency="USD")) is None

    def test_a_zero_or_negative_naira_charge_is_not_a_payment(self):
        from services.payment_release import webhook

        assert webhook.extract_paystack_payment(self._payload(amount=0, currency="NGN")) is None
        assert webhook.extract_paystack_payment(self._payload(amount=-5000, currency="NGN")) is None

    def test_flutterwave_refuses_a_non_positive_or_malformed_amount_too(self):
        from services.payment_release import webhook

        def payload(amount):
            data = {"status": "successful", "tx_ref": "b-2", "amount": amount, "currency": "NGN", "id": 1}
            return {"event": "charge.completed", "data": data}

        assert webhook.extract_flutterwave_payment(payload(0)) is None
        assert webhook.extract_flutterwave_payment(payload(-1)) is None
        assert webhook.extract_flutterwave_payment(payload("abc")) is None
        assert webhook.extract_flutterwave_payment(payload(2500))["amount_ngn"] == Decimal("2500")


class TestASignedEventInAnotherCurrencyDoesNotChangeTheInvoice:
    """The brief's acceptance test: a correctly signed USD `charge.success` leaves the invoice alone.

    The control case sends the same event in naira through the same signature check, so a pass here is not the
    signature failing.
    """

    SECRET = "sk_test_tenant_secret"  # noqa: S105 - a made-up test key
    BILLING_ID = "44444444-4444-4444-4444-444444444444"

    def _deliver(self, currency: str, amount_minor_units: int = 2500000):
        import hashlib
        import hmac
        import json

        from services.payment_release import handler

        body = json.dumps(
            {
                "event": "charge.success",
                "data": {
                    "status": "success",
                    "reference": f"{self.BILLING_ID}.abc123",
                    "amount": amount_minor_units,
                    "currency": currency,
                    "id": 9001,
                },
            }
        )
        signature = hmac.new(self.SECRET.encode(), body.encode(), hashlib.sha512).hexdigest()
        event = {"headers": {"x-paystack-signature": signature}, "body": body}
        with (
            patch.object(handler.wh, "get_billing_tenant", return_value="tenant-1"),
            patch.object(handler.repo, "get_tenant_paystack_secret", return_value=self.SECRET),
            patch.object(handler.service, "process_webhook_payment", return_value={"new_payment_status": "paid"}) as process,
        ):
            response = handler._webhook_routes(event, ["v1", "webhooks", "payment"], "POST", "req-1")
        return response, process

    def test_a_signed_usd_event_records_no_payment(self):
        response, process = self._deliver("USD")
        process.assert_not_called()
        assert response == {"statusCode": 200, "body": ""}  # acknowledged, so Paystack does not retry it for days

    def test_the_same_event_in_naira_is_recorded(self):
        _, process = self._deliver("NGN")
        process.assert_called_once()
        assert process.call_args.kwargs["amount_ngn"] == Decimal("25000")
        assert process.call_args.kwargs["billing_id"] == self.BILLING_ID

    def test_a_signed_event_with_a_non_positive_amount_records_no_payment(self):
        _, process = self._deliver("NGN", amount_minor_units=0)
        process.assert_not_called()
