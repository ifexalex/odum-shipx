"""Unit tests for shared/http_routing.py — the route table + public-route
matcher shared by the dev server, the container HTTP app, and (by mirroring)
production API Gateway."""

from shared import http_routing


class TestResolveService:
    def test_simple_prefix(self):
        assert http_routing.resolve_service("/v1/billing") == "billing"
        assert http_routing.resolve_service("/v1/billing/123/disputes") == "billing"

    def test_query_string_is_ignored(self):
        assert http_routing.resolve_service("/v1/containers?status=open") == "tracking"

    def test_excel_export_overrides_owning_prefix(self):
        # /v1/billing/{id}/export is excel, not billing.
        assert http_routing.resolve_service("/v1/billing/1/export") == "excel"
        assert http_routing.resolve_service("/v1/manifests/1/export") == "excel"

    def test_pdf_override(self):
        assert http_routing.resolve_service("/v1/release-notes/1/pdf") == "excel"
        assert http_routing.resolve_service("/v1/payments/1/pdf") == "excel"

    def test_import_override(self):
        assert http_routing.resolve_service("/v1/packing-lists/import") == "excel"
        assert http_routing.resolve_service("/v1/packing-lists/import/presigned-url") == "excel"

    def test_container_packing_lists_subresource(self):
        assert http_routing.resolve_service("/v1/containers/abc/packing-lists") == "packing_list"

    def test_platform_usage_goes_to_metering(self):
        assert http_routing.resolve_service("/v1/platform/tenants/t1/usage") == "metering"
        # but other /v1/platform paths stay with tenant_management
        assert http_routing.resolve_service("/v1/platform/tenants") == "tenant_management"

    def test_unrouted_path_returns_none(self):
        assert http_routing.resolve_service("/v1/does-not-exist") is None

    def test_customer_export_is_not_excel(self):
        # /v1/customers/{id}/export is GDPR data export in tenant_management, not excel.
        assert http_routing.resolve_service("/v1/customers/1/export") == "tenant_management"


class TestIsPublicRoute:
    def test_health_is_public(self):
        assert http_routing.is_public_route("GET", "/v1/health") is True

    def test_public_tracking_with_path_param(self):
        assert http_routing.is_public_route("GET", "/v1/shipments/TRACK123") is True

    def test_authenticated_shipments_list_is_not_public(self):
        assert http_routing.is_public_route("GET", "/v1/shipments") is False

    def test_webhooks_public_both_methods(self):
        assert http_routing.is_public_route("GET", "/v1/webhooks/whatsapp") is True
        assert http_routing.is_public_route("POST", "/v1/webhooks/whatsapp") is True
        assert http_routing.is_public_route("POST", "/v1/webhooks/payment") is True

    def test_invite_claim_routes(self):
        assert http_routing.is_public_route("GET", "/v1/invites/tok-123") is True
        assert http_routing.is_public_route("POST", "/v1/invites/tok-123/accept") is True

    def test_register_routes(self):
        assert http_routing.is_public_route("POST", "/v1/register") is True
        assert http_routing.is_public_route("POST", "/v1/register/acme") is True

    def test_auth_session_routes(self):
        for path in ("/v1/auth/session", "/v1/auth/refresh", "/v1/auth/logout"):
            assert http_routing.is_public_route("POST", path) is True

    def test_method_must_match(self):
        # /v1/register is public for POST only, not GET.
        assert http_routing.is_public_route("GET", "/v1/register") is False

    def test_wrong_segment_count_not_matched(self):
        assert http_routing.is_public_route("POST", "/v1/register/acme/extra") is False

    def test_query_string_ignored(self):
        assert http_routing.is_public_route("GET", "/v1/shipments/TRACK123?lang=en") is True
