"""Phase 0 permissioning security regression tests (C-2, C-3, C-4, H-1, H-5, H-9)."""

from unittest.mock import MagicMock, patch

import pytest

from services.search import service as search_service
from services.tenant_management import customers as customer_service
from services.tenant_management import handler as tm_handler
from services.tenant_management import tenant_config
from shared import auth as shared_auth
from shared.auth import _check_user_active as _real_check_user_active
from shared.exceptions import DuplicateResourceError
from shared.providers.azure.entra import EntraIdentityProvider
from shared.tenant_context import TenantContext, UserRole


class TestC3MultiRoleCustomerScopeBypass:
    def test_must_scope_to_customer_enforces_endpoint_staff_roles(self) -> None:
        mixed_wh = TenantContext(
            tenant_id="tenant-1",
            user_id="user-1",
            role=UserRole.WAREHOUSE_ATTENDANT,
            roles=frozenset({UserRole.WAREHOUSE_ATTENDANT, UserRole.CUSTOMER}),
        )
        # Not authorized as billing/admin staff -> must scope to own customer records!
        assert mixed_wh.must_scope_to_customer(UserRole.TENANT_ADMIN) is True
        assert mixed_wh.must_scope_to_customer(UserRole.TENANT_ADMIN, UserRole.NIGERIA_OFFICE_STAFF) is True
        # Authorized on warehouse-accessible routes -> staff scope allowed
        assert mixed_wh.must_scope_to_customer(UserRole.TENANT_ADMIN, UserRole.WAREHOUSE_ATTENDANT) is False
        # Customer-only endpoints (no staff roles) -> always scoped
        assert mixed_wh.must_scope_to_customer() is True

    def test_gdpr_export_enforces_ownership_for_multi_role_warehouse_plus_customer(self) -> None:
        ctx = TenantContext(
            tenant_id="tenant-1",
            user_id="user-wh",
            role=UserRole.WAREHOUSE_ATTENDANT,
            roles=frozenset({UserRole.WAREHOUSE_ATTENDANT, UserRole.CUSTOMER}),
        )
        event = {
            "requestContext": {"requestId": "req-1", "http": {"method": "GET", "path": "/v1/customers/cust-other/export"}},
            "headers": {},
        }
        with (
            patch.object(tm_handler, "get_tenant_context", return_value=ctx),
            patch.object(
                customer_service.repo,
                "get_customer_by_id",
                return_value={"id": "cust-other", "user_id": "different-user"},
            ),
        ):
            resp = tm_handler.lambda_handler(event, None)
        assert resp["statusCode"] == 404

    def test_global_search_pins_customer_only_kinds_for_mixed_warehouse_plus_customer(self) -> None:
        ctx = TenantContext(
            tenant_id="tenant-1",
            user_id="user-wh",
            role=UserRole.WAREHOUSE_ATTENDANT,
            roles=frozenset({UserRole.WAREHOUSE_ATTENDANT, UserRole.CUSTOMER}),
        )
        with (
            patch.object(search_service.repo, "get_customer_id_for_user", return_value="cust-own"),
            patch.object(search_service.repo, "search_release_notes", return_value=[]) as mock_rn,
            patch.object(search_service.repo, "search_invoices", return_value=[]) as mock_inv,
            patch.object(search_service.repo, "search_shipments", return_value=[]) as mock_ship,
        ):
            search_service.search("tenant-1", "INV-001", ctx)
        # Release notes allowed tenant-wide for warehouse_attendant
        assert mock_rn.call_args.kwargs["customer_id"] is None
        # Invoices & shipments are customer-only kinds -> MUST be pinned to cust-own!
        assert mock_inv.call_args.kwargs["customer_id"] == "cust-own"
        assert mock_inv.call_args.kwargs["by_name"] is False
        assert mock_ship.call_args.kwargs["customer_id"] == "cust-own"


class TestC4CustomerUserIdAndAdminErasureProtection:
    def test_update_customer_strips_user_id_and_consent_given_at(self) -> None:
        with (
            patch.object(customer_service.repo, "get_customer_by_id", return_value={"id": "c-1", "name": "Ada"}),
            patch.object(customer_service.repo, "get_tenant_by_id", return_value={"destination_country": "NG"}),
            patch.object(customer_service.repo, "update_customer", return_value={"id": "c-1", "name": "Ada"}) as mock_upd,
            patch.object(customer_service, "log_audit"),
        ):
            customer_service.update_customer(
                "tenant-1",
                "c-1",
                {"name": "Ada", "user_id": "hijacked-admin-id", "consent_given_at": "2020-01-01"},
                actor_id="staff-1",
            )
        passed_updates = mock_upd.call_args[0][2]
        assert "user_id" not in passed_updates

    def test_anonymise_customer_never_revokes_or_erases_staff_or_admin_login(self) -> None:
        admin_login = {
            "id": "admin-1",
            "email": "admin@acme.test",
            "status": "active",
            "role": "tenant_admin",
            "roles": ["tenant_admin"],
        }
        with (
            patch.object(
                customer_service.repo,
                "get_customer_by_id",
                return_value={"id": "c-1", "name": "Ada", "user_id": "admin-1", "anonymised_at": None},
            ),
            patch.object(customer_service.repo, "get_user_by_id", return_value=admin_login),
            patch.object(customer_service, "_revoke_login") as mock_revoke,
            patch.object(customer_service, "_erase_login_identity") as mock_erase,
            patch.object(customer_service.repo, "delete_unconsumed_invites_for_customer"),
            patch.object(customer_service.repo, "anonymise_customer_record"),
            patch.object(customer_service, "log_audit"),
        ):
            customer_service.anonymise_customer("tenant-1", "c-1", actor_id="admin-2")
        mock_revoke.assert_not_called()
        mock_erase.assert_not_called()


