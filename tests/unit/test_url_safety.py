"""SSRF defence for tenant-supplied webhook URLs (shared/url_safety.py, shared/webhook.py)."""

import socket
import urllib.request
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from shared import url_safety
from shared.url_safety import UnsafeUrlError, resolve_public_ips, validate_public_https_url


def _addrinfo(*addresses: str) -> list[tuple]:
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, 443)) for a in addresses]


class TestValidatePublicHttpsUrl:
    @pytest.mark.parametrize(
        "url",
        [
            "https://erp.acme.com/hooks/shipx",
            "https://erp.acme.com:8443/hooks",
            "https://93.184.216.34/hook",
            "https://[2606:2800:220:1:248:1893:25c8:1946]/hook",
        ],
    )
    def test_accepts_public_targets(self, url):
        host, port = validate_public_https_url(url)
        assert host and port

    @pytest.mark.parametrize(
        "url",
        [
            "http://erp.acme.com/hook",  # not https
            "file:///etc/passwd",
            "ftp://erp.acme.com/hook",
            "https://",  # no host
            "https://user:pw@erp.acme.com/hook",  # embedded credentials
            "https://localhost/hook",
            "https://LOCALHOST./hook",
            "https://db.internal/hook",
            "https://printer.local/hook",
            "https://127.0.0.1/hook",
            "https://10.0.3.7/hook",  # VPC private range
            "https://172.16.0.5/hook",
            "https://192.168.1.1/hook",
            "https://169.254.169.254/latest/meta-data/",  # cloud metadata
            "https://100.64.0.1/hook",  # CGNAT
            "https://0.0.0.0/hook",
            "https://[::1]/hook",
            "https://[fe80::1]/hook",
            "https://[fd00::1]/hook",
            "https://[::ffff:10.0.0.1]/hook",  # IPv4-mapped private
            "https://2130706433/hook",  # 127.0.0.1 as a decimal integer
            "https://0x7f.1/hook",  # 127.0.0.1 in hex/short form
            "https://127.1/hook",
            "https://erp.acme.com:notaport/hook",
        ],
    )
    def test_rejects_unsafe_targets(self, url):
        with pytest.raises(UnsafeUrlError):
            validate_public_https_url(url)


class TestResolvePublicIps:
    def test_returns_public_addresses(self):
        with patch("socket.getaddrinfo", return_value=_addrinfo("93.184.216.34", "93.184.216.35")):
            assert resolve_public_ips("erp.acme.com", 443) == ["93.184.216.34", "93.184.216.35"]

    def test_rejects_hostname_resolving_to_private_address(self):
        with patch("socket.getaddrinfo", return_value=_addrinfo("10.0.3.7")):
            with pytest.raises(UnsafeUrlError):
                resolve_public_ips("innocent.example.com", 443)

    def test_rejects_when_any_address_is_private(self):
        # A multi-record answer must not be accepted just because one record is public.
        with patch("socket.getaddrinfo", return_value=_addrinfo("93.184.216.34", "169.254.169.254")):
            with pytest.raises(UnsafeUrlError):
                resolve_public_ips("rebind.example.com", 443)

    def test_unresolvable_host_is_rejected(self):
        with patch("socket.getaddrinfo", side_effect=socket.gaierror("nope")):
            with pytest.raises(UnsafeUrlError):
                resolve_public_ips("nope.example.com", 443)


class TestOpenPublicHttps:
    def test_refuses_before_any_connection_when_host_resolves_private(self):
        req = urllib.request.Request("https://innocent.example.com/hook", data=b"{}", method="POST")
        with (
            patch("socket.getaddrinfo", return_value=_addrinfo("10.0.3.7")),
            patch("socket.create_connection") as connect,
        ):
            with pytest.raises(UnsafeUrlError):
                url_safety.open_public_https(req, timeout=1)
        connect.assert_not_called()

    def test_redirects_are_not_followed(self):
        handler = url_safety._NoRedirect()
        assert handler.redirect_request(MagicMock(), None, 302, "Found", {}, "http://169.254.169.254/") is None

    def test_connects_to_the_validated_ip_not_a_fresh_dns_answer(self):
        conn = url_safety._PinnedHTTPSConnection("erp.acme.com", ["93.184.216.34"], timeout=1, context=MagicMock())
        with patch("socket.create_connection", return_value=MagicMock()) as connect:
            conn.connect()
        assert connect.call_args[0][0] == ("93.184.216.34", 443)
        # TLS is still verified against the original hostname, not the IP.
        assert conn._tls_context.wrap_socket.call_args.kwargs["server_hostname"] == "erp.acme.com"

    def test_pinned_connection_falls_back_across_validated_ips(self):
        conn = url_safety._PinnedHTTPSConnection(
            "erp.acme.com", ["93.184.216.34", "93.184.216.35"], timeout=1, context=MagicMock()
        )
        with patch("socket.create_connection", side_effect=[OSError("down"), MagicMock()]) as connect:
            conn.connect()
        assert [c.args[0][0] for c in connect.call_args_list] == ["93.184.216.34", "93.184.216.35"]


class TestWebhookDelivery:
    def test_test_delivery_reports_unsafe_url_without_touching_the_network(self):
        from shared import webhook

        cfg = {"url": "https://169.254.169.254/latest/meta-data/", "secret": "s", "enabled": True}
        with (
            patch.object(webhook, "_get_webhook_config", return_value=cfg),
            patch("socket.create_connection") as connect,
        ):
            result = webhook.test_fire_tenant_webhook("tenant-a")
        assert result["success"] is False
        assert result["status_code"] is None
        assert "private or reserved" in result["error"]
        connect.assert_not_called()

    def test_fire_never_raises_and_never_connects_for_unsafe_url(self):
        from shared import webhook

        cfg = {"url": "https://localhost/hook", "secret": "s", "enabled": True}
        with (
            patch.object(webhook, "_get_webhook_config", return_value=cfg),
            patch("socket.create_connection") as connect,
        ):
            webhook.fire_tenant_webhook("tenant-a", "billing.payment_due", {"x": 1})
        connect.assert_not_called()

    def test_fire_never_raises_on_a_malformed_stored_url(self):
        from shared import webhook

        cfg = {"url": "not a url at all", "secret": "s", "enabled": True}
        with patch.object(webhook, "_get_webhook_config", return_value=cfg):
            webhook.fire_tenant_webhook("tenant-a", "billing.payment_due", {"x": 1})


class TestWebhookConfigRequestModel:
    @pytest.mark.parametrize(
        "url",
        [
            "https://169.254.169.254/latest/meta-data/",
            "https://localhost/hook",
            "https://10.0.0.5/hook",
            "https://2130706433/hook",
        ],
    )
    def test_rejects_internal_targets_at_save_time(self, url):
        from services.tenant_management.models import WebhookConfigRequest

        with pytest.raises(ValidationError):
            WebhookConfigRequest(endpoint_url=url, enabled=True, events=[])

    def test_accepts_a_public_https_endpoint(self):
        from services.tenant_management.models import WebhookConfigRequest

        req = WebhookConfigRequest(endpoint_url="https://erp.acme.com/hooks/shipx", enabled=True, events=[])
        assert req.endpoint_url == "https://erp.acme.com/hooks/shipx"
