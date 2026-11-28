"""Plain-text email to platform admins (approval requests, sole-admin notices to owners).

Platform admins are ShipX staff, not tenant customers, but the non-production allowlist still applies
(``shared.notifications.is_recipient_allowed``): a dev or staging environment emails nobody who is not on it. Never
raises; a failed send is logged without the address.
"""

import logging
import os

from shared.notifications import is_recipient_allowed

logger = logging.getLogger(__name__)


def send_platform_email(to_email: str, subject: str, text_body: str) -> bool:
    """Send one email; return True when it was handed to the provider."""
    if not is_recipient_allowed({"email": to_email}):
        logger.info("Platform email not sent: recipient is not on the non-production allowlist")
        return False
    sender = os.environ.get("SES_FROM_ADDRESS", "").strip()
    if not sender:
        logger.warning("Platform email not sent: SES_FROM_ADDRESS is not configured")
        return False
    try:
        from shared.providers import get_email_provider

        html_body = '<pre style="font-family:inherit;white-space:pre-wrap">' + _escape(text_body) + "</pre>"
        get_email_provider().send(sender=sender, to_email=to_email, subject=subject, html_body=html_body, text_body=text_body)
        return True
    except Exception as exc:
        logger.warning("Platform email send failed: %s", type(exc).__name__)
        return False


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