class TestC2EntraDuplicateProtection:
    def test_entra_create_propagates_duplicate_resource_error(self) -> None:
        provider = EntraIdentityProvider.__new__(EntraIdentityProvider)
        provider._local_accounts = True
        provider._user_domain = "example.onmicrosoft.com"
        provider._graph = MagicMock(side_effect=DuplicateResourceError("user", "admin@shipx.test"))
        with pytest.raises(DuplicateResourceError):
            provider._create("admin@shipx.test", "Admin", "tenant-1", "customer", "test-password", force_change=False)


class TestH1AndH5AuthIdentityResolutionWithoutRedis:
    def test_check_user_active_returns_full_db_roles_even_when_redis_disabled(self) -> None:
        shared_auth.evict_identity_cache("user-sub-1", "canonical-uuid-1")
        with (
            patch.object(shared_auth._identity_cache, "get", return_value=None),
            patch.object(shared_auth._identity_cache, "set"),
            patch.object(shared_auth._identity_roles_cache, "get", return_value=None),
            patch.object(shared_auth._identity_roles_cache, "set"),
            patch(
                "shared.db.execute_with_tenant",
                return_value=[
                    {
                        "id": "canonical-uuid-1",
                        "tenant_id": "tenant-1",
                        "role": "nigeria_office_staff",
                        "roles": ["nigeria_office_staff", "warehouse_attendant"],
                    }
                ],
            ),
        ):
            checked = _real_check_user_active("user-sub-1", "tenant-1")
        assert checked == (
            "nigeria_office_staff",
            frozenset({UserRole.NIGERIA_OFFICE_STAFF, UserRole.WAREHOUSE_ATTENDANT}),
        )
        assert shared_auth._canonical_user_id("user-sub-1") == "canonical-uuid-1"
        # Evicting by canonical id automatically clears the cognito_sub alias too
        shared_auth.evict_identity_cache("canonical-uuid-1")
        assert shared_auth._cached_db_roles("user-sub-1") is None


class TestH9RoleScopedTenantConfig:
    def test_customer_cannot_read_internal_pricing_thresholds_or_webhook_urls(self) -> None:
        rows = [
            {"config_key": "branding_config", "config_value": {"company_name": "Acme"}},
            {"config_key": "bank_transfer_config", "config_value": {"bank_name": "GTBank"}},
            {"config_key": "dollar_rate_markup", "config_value": {"markup_ngn": 50}},
            {"config_key": "cbm_rate_per_unit", "config_value": {"default": 45}},
            {"config_key": "refund_threshold_usd", "config_value": {"staff_limit": 50}},
            {"config_key": "webhook_config", "config_value": {"endpoint_url": "https://erp.internal/hook", "secret": "s"}},
            {"config_key": "paystack_config", "config_value": {"enabled": True, "last4": "9999", "configured_by": "u-1"}},
        ]
        cust_ctx = TenantContext(tenant_id="tenant-1", user_id="u-cust", role=UserRole.CUSTOMER)
        admin_ctx = TenantContext(tenant_id="tenant-1", user_id="u-admin", role=UserRole.TENANT_ADMIN)

        with patch.object(tenant_config.repo, "get_all_configs", return_value=rows):
            cust_cfg = tenant_config.get_tenant_config("tenant-1", ctx=cust_ctx)
            admin_cfg = tenant_config.get_tenant_config("tenant-1", ctx=admin_ctx)

        assert set(cust_cfg.keys()) == {"branding_config", "bank_transfer_config", "default_transit_days", "paystack_config"}
        assert cust_cfg["paystack_config"] == {"enabled": True}
        assert "dollar_rate_markup" not in cust_cfg
        assert "webhook_config" not in cust_cfg
        assert "refund_threshold_usd" not in cust_cfg

        assert "dollar_rate_markup" in admin_cfg
        assert "webhook_config" in admin_cfg
        assert admin_cfg["paystack_config"]["last4"] == "9999"
