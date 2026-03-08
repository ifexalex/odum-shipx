"""Tenant branding helpers for the Notification service.

Branding is embedded in the SQS event payload by the publishing service
so that these Lambdas can run outside the VPC without DB access.
"""


def extract_branding(event_body: dict) -> dict:
    """Return the tenant_branding dict from a parsed SQS message body."""
    return event_body.get("tenant_branding") or {}


def get_company_name(branding: dict) -> str:
    return branding.get("company_name") or "Logistics"


def get_primary_color(branding: dict) -> str:
    return branding.get("primary_color") or "#1A5276"
