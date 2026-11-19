"""The address a request really came from.

Two things go wrong without this. `requestContext.identity.sourceIp` is the REST API (v1) location; the
HTTP API (payload 2.0) this runs behind on AWS puts it at `requestContext.http.sourceIp`, so reading only
the first recorded no address in production at all. And behind a reverse proxy the socket peer is the proxy,
so keying anything on it (audit logs, rate limits) lumps every user into one.

`resolve_edge_client_ip` is for the container deployment, which sits behind Azure Front Door and then the
Container Apps ingress. It does not count proxies. Front Door stamps every request it forwards with its own id
(`X-Azure-FDID`) and with the address of the connection it accepted (`X-Azure-SocketIP`), so a request that
carries *our* Front Door's id is taken at Front Door's word for the address. A request that does not carry it
reached the ingress some other way, and its headers are not believed: it falls back to `resolve_client_ip`,
which trusts only the entries known proxies appended to `X-Forwarded-For` (a client can put anything at the
front of that header, never at the end) and otherwise answers "unknown".
"""

import hmac
import ipaddress
import os
from typing import Any, Protocol

# How many proxies in front of the app each append the address they received the connection from.
# 0 (the default) means there are none we know about, so the socket peer is the client.
TRUSTED_PROXY_HOPS_ENV = "TRUSTED_PROXY_HOPS"


class Headers(Protocol):
    """Request headers, looked up case-insensitively: a Flask/Werkzeug `Headers`, or any mapping that does the same."""

    def get(self, key: str, /) -> Any: ...


# The id of this deployment's Front Door profile, as Front Door sends it in `X-Azure-FDID`. Unset (AWS, local
# dev, or a deployment with no Front Door) switches the Front Door path off.
FRONT_DOOR_ID_ENV = "AZURE_FRONT_DOOR_ID"
# "true" refuses API requests that did not come through that Front Door (services/http_app). Off by default:
# anything configured to call the container app's own hostname (a payment webhook, a smoke test) would break.
REQUIRE_FRONT_DOOR_ENV = "REQUIRE_FRONT_DOOR"


def front_door_id() -> str:
    """This deployment's Front Door id, or "" when there is none."""
    return os.environ.get(FRONT_DOOR_ID_ENV, "").strip()


def came_through_front_door(headers: Headers) -> bool:
    """Did our own Front Door forward this request? False when no Front Door id is configured."""
    expected = front_door_id()
    presented = str(headers.get("X-Azure-FDID") or "").strip()
    return bool(expected) and hmac.compare_digest(presented.lower(), expected.lower())


def front_door_required() -> bool:
    """Should requests that bypass Front Door be refused? Only meaningful when a Front Door id is configured."""
    return bool(front_door_id()) and os.environ.get(REQUIRE_FRONT_DOOR_ENV, "").strip().lower() == "true"


def resolve_edge_client_ip(peer: str, headers: Headers) -> str | None:
    """The client's address for a request to the container deployment, or None when it cannot be told safely.

    Through our Front Door: the address Front Door accepted the connection from (`X-Azure-SocketIP`), which
    the client cannot influence, unlike `X-Forwarded-For` and `X-Azure-ClientIP`. Otherwise: whatever
    `resolve_client_ip` can establish from the socket peer and `TRUSTED_PROXY_HOPS`, which by default is
    "unknown" for a request that arrives through a proxy nobody vouched for.
    """
    if came_through_front_door(headers):
        socket_ip = str(headers.get("X-Azure-SocketIP") or "").strip()
        return socket_ip if _valid(socket_ip) else None
    return resolve_client_ip(peer, str(headers.get("X-Forwarded-For") or ""), trusted_proxy_hops())


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
