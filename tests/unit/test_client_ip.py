"""Unit tests for shared.client_ip: which address a request really came from (audit SEC-03).

It matters for two reasons. Rate limits are keyed on it, so an address a client can choose lets it dodge
them, and an address shared by everyone lumps every user into one client. Audit logs record it too.
"""

import json
from unittest.mock import patch

import pytest

from shared.client_ip import client_ip, resolve_client_ip, trusted_proxy_hops


class TestClientIpFromTheEvent:
    def test_reads_the_http_api_location(self):
        """API Gateway's HTTP API (payload 2.0), which is what production runs behind."""
        assert client_ip({"requestContext": {"http": {"sourceIp": "203.0.113.7"}}}) == "203.0.113.7"

    def test_reads_the_rest_api_and_container_location(self):
        assert client_ip({"requestContext": {"identity": {"sourceIp": "203.0.113.8"}}}) == "203.0.113.8"

    def test_the_http_api_location_wins(self):
        event = {"requestContext": {"http": {"sourceIp": "203.0.113.7"}, "identity": {"sourceIp": "10.0.0.1"}}}
        assert client_ip(event) == "203.0.113.7"

    @pytest.mark.parametrize("event", [{}, {"requestContext": {}}, {"requestContext": {"http": {}, "identity": {}}}])
    def test_no_address_is_none_not_an_empty_string(self, event):
        """An empty string would reach the audit log's inet column and fail the insert."""
        assert client_ip(event) is None


class TestResolveClientIp:
    def test_with_no_proxy_the_peer_is_the_client(self):
        assert resolve_client_ip("203.0.113.7", "", 0) == "203.0.113.7"

    def test_a_local_developer_is_a_client_too(self):
        assert resolve_client_ip("127.0.0.1", "", 0) == "127.0.0.1"

    def test_with_proxies_the_client_is_counted_from_the_end(self):
        # Front Door appends the user, the ingress appends Front Door.
        assert resolve_client_ip("100.100.0.4", "203.0.113.7, 147.243.0.9", 2) == "203.0.113.7"

    def test_whatever_the_client_put_at_the_front_is_ignored(self):
        """A client can send its own X-Forwarded-For; only what the proxies appended can be trusted."""
        forged = "6.6.6.6, 203.0.113.7, 147.243.0.9"
        assert resolve_client_ip("100.100.0.4", forged, 2) == "203.0.113.7"

    def test_a_forged_header_cannot_choose_the_address_when_one_proxy_is_trusted(self):
        assert resolve_client_ip("10.0.0.2", "1.2.3.4, 203.0.113.7", 1) == "203.0.113.7"

    def test_fewer_entries_than_proxies_means_unknown_not_a_guess(self):
        assert resolve_client_ip("100.100.0.4", "203.0.113.7", 2) is None

    def test_no_header_at_all_with_proxies_configured_means_unknown(self):
        assert resolve_client_ip("100.100.0.4", "", 1) is None

    def test_a_garbage_entry_is_not_an_address(self):
        assert resolve_client_ip("100.100.0.4", "203.0.113.7, not-an-ip", 1) is None

    @pytest.mark.parametrize("proxy", ["10.1.2.3", "172.16.0.9", "192.168.1.1", "100.100.0.4", "169.254.1.1"])
    def test_an_unconfigured_proxy_is_not_mistaken_for_the_client(self, proxy):
        """Behind a proxy nobody told us about, the peer is the proxy: answering with it would put every user in one bucket."""
        assert resolve_client_ip(proxy, "203.0.113.7", 0) is None

    def test_an_internal_peer_without_a_proxy_header_is_just_a_client(self):
        """A private network with no proxy in front of it (a docker network, an office) is not hiding anyone."""
        assert resolve_client_ip("10.1.2.3", "", 0) == "10.1.2.3"

    def test_a_public_peer_is_the_client_even_if_it_sent_a_header(self):
        """No proxy is configured and the peer is a public address, so it connected directly; the header is its own claim."""
        assert resolve_client_ip("8.8.8.8", "6.6.6.6", 0) == "8.8.8.8"  # a genuinely public address

    @pytest.mark.parametrize("peer", ["", "not-an-ip"])
    def test_an_unusable_peer_is_unknown(self, peer):
        assert resolve_client_ip(peer, "", 0) is None

    def test_ipv6_works(self):
        assert resolve_client_ip("2001:db8::1", "", 0) == "2001:db8::1"
        assert resolve_client_ip("fd00::1", "2001:db8::7", 1) == "2001:db8::7"


class TestTrustedProxyHops:
    @pytest.mark.parametrize(("value", "expected"), [("2", 2), ("0", 0), ("", 0), ("two", 0), ("-1", 0), (" 3 ", 3)])
    def test_reads_the_environment_defensively(self, value, expected):
        with patch.dict("os.environ", {"TRUSTED_PROXY_HOPS": value}):
            assert trusted_proxy_hops() == expected

    def test_defaults_to_none(self):
        with patch.dict("os.environ", {}, clear=False) as env:
            env.pop("TRUSTED_PROXY_HOPS", None)
            assert trusted_proxy_hops() == 0


class TestHandlersUseIt:
    def test_a_handler_records_the_address_from_the_http_api_event(self):
        """Production events carry it at requestContext.http.sourceIp; the handlers used to read only identity."""
        from services.tenant_management import service
        from services.tenant_management.handler import lambda_handler

        event = {
            "requestContext": {
                "requestId": "r1",
                "http": {"method": "POST", "path": "/v1/register/acme", "sourceIp": "203.0.113.7"},
            },
            "headers": {},
            "body": json.dumps({"name": "Ngozi", "email": "ngozi@example.test", "phone": "08012345678"}),
        }
        with patch.object(service, "self_register_customer", return_value=None) as register:
            lambda_handler(event, None)
        assert register.call_args.kwargs["ip_address"] == "203.0.113.7"


class TestContainerApp:
    """services/http_app/app.py builds the event for the container deployment."""

    @staticmethod
    def _event(remote_addr: str, headers: dict | None = None) -> dict:
        from services.http_app import app as http_app

        with http_app.app.test_request_context(
            "/v1/x", method="GET", headers=headers or {}, environ_base={"REMOTE_ADDR": remote_addr}
        ):
            return http_app._build_event(None)

    def test_a_direct_client_is_recorded(self):
        event = self._event("203.0.113.7")
        assert client_ip(event) == "203.0.113.7"

    def test_behind_a_configured_proxy_the_users_address_is_recorded_not_the_proxys(self):
        with patch.dict("os.environ", {"TRUSTED_PROXY_HOPS": "2"}):
            event = self._event("100.100.0.4", {"X-Forwarded-For": "6.6.6.6, 203.0.113.7, 147.243.0.9"})
        assert client_ip(event) == "203.0.113.7"

    def test_behind_an_unconfigured_proxy_no_address_is_recorded(self):
        """Better no address than the proxy's: audit logs stay honest and per-client limits skip rather than share a bucket."""
        with patch.dict("os.environ", {"TRUSTED_PROXY_HOPS": "0"}):
            event = self._event("100.100.0.4", {"X-Forwarded-For": "203.0.113.7"})
        assert client_ip(event) is None
        assert "sourceIp" not in event["requestContext"]["http"]
