"""Payment gateway webhook processing.

Supports Paystack and Flutterwave. Verifies HMAC signatures before processing.

Paystack (2026-07-19 — multi-tenant): each tenant connects their own
Paystack secret key (services/tenant_management, encrypted in tenant_config
under 'paystack_config') — there is no platform-wide key, so signature
verification can no longer happen before a tenant is known. handler.py's
_webhook_routes() resolves the tenant FIRST (billing_id → tenant_id via
get_billing_tenant(), a harmless read of the billing reference — no secret
required) and only then calls verify_paystack_signature() with that
specific tenant's key. This is a stricter invariant than a shared key ever
gave us: a signature is only ever accepted against the exact tenant its
reference claims to belong to, so a leaked key from one tenant can't be used
to forge a payment confirmation against another tenant's billing.

Flutterwave is unused (no frontend integration) and stays on its original
single env-var secret (FLUTTERWAVE_WEBHOOK_SECRET) — out of scope for the
Paystack multi-tenant migration.

The payment reference stored in the gateway must equal the billing UUID so
handler.py can look it up across tenants using PLATFORM scope.
"""

import hashlib
import hmac
import logging
import os
from decimal import Decimal, InvalidOperation
from typing import Any

from shared.db import execute_with_tenant
from shared.exceptions import BusinessRuleViolationError
from shared.tenant_context import PLATFORM_TENANT_ID

from . import paystack

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# HMAC signature verification
# ---------------------------------------------------------------------------


def verify_paystack_signature(raw_body: bytes, signature_header: str, secret: str) -> bool:
    """Verify Paystack HMAC-SHA512 signature against a specific tenant's key.

    Paystack sends: X-Paystack-Signature = HMAC-SHA512(secret, raw_body)

    `secret` is the resolved tenant's own Paystack secret key (see module
    docstring) — the caller must resolve it via the billing_id in the
    payload *before* calling this, there is no fallback secret.
    """
    if not secret:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def verify_flutterwave_signature(hash_header: str) -> bool:
    """Verify Flutterwave verif-hash (simple secret comparison).

    Flutterwave sends: verif-hash = <secret_hash configured on dashboard>
    """
    secret = os.environ.get("FLUTTERWAVE_WEBHOOK_SECRET", "")
    if not secret:
        logger.warning("FLUTTERWAVE_WEBHOOK_SECRET not set — rejecting webhook")
        return False
    return hmac.compare_digest(secret, hash_header)


# ---------------------------------------------------------------------------
# Payload extraction
# ---------------------------------------------------------------------------


def extract_paystack_payment(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Extract billing_id, amount_ngn, and reference from a Paystack charge event.

    Returns None if the event is not a successful charge, or if the charge is not a positive naira amount
    (`paystack.charge_amount_ngn`): a charge in another currency must never be read as naira.
    """
    event = payload.get("event", "")
    if event != "charge.success":
        logger.info("Ignoring Paystack event type: %s", event)
        return None

    data = payload.get("data") or {}
    if data.get("status") != "success":
        return None

    amount_ngn = paystack.charge_amount_ngn(data)
    if amount_ngn is None:
        return None
    reference = str(data.get("reference", ""))

    # References are issued as "{billing_id}.{nonce}" (paystack.py) so a
    # customer can retry after an abandoned attempt — Paystack rejects
    # duplicate references (and only allows alphanumerics + "-.=", hence the
    # dot separator). Bare billing-UUID references still parse.
    billing_id = reference.split(".", 1)[0]

    return {
        "billing_id": billing_id,
        "amount_ngn": amount_ngn,
        "payment_method": "paystack",
        "payment_reference": reference,
        "gateway_transaction_id": data.get("id", ""),
    }


def extract_flutterwave_payment(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Extract billing_id, amount_ngn, and reference from a Flutterwave event.

    Returns None if the event is not a successful charge.
    """
    event = payload.get("event", "")
    if event != "charge.completed":
        logger.info("Ignoring Flutterwave event type: %s", event)
        return None

    data = payload.get("data") or {}
    if data.get("status") != "successful":
        return None

    tx_ref = data.get("tx_ref", "")
    currency = str(data.get("currency") or "")
    if currency != paystack.SETTLEMENT_CURRENCY:
        logger.warning("Unexpected Flutterwave currency: %r — skipping", currency[:8])
        return None
    try:
        amount_ngn = Decimal(str(data.get("amount")))
    except InvalidOperation:
        logger.warning("Ignoring Flutterwave charge: amount is not a number")
        return None
    if not amount_ngn.is_finite() or amount_ngn <= 0:
        logger.warning("Ignoring Flutterwave charge: amount is not positive")
        return None

    return {
        "billing_id": tx_ref,
        "amount_ngn": amount_ngn,
        "payment_method": "flutterwave",
        "payment_reference": tx_ref,
        "gateway_transaction_id": str(data.get("id", "")),
    }


# ---------------------------------------------------------------------------
# Cross-tenant billing lookup (platform scope)
# ---------------------------------------------------------------------------


def get_billing_tenant(billing_id: str) -> str | None:
    """Look up tenant_id for a billing record using PLATFORM scope.

    Returns tenant_id or None if the billing record doesn't exist.
    """
    rows = execute_with_tenant(
        PLATFORM_TENANT_ID,
        "SELECT tenant_id FROM billing WHERE id = %s LIMIT 1",
        (billing_id,),
    )
    if not rows:
        return None
    return str(rows[0]["tenant_id"])


# ---------------------------------------------------------------------------
# Duplicate payment guard
# ---------------------------------------------------------------------------


def is_duplicate_gateway_transaction(tenant_id: str, gateway_transaction_id: str) -> bool:
    """Check if a gateway transaction ID has already been recorded.

    Prevents double-processing if the gateway sends the same webhook twice.
    """
    rows = execute_with_tenant(
        tenant_id,
        """
        SELECT 1 FROM payment_record
        WHERE tenant_id = %s AND gateway_transaction_id = %s
        LIMIT 1
        """,
        (tenant_id, gateway_transaction_id),
    )
    return bool(rows)


def validate_billing_for_webhook(billing: dict[str, Any], billing_id: str) -> None:
    """Raise BusinessRuleViolationError if billing cannot accept a webhook payment."""
    if billing["status"] in {"cancelled", "waived"}:
        raise BusinessRuleViolationError(
            f"Billing {billing_id} is '{billing['status']}' and cannot accept payments.",
            rule_id="BR-WEBHOOK-001",
        )
