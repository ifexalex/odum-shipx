"""The address a request really came from.

Two things go wrong without this. `requestContext.identity.sourceIp` is the REST API (v1) location; the
HTTP API (payload 2.0) this runs behind on AWS puts it at `requestContext.http.sourceIp`, so reading only
the first recorded no address in production at all. And behind a reverse proxy the socket peer is the proxy,
so keying anything on it (audit logs, rate limits) lumps every user into one.

`resolve_client_ip` is for the container deployment, which has proxies in front of it (Front Door, then the
Container Apps ingress). It trusts only the entries those proxies themselves appended to `X-Forwarded-For`:
a client can put anything at the front of that header, never at the end.
"""

import ipaddress
import os
from typing import Any

# How many proxies in front of the app each append the address they received the connection from.
# 0 (the default) means there are none we know about, so the socket peer is the client.
TRUSTED_PROXY_HOPS_ENV = "TRUSTED_PROXY_HOPS"


def client_ip(event: dict[str, Any]) -> str | None:
    """Return the client address recorded on an API Gateway proxy event, or None if there is none."""
    context = event.get("requestContext") or {}
    for section in ("http", "identity"):
        value = (context.get(section) or {}).get("sourceIp")
        if value:
            return str(value)
    return None


def _valid(address: str) -> bool:
    try:
        ipaddress.ip_address(address)
    except ValueError:
        return False
    return True


def trusted_proxy_hops() -> int:
    """Read TRUSTED_PROXY_HOPS; a missing, non-numeric or negative value means 0."""
    try:
        return max(int(os.environ.get(TRUSTED_PROXY_HOPS_ENV, "0")), 0)
    except ValueError:
        return 0


def resolve_client_ip(peer: str, forwarded_for: str, trusted_hops: int) -> str | None:
    """Work out the client's address, or return None when it cannot be told safely.

    Args:
        peer: The socket peer, which is the nearest proxy when there is one.
        forwarded_for: The `X-Forwarded-For` header, or "".
        trusted_hops: How many proxies in front of the app append to that header.

    With `trusted_hops` proxies the client is that many entries from the end: anything before it was
    supplied by the client and is ignored. With none configured the peer is the client, unless the request
    carries `X-Forwarded-For` and the peer is not a public address: that is a proxy nobody told us about,
    and answering with its address would make every user look like one client, so say "unknown" instead.
    """
    if trusted_hops > 0:
        entries = [entry.strip() for entry in forwarded_for.split(",") if entry.strip()]
        if len(entries) >= trusted_hops and _valid(entries[-trusted_hops]):
            return entries[-trusted_hops]
        return None
    if not _valid(peer):
        return None
    if forwarded_for and not ipaddress.ip_address(peer).is_global:
        return None
    return peer
