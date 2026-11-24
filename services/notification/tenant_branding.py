"""Tenant branding helpers for the Notification service.

Branding is embedded in the SQS event payload by the publishing service
(`shared/notifications.py::_tenant_branding`) so that these Lambdas can run
outside the VPC without DB access.

The keys are the canonical `branding_config` shape the frontend writes through
`PUT /v1/tenant/config {branding}`: `display_name`, `tagline`, `primary_color`,
`warehouse_address`, `pickup_hours`, `pickup_phone`, `support_email`,
`support_whatsapp`, `document_footer` — plus `company_name`, which the producer
adds from the `tenant` row.

Reading the wrong key here is silent: there is no error, every message simply
goes out branded as somebody else. `get_company_name` used to read only
`company_name`, which the canonical shape does not contain and which the
producer did not supply, so every email header, every `{company_name}:` SMS
prefix and every WhatsApp parameter was the literal word "Logistics".
"""

import re
from typing import Any

# Last resort only. Reaching this means the tenant row had no company name at
# all, which should be impossible — `company_name` is NOT NULL on `tenant`.
_FALLBACK_COMPANY_NAME = "Logistics"
_FALLBACK_PRIMARY_COLOR = "#1A5276"
_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def extract_branding(event_body: dict[str, Any]) -> dict[str, Any]:
    """Return the tenant_branding dict from a parsed SQS message body."""
    return event_body.get("tenant_branding") or {}


def _first(branding: dict[str, Any], *keys: str) -> str:
    """Return the first key present with a non-blank string value."""
    for key in keys:
        value = branding.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def get_company_name(branding: dict[str, Any]) -> str:
    """The name the recipient should see this message as coming from.

    `display_name` first — a tenant that set a trading name meant it to be what
    customers see — then the legal `company_name` from the tenant row.
    """
    return _first(branding, "display_name", "company_name") or _FALLBACK_COMPANY_NAME


def get_primary_color(branding: dict[str, Any]) -> str:
    """The tenant's brand colour, used for the email header and CTA button."""
    color = _first(branding, "primary_color")
    if color and _HEX_COLOR_RE.match(color):
        return color
    return _FALLBACK_PRIMARY_COLOR


def get_tagline(branding: dict[str, Any]) -> str:
    """Optional strapline, shown under the company name in the email header."""
    return _first(branding, "tagline")


def get_support_email(branding: dict[str, Any]) -> str:
    """Where a recipient should reply for help, if the tenant published one."""
    return _first(branding, "support_email")


def get_support_whatsapp(branding: dict[str, Any]) -> str:
    """Tenant's support WhatsApp number, if published."""
    return _first(branding, "support_whatsapp")


def get_document_footer(branding: dict[str, Any]) -> str:
    """Tenant boilerplate for the bottom of a message, if published."""
    return _first(branding, "document_footer")
