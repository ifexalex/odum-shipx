"""SSRF defence for outbound calls to tenant-supplied URLs (webhooks).

A tenant admin controls `webhook_config.endpoint_url`, and the Lambda that
fetches it runs inside the VPC beside Aurora/Redis. `^https://` alone does
not stop `https://169.254.169.254/...`, `https://10.0.3.7/...`,
`https://localhost/...`, a hostname whose DNS record points at any of those,
or a public server that answers with a 302 to one. Three layers close this:

1. `validate_public_https_url` — syntactic, no network I/O; safe to call from
   a Pydantic validator at save time.
2. `resolve_public_ips` — resolves the host at delivery time and refuses if
   *any* address is non-public (DNS records change after save).
3. `open_public_https` — connects to the exact IP that was just validated
   (TLS is still verified against the original hostname), disables proxies,
   and refuses redirects, so nothing can swap the target after the check.
"""

import http.client
import ipaddress
import socket
import urllib.request
from typing import Any
from urllib.parse import urlsplit

from shared.ssl_context import verified_ssl_context

_BLOCKED_HOST_SUFFIXES = (".localhost", ".local", ".internal", ".intranet", ".lan", ".home.arpa")


class UnsafeUrlError(ValueError):
    """The URL targets something other than a public https endpoint."""


def _is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def _literal_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Parse `host` as an IP literal, including the legacy numeric IPv4 forms
    (`2130706433`, `0x7f.1`, `127.1`) that resolvers accept but `ipaddress` rejects."""
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    try:
        return ipaddress.IPv4Address(socket.inet_aton(host))
    except OSError:
        return None


def validate_public_https_url(url: str) -> tuple[str, int]:
    """Syntactic check (no DNS). Returns `(hostname, port)` or raises UnsafeUrlError."""
    try:
        parts = urlsplit(url)
        port = parts.port or 443
    except ValueError as exc:
        raise UnsafeUrlError("Endpoint URL is not a valid URL") from exc

    if parts.scheme != "https":
        raise UnsafeUrlError("Endpoint URL must use https")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise UnsafeUrlError("Endpoint URL has no hostname")
    if parts.username is not None or parts.password is not None:
        raise UnsafeUrlError("Endpoint URL must not embed credentials")
    if host == "localhost" or host.endswith(_BLOCKED_HOST_SUFFIXES):
        raise UnsafeUrlError("Endpoint URL must be a public internet host")

    literal = _literal_ip(host)
    if literal is not None and not _is_public(literal):
        raise UnsafeUrlError("Endpoint URL must not point at a private or reserved address")
    return host, port


def resolve_public_ips(host: str, port: int) -> list[str]:
    """Resolve `host` and return its addresses, refusing if any is non-public."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeUrlError("Endpoint hostname could not be resolved") from exc

    addresses = list(dict.fromkeys(str(info[4][0]) for info in infos))
    if not addresses:
        raise UnsafeUrlError("Endpoint hostname could not be resolved")
    for address in addresses:
        if not _is_public(ipaddress.ip_address(address.split("%", 1)[0])):
            raise UnsafeUrlError("Endpoint hostname resolves to a private or reserved address")
    return addresses


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A 3xx surfaces as an HTTPError instead of being followed to an unvalidated target."""

    def redirect_request(self, req: Any, fp: Any, code: Any, msg: Any, headers: Any, newurl: Any) -> None:
        return None


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Connects to a pre-validated IP while keeping SNI + cert verification on the hostname."""

    def __init__(self, host: str, pinned_ips: list[str], **kwargs: Any) -> None:
        super().__init__(host, **kwargs)
        self._pinned_ips = pinned_ips
        self._tls_context = kwargs["context"]
        self._source_address = kwargs.get("source_address")

    def connect(self) -> None:
        last_error: OSError | None = None
        for ip in self._pinned_ips:
            try:
                sock = socket.create_connection((ip, self.port), self.timeout, self._source_address)
                break
            except OSError as exc:
                last_error = exc
        else:
            raise last_error or OSError("no pinned address reachable")
        self.sock = self._tls_context.wrap_socket(sock, server_hostname=self.host)


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, pinned_ips: list[str]) -> None:
        super().__init__(context=verified_ssl_context())
        self._pinned_ips = pinned_ips

    def https_open(self, req: urllib.request.Request) -> http.client.HTTPResponse:
        def make_connection(host: str, **kwargs: Any) -> _PinnedHTTPSConnection:
            return _PinnedHTTPSConnection(host, self._pinned_ips, **kwargs)

        return self.do_open(make_connection, req, context=verified_ssl_context())


def open_public_https(req: urllib.request.Request, timeout: float) -> Any:
    """`urlopen` replacement for tenant-supplied URLs. Raises UnsafeUrlError before any connection
    is made if the target isn't a public https endpoint."""
    host, port = validate_public_https_url(req.full_url)
    pinned_ips = resolve_public_ips(host, port)
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _NoRedirect,
        _PinnedHTTPSHandler(pinned_ips),
    )
    return opener.open(req, timeout=timeout)
