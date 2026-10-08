"""Verified TLS context for outbound HTTP calls made via urllib.

Extracted from services/payment_release/paystack.py once a second call site
(shared/fx_rate.py) needed the exact same context — sharing it here instead
of duplicating it a second time.
"""

import ssl


def verified_ssl_context() -> ssl.SSLContext:
    """Verified TLS context. Prefers certifi's CA bundle when available —
    python.org macOS builds ship without system CA certs wired up, which
    breaks local dev; Lambda's runtime has them, and botocore already pulls
    certifi in as a dependency. Verification is never disabled."""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()
