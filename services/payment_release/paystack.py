"""Paystack transaction initialization + verification (audit gap B12 —
customer pay-online).

The customer's browser is redirected to Paystack's hosted checkout
(`authorization_url`); the HMAC-verified webhook (`POST /v1/webhooks/payment`
→ webhook.py) is the primary source of truth for the actual payment, never
the browser redirect by itself.

**Ground-truth gap found live (2026-09-19):** that webhook can only ever
reach a publicly-addressable URL — Paystack's servers cannot call
`http://localhost:3000`, so in local dev the webhook *never* fires at all,
and even in production a webhook can be delayed, retried, or lost. The
customer saw Paystack's own "successful" page, but our own billing record
never updated: clicking "View invoice" showed the bill as still unpaid, and
"Pay" was still there, offering to charge them again. `verify_transaction()`
below is the fix — a direct, synchronous call to Paystack's own
`GET /transaction/verify/:reference`, made when the customer's browser lands
back on our `callback_url` (services/payment_release/service.py's
`confirm_online_payment`), so the payment is reconciled immediately rather
than only if/when a webhook happens to arrive. Both paths ultimately call
the same `service.process_webhook_payment()`, and `gateway_transaction_id`'s
`ON CONFLICT DO NOTHING` (repository.create_webhook_payment_record) makes
running both harmless — whichever gets there first wins, the other is a
no-op.

Secret handling (2026-07-19 — multi-tenant Paystack): each tenant connects
their own Paystack secret key (services/tenant_management, stored encrypted
in tenant_config under 'paystack_config') so customer payments land directly
in that tenant's own account — there is no platform-wide key. The secret is
always passed in by the caller (services/payment_release/service.py, which
resolves it via repository.get_tenant_paystack_secret), never read from an
env var here. Paystack signs webhooks with this same secret key — see
webhook.py.
"""

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
import uuid
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from shared.exceptions import ExternalServiceError
from shared.ssl_context import verified_ssl_context as _ssl_context

logger = logging.getLogger(__name__)

_PAYSTACK_INITIALIZE_URL = "https://api.paystack.co/transaction/initialize"
_PAYSTACK_VERIFY_URL = "https://api.paystack.co/transaction/verify/"
_PAYSTACK_TEST_URL = "https://api.paystack.co/transaction?perPage=1"
_TIMEOUT_SECONDS = 15

#: Invoices are in naira and every checkout we open asks for naira, so that is the only currency a charge is applied in.
SETTLEMENT_CURRENCY = "NGN"
_KOBO_PER_NAIRA = Decimal("100")


def charge_amount_ngn(data: dict[str, Any]) -> Decimal | None:
    """The naira value of a Paystack charge, or ``None`` if the charge must not be applied to an invoice.

    Paystack reports ``amount`` in the smallest unit of ``currency``. Reading it as kobo without looking at the
    currency turned a charge of 100.00 in any other currency into ₦100.00 paid. A charge in another currency, with no
    currency, or with an amount that is not a positive number is refused here and logged; both the webhook and the
    verify call read the amount through this function.

    Args:
        data: The ``data`` object of a ``charge.success`` webhook or of a verify response.

    Returns:
        The amount in naira, or ``None`` when the charge is not a positive naira amount.
    """
    # Values below come from a payload that may not have been authenticated yet: log them cut short and quoted.
    gateway_id = str(data.get("id", ""))[:40]
    currency = str(data.get("currency") or "").strip().upper()
    if currency != SETTLEMENT_CURRENCY:
        logger.warning("Ignoring Paystack charge %r: currency %r is not %s", gateway_id, currency[:8], SETTLEMENT_CURRENCY)
        return None
    try:
        amount_kobo = Decimal(str(data.get("amount")))
    except InvalidOperation:
        logger.warning("Ignoring Paystack charge %r: amount is not a number", gateway_id)
        return None
    if not amount_kobo.is_finite() or amount_kobo <= 0:
        logger.warning("Ignoring Paystack charge %r: amount is not positive", gateway_id)
        return None
    return amount_kobo / _KOBO_PER_NAIRA


def build_reference(billing_id: str) -> str:
    """Unique per attempt: `{billing_id}.{nonce}`.

    Paystack rejects duplicate references, so a bare billing UUID would make a
    retried payment (after an abandoned/failed attempt) impossible. webhook.py
    strips the `.{nonce}` suffix to recover the billing id. Separator is `.`
    because Paystack only accepts alphanumerics and `-.=` in references
    (verified against the live API), and `.` cannot appear inside a UUID.
    """
    return f"{billing_id}.{uuid.uuid4().hex[:10]}"


