"""Phone number normalisation, shared across every customer write path.

Previously `_normalize_phone` lived only in `services/excel/service.py` and
only stripped non-digit characters — it never canonicalised a local-format
number against its international equivalent, so `08012345678` (as typed by
staff or a customer) and `+2348012345678` (as a manifest sometimes carries
it) were treated as two different customers. `services/tenant_management`
also stored phones verbatim, so self-registered and admin-created rows never
matched imported ones either.

This module canonicalises to E.164 using the tenant's destination-country
dial code, and is the single normaliser every customer write path
(manifest import, tenant_management create/update, self-registration,
invite acceptance) must call before a phone number reaches the database.
"""

import re

# Destination-country name -> E.164 dial code (no leading '+'). Covers the
# countries this platform currently onboards tenants in; extend as new
# destination markets are added (see tenant.destination_country).
_DIAL_CODES: dict[str, str] = {
    "nigeria": "234",
    "ghana": "233",
    "kenya": "254",
    "china": "86",
    "south africa": "27",
    "united kingdom": "44",
    "united states": "1",
}

# Nigeria — this platform's primary destination market — is the fallback
# when a tenant's destination_country is missing or unrecognised.
DEFAULT_DIAL_CODE = "234"


def dial_code_for_country(country: str | None) -> str:
    """Return the E.164 dial code (no leading '+') for a destination-country name.

    Falls back to `DEFAULT_DIAL_CODE` for missing or unrecognised input rather
    than raising — phone normalisation must never block a write because a
    tenant's country field is blank or spelled unexpectedly.
    """
    if not country:
        return DEFAULT_DIAL_CODE
    return _DIAL_CODES.get(country.strip().lower(), DEFAULT_DIAL_CODE)


def normalize_phone(raw: str | None, dial_code: str = DEFAULT_DIAL_CODE) -> str | None:
    """Canonicalise a phone number to E.164, e.g. `+2348012345678`.

    Handles the two shapes manifests, forms, and staff input produce:
      - Already-international (`"+234 801 234 5678"`, `"2348012345678"`):
        kept, digits-only, with a leading `+`.
      - Local/trunk format (`"08012345678"`): the trunk `0` is stripped and
        `dial_code` is prepended.

    Args:
        raw: The raw phone string as entered/imported.
        dial_code: E.164 dial code (no leading '+') to apply to local-format
            numbers, normally the tenant's destination-country dial code
            from `dial_code_for_country`.

    Returns:
        The E.164-formatted number, or None if `raw` is blank/unparseable.
    """
    if not raw:
        return None
    text = raw.strip()
    if not text:
        return None
    digits = re.sub(r"[^\d]", "", text)
    if not digits:
        return None
    if text.startswith("+"):
        return f"+{digits}"
    if digits.startswith(dial_code):
        return f"+{digits}"
    if digits.startswith("0"):
        digits = digits[1:]
    return f"+{dial_code}{digits}"


def mask_phone(phone: str | None) -> str | None:
    """Mask a phone number for storage/logging where only a hint is needed.

    e.g. `+2348012345678` -> `+23480****678`. Used by `customer_invite`
    (sent_to_masked) so no raw PII sits in that table.
    """
    if not phone:
        return None
    if len(phone) <= 8:
        return "*" * len(phone)
    return f"{phone[:6]}****{phone[-3:]}"
