"""Unit tests for services.payment_release.webhook — signature verification and payload extraction."""

import hashlib
import hmac
from decimal import Decimal


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
            "data": {"status": "success", "reference": reference, "amount": 100000, "id": 12345},
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