def initialize_transaction(
    *,
    secret_key: str,
    email: str,
    amount_ngn: Decimal,
    billing_id: str,
    callback_url: str | None,
    tenant_id: str,
    request_id: str = "",
) -> dict[str, Any]:
    """Create a Paystack checkout session; returns authorization_url + reference.

    `secret_key` is the calling tenant's own Paystack secret key (resolved by
    the caller — see module docstring) — the caller is responsible for
    raising PAYMENT_GATEWAY_NOT_CONFIGURED before reaching here if the
    tenant hasn't connected a key.

    Raises:
        ExternalServiceError: Paystack rejected the request or is unreachable.
    """
    amount_kobo = int((amount_ngn * _KOBO_PER_NAIRA).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    reference = build_reference(billing_id)

    body: dict[str, Any] = {
        "email": email,
        "amount": amount_kobo,
        "currency": "NGN",
        "reference": reference,
        "metadata": {"billing_id": billing_id, "tenant_id": tenant_id, "request_id": request_id},
    }
    if callback_url:
        body["callback_url"] = callback_url

    req = urllib.request.Request(
        _PAYSTACK_INITIALIZE_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {secret_key}",
            "Content-Type": "application/json",
            # Paystack sits behind Cloudflare, which rejects urllib's default
            # UA ("Python-urllib/…") with error 1010 — identify ourselves.
            "User-Agent": "ShipX-Logistics/1.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS, context=_ssl_context()) as resp:  # noqa: S310 — fixed https URL
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        logger.warning("Paystack initialize rejected (%s): %s", exc.code, detail)
        raise ExternalServiceError("Paystack", f"initialize failed with HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        logger.warning("Paystack unreachable: %s", exc)
        raise ExternalServiceError("Paystack", "gateway unreachable") from exc

    if not payload.get("status") or "data" not in payload:
        raise ExternalServiceError("Paystack", payload.get("message", "initialize returned no data"))

    data = payload["data"]
    return {
        "authorization_url": data["authorization_url"],
        "access_code": data.get("access_code", ""),
        "reference": reference,
        "amount_ngn": str(amount_ngn),
    }


def verify_transaction(secret_key: str, reference: str) -> dict[str, Any]:
    """Ask Paystack directly whether `reference` actually succeeded.

    Returns the raw `data` object from Paystack's response — same shape
    `webhook.py::extract_paystack_payment` reads out of a webhook payload
    (`status`, `amount` in kobo, `reference`, `id`) — so both paths can feed
    the same extraction/confirmation logic.

    Raises:
        ExternalServiceError: Paystack rejected the request or is unreachable.
    """
    req = urllib.request.Request(
        _PAYSTACK_VERIFY_URL + urllib.parse.quote(reference, safe=""),
        headers={
            "Authorization": f"Bearer {secret_key}",
            "User-Agent": "ShipX-Logistics/1.0",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS, context=_ssl_context()) as resp:  # noqa: S310 — fixed https URL
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        logger.warning("Paystack verify rejected (%s) for reference=%s: %s", exc.code, reference, detail)
        raise ExternalServiceError("Paystack", f"verify failed with HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        logger.warning("Paystack unreachable during verify: %s", exc)
        raise ExternalServiceError("Paystack", "gateway unreachable") from exc

    if not payload.get("status") or "data" not in payload:
        raise ExternalServiceError("Paystack", payload.get("message", "verify returned no data"))

    return payload["data"]  # type: ignore[no-any-return]


def test_connection(secret_key: str) -> None:
    """Verify a Paystack secret key actually works with a live, harmless call.

    Unlike a shape-only validation, this proves the key is accepted by
    Paystack — GET /transaction (list, capped to 1 row) is read-only and
    touches no real transaction. Used by the tenant-admin "Test connection"
    action after saving a new key.

    Raises:
        ExternalServiceError: Paystack rejected the key or is unreachable —
            the exception message is safe to surface to the tenant_admin.
    """
    req = urllib.request.Request(
        _PAYSTACK_TEST_URL,
        headers={
            "Authorization": f"Bearer {secret_key}",
            "User-Agent": "ShipX-Logistics/1.0",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS, context=_ssl_context()) as resp:  # noqa: S310 — fixed https URL
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise ExternalServiceError("Paystack", "Paystack rejected this key — check it's correct and active") from exc
        raise ExternalServiceError("Paystack", f"connection test failed with HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise ExternalServiceError("Paystack", "gateway unreachable") from exc

    if not payload.get("status"):
        raise ExternalServiceError("Paystack", payload.get("message", "connection test failed"))
