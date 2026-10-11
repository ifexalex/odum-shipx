"""Unit tests for shipping-company (tenant) onboarding — admin/sales-led.

Covers the service lead-capture, the public `POST /v1/onboarding-requests` route
(no JWT, no account created), the platform-admin review routes, and the
create_tenant → lead linking. Fully mocked (no DB, no Cognito/Entra)."""

import json
from unittest.mock import MagicMock, patch

from services.tenant_management import handler, service
from services.tenant_management.models import (
    CreateOnboardingRequest,
    CreateTenantRequest,
    InitialAdminInput,
    SubscriptionTier,
)
from shared.tenant_context import PLATFORM_TENANT_ID, TenantContext, UserRole

_LEAD = {"company_name": "Acme Freight", "contact_name": "Ada Obi", "contact_email": "ops@acme.com"}


def _event(method: str, path: str, body: dict | None = None) -> dict:
    return {
        "requestContext": {"requestId": "r1", "http": {"method": method, "path": path}},
        "headers": {},
        "body": json.dumps(body) if body is not None else None,
        "cookies": [],
    }


def _ctx(role: UserRole) -> TenantContext:
    tid = PLATFORM_TENANT_ID if role == UserRole.PLATFORM_ADMIN else "t1"
    return TenantContext(tenant_id=tid, user_id="actor-1", role=role)


# ── Service: lead capture ────────────────────────────────────────────────────
class TestCreateOnboardingRequestService:
    def test_inserts_lead_and_publishes_event(self):
        row = {"id": "req-1", "status": "new"}
        with (
            patch.object(service.repo, "insert_onboarding_request", return_value=row) as ins,
            patch("services.tenant_management.service.publish_event") as pub,
        ):
            result = service.create_onboarding_request(CreateOnboardingRequest(**_LEAD))
        assert result == {"id": "req-1", "status": "new"}
        ins.assert_called_once()
        # No account/tenant fields leak back to the public caller.
        assert set(result) == {"id", "status"}
        pub.assert_called_once()

    def test_event_failure_does_not_fail_capture(self):
        row = {"id": "req-2", "status": "new"}
        with (
            patch.object(service.repo, "insert_onboarding_request", return_value=row),
            patch("services.tenant_management.service.publish_event", side_effect=RuntimeError("bus down")),
        ):
            result = service.create_onboarding_request(CreateOnboardingRequest(**_LEAD))
        assert result["id"] == "req-2"


# ── Public route: POST /v1/onboarding-requests (no JWT) ──────────────────────
class TestPublicRoute:
    def test_post_needs_no_auth_and_returns_201(self):
        with patch.object(service, "create_onboarding_request", return_value={"id": "req-1", "status": "new"}) as svc:
            resp = handler.lambda_handler(_event("POST", "/v1/onboarding-requests", _LEAD), None)
        assert resp["statusCode"] == 201
        svc.assert_called_once()

    def test_missing_required_fields_returns_422(self):
        resp = handler.lambda_handler(_event("POST", "/v1/onboarding-requests", {"company_name": "Acme"}), None)
        assert resp["statusCode"] == 422

    def test_no_account_creation_path_invoked(self):
        # The lead route must never touch customer self-registration.
        with (
            patch.object(service, "create_onboarding_request", return_value={"id": "x", "status": "new"}),
            patch.object(service, "self_register_customer") as reg,
        ):
            handler.lambda_handler(_event("POST", "/v1/onboarding-requests", _LEAD), None)
        reg.assert_not_called()


# ── Platform routes: review queue (platform_admin only) ──────────────────────
class TestPlatformRoutes:
    def test_list_forbidden_for_non_platform_admin(self):
        with patch.object(handler, "get_tenant_context", return_value=_ctx(UserRole.TENANT_ADMIN)):
            resp = handler.lambda_handler(_event("GET", "/v1/platform/onboarding-requests"), None)
        assert resp["statusCode"] == 403

    def test_list_as_platform_admin(self):
        with (
            patch.object(handler, "get_tenant_context", return_value=_ctx(UserRole.PLATFORM_ADMIN)),
            patch.object(service, "list_onboarding_requests", return_value=[{"id": "req-1"}]) as svc,
        ):
            resp = handler.lambda_handler(_event("GET", "/v1/platform/onboarding-requests"), None)
        assert resp["statusCode"] == 200
        svc.assert_called_once_with(status=None)

    def test_patch_status_as_platform_admin(self):
        with (
            patch.object(handler, "get_tenant_context", return_value=_ctx(UserRole.PLATFORM_ADMIN)),
            patch.object(service, "update_onboarding_request_status", return_value={"id": "req-1", "status": "contacted"}) as svc,
        ):
            resp = handler.lambda_handler(
                _event("PATCH", "/v1/platform/onboarding-requests/req-1", {"status": "contacted"}), None
            )
        assert resp["statusCode"] == 200
        svc.assert_called_once()


# ── create_tenant links + closes the lead when provisioned from one ──────────
class TestProvisioningLinksLead:
    def _req(self, onboarding_request_id=None):
        return CreateTenantRequest(
            company_name="Acme Freight",
            primary_contact_email="ops@acme.com",
            subscription_tier=SubscriptionTier.business,
            initial_admin=InitialAdminInput(email="admin@acme.com", full_name="Ada Obi"),
            onboarding_request_id=onboarding_request_id,
        )

    def test_provision_marks_request_provisioned(self):
        tenant = {"id": "tenant-123", "company_name": "Acme Freight"}
        admin_user = {"id": "admin-user-1", "email": "admin@acme.com"}
        mock_idp = MagicMock()
        mock_idp.create_user.return_value = "sub-1"
        with (
            patch.object(service, "get_identity_provider", return_value=mock_idp),
            patch.object(service.repo, "create_tenant", return_value=tenant),
            patch.object(service.repo, "create_tenant_user", return_value=admin_user),
            patch.object(service.repo, "upsert_config"),
            patch.object(service.repo, "insert_platform_audit"),
            patch("services.tenant_management.service.publish_event"),
            patch("shared.notifications.enqueue_notifications"),
            patch.object(service.repo, "update_onboarding_request") as upd,
        ):
            service.create_tenant(self._req(onboarding_request_id="req-1"), actor_id="platform-admin")
        upd.assert_called_once()
        args, kwargs = upd.call_args
        assert args[0] == "req-1"
        assert args[1]["status"] == "provisioned"
        assert args[1]["tenant_id"] == "tenant-123"

    def test_no_request_id_does_not_touch_leads(self):
        tenant = {"id": "tenant-123", "company_name": "Acme Freight"}
        admin_user = {"id": "admin-user-1", "email": "admin@acme.com"}
        mock_idp = MagicMock()
        mock_idp.create_user.return_value = "sub-1"
        with (
            patch.object(service, "get_identity_provider", return_value=mock_idp),
            patch.object(service.repo, "create_tenant", return_value=tenant),
            patch.object(service.repo, "create_tenant_user", return_value=admin_user),
            patch.object(service.repo, "upsert_config"),
            patch.object(service.repo, "insert_platform_audit"),
            patch("services.tenant_management.service.publish_event"),
            patch("shared.notifications.enqueue_notifications"),
            patch.object(service.repo, "update_onboarding_request") as upd,
        ):
            service.create_tenant(self._req(), actor_id="platform-admin")
        upd.assert_not_called()
